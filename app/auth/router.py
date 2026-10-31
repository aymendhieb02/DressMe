from datetime import timezone
import hashlib
import re

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..common.errors import error_response
from ..config import settings
from ..database import get_db
from ..models import Avatar, AvatarRender, AuthSession, Garment, PendingUpload, PersonPhoto, StorageDeletion, TryOnJob, User
from ..storage.cleanup import acknowledge_storage_deletion, record_storage_deletion_failure
from ..storage.local_disk import LocalPrivateStorage
from ..tryon.deletion import delete_jobs
from .dependencies import (
    AuthContext,
    AuthenticationRequired,
    InvalidCsrfToken,
    get_auth_context,
    require_csrf,
    require_request_origin,
    session_context,
)
from .rate_limit import rate_limit_login
from .schemas import AccountDelete, AuthResponse, LoginCredentials, RegisterCredentials, CsrfToken, UserPublic
from .security import new_secret, secret_hash, verify_password
from .service import authenticate, create_session, create_user, find_user, utc_now


router = APIRouter(prefix="/auth", tags=["authentication"])
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _cookie(response: Response, value: str) -> None:
    response.set_cookie(
        settings.auth_cookie_name,
        value,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _public(user) -> UserPublic:
    return UserPublic(id=user.id, email=user.email, role=user.role, created_at=user.created_at)


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin", "").rstrip("/")
    return bool(origin and origin in settings.frontend_origins)


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(body: RegisterCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    if not _origin_ok(request):
        raise InvalidCsrfToken()
    email = body.email
    if not _EMAIL_SHAPE.fullmatch(email):
        return error_response(request, 422, "validation_error", "One or more request fields are invalid.")
    key = hashlib.sha256(email.encode("utf-8")).hexdigest()
    limited = rate_limit_login(request, key)
    if limited:
        return limited
    if find_user(db, email):
        return error_response(request, 409, "account_unavailable", "An account with that email cannot be created.")
    try:
        user = create_user(db, email, body.password)
        _, cookie_token, csrf_token = create_session(db, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        return error_response(request, 409, "account_unavailable", "An account with that email cannot be created.")
    _cookie(response, cookie_token)
    return AuthResponse(user=_public(user), csrf_token=csrf_token)


@router.post("/login", response_model=AuthResponse)
def login(body: LoginCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    if not _origin_ok(request):
        raise InvalidCsrfToken()
    email = body.email
    key = hashlib.sha256(email.encode("utf-8")).hexdigest()
    limited = rate_limit_login(request, key)
    if limited:
        return limited
    user = authenticate(db, email, body.password)
    if user is None:
        return error_response(request, 401, "invalid_credentials", "Email or password is incorrect.")
    _, cookie_token, csrf_token = create_session(db, user)
    db.commit()
    _cookie(response, cookie_token)
    return AuthResponse(user=_public(user), csrf_token=csrf_token)


@router.get("/me", response_model=UserPublic)
def me(context: AuthContext = Depends(get_auth_context)):
    return _public(context.user)


@router.post("/csrf", response_model=CsrfToken)
def bootstrap_csrf(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    if request.headers.get("X-CSRF-Bootstrap") != "1":
        raise InvalidCsrfToken()
    csrf_token = new_secret()
    context.session.csrf_hash = secret_hash(csrf_token)
    db.commit()
    return CsrfToken(csrf_token=csrf_token)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    context = session_context(request, db)
    if context is not None:
        require_csrf(request, context)
        context.session.revoked_at = utc_now()
        db.commit()
    elif request.cookies.get(settings.auth_cookie_name) and not _origin_ok(request):
        raise InvalidCsrfToken()
    response.delete_cookie(
        settings.auth_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post("/refresh", response_model=AuthResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    context = session_context(request, db)
    if context is None:
        raw_cookie = request.cookies.get(settings.auth_cookie_name)
        old = db.scalar(select(AuthSession).where(AuthSession.token_hash == secret_hash(raw_cookie))) if raw_cookie else None
        # A previously valid, revoked cookie replayed with its CSRF proof revokes the family.
        if old is not None and old.revoked_at is not None and _origin_ok(request):
            supplied = request.headers.get(settings.csrf_header_name, "")
            if supplied and secret_hash(supplied) == old.csrf_hash:
                family_id = old.family_id or old.id
                db.execute(update(AuthSession).where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None)).values(revoked_at=utc_now()))
                db.commit()
        return error_response(request, 401, "refresh_invalid", "The session cannot be refreshed.")
    require_csrf(request, context)
    old = context.session
    family_id = old.family_id or old.id
    now = utc_now()
    rotation = db.execute(
        update(AuthSession)
        .where(
            AuthSession.id == old.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .values(family_id=family_id, revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    if rotation.rowcount != 1:
        db.rollback()
        return error_response(request, 401, "refresh_invalid", "The session cannot be refreshed.")
    _session, cookie_token, csrf_token = create_session(db, context.user, family_id=family_id)
    db.commit()
    _cookie(response, cookie_token)
    return AuthResponse(user=_public(context.user), csrf_token=csrf_token)


@router.delete("/account", status_code=204)
def delete_account(
    body: AccountDelete,
    request: Request,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    # Resolve the same request-scoped session and enforce double-submit CSRF before deletion.
    require_csrf(request, context)
    user = db.get(User, context.user.id)
    if user is None or not verify_password(user.password_hash, body.password):
        return error_response(request, 403, "account_delete_rejected", "The password or confirmation is incorrect.")

    pending = db.scalars(select(PendingUpload).where(PendingUpload.user_id == user.id)).all()
    garments = db.scalars(select(Garment).where(Garment.user_id == user.id)).all()
    photos = db.scalars(select(PersonPhoto).where(PersonPhoto.user_id == user.id)).all()
    avatars = db.scalars(select(Avatar).where(Avatar.user_id == user.id)).all()
    avatar_renders = db.scalars(select(AvatarRender).where(AvatarRender.user_id == user.id)).all()
    jobs = db.scalars(select(TryOnJob).where(TryOnJob.user_id == user.id)).all()
    keys = {row.image_key for row in pending} | {row.image_key for row in garments} | {row.image_key for row in photos}
    keys |= {row.asset_key for row in avatars}
    keys |= {row.image_key for row in avatar_renders}
    keys |= {row.result_key for row in jobs if row.result_key}
    existing = set(db.scalars(select(StorageDeletion.image_key).where(StorageDeletion.image_key.in_(keys))).all()) if keys else set()
    for key in keys - existing:
        db.add(StorageDeletion(image_key=key))
    delete_jobs(db, jobs)
    for row in garments:
        db.delete(row)
    db.flush()
    for row in photos:
        db.delete(row)
    for row in avatars:
        db.delete(row)
    for row in pending:
        db.delete(row)
    db.delete(user)
    db.commit()

    storage = LocalPrivateStorage()
    cleanup_pending = False
    for key in keys:
        try:
            storage.delete(key)
        except Exception:
            record_storage_deletion_failure(db, key)
            cleanup_pending = True
            continue
        acknowledge_storage_deletion(db, key)
    if cleanup_pending:
        result = JSONResponse(status_code=202, content={"status": "deletion_queued", "message": "The account was deleted; private file cleanup is queued for retry."})
        result.delete_cookie(settings.auth_cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
        return result
    response.delete_cookie(settings.auth_cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    response.status_code = 204
    return response
