from dataclasses import dataclass
from datetime import timezone

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import AuthSession, User
from .security import secret_hash, secret_matches
from .service import utc_now


class AuthenticationRequired(Exception):
    pass


class InvalidCsrfToken(Exception):
    pass


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


def session_context(request: Request, db: Session) -> AuthContext | None:
    raw = request.cookies.get(settings.auth_cookie_name)
    if not raw:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == secret_hash(raw)))
    if session is None or session.revoked_at is not None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= utc_now():
        return None
    user = db.get(User, session.user_id)
    if user is None:
        return None
    return AuthContext(user=user, session=session)


def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    context = session_context(request, db)
    if context is None:
        raise AuthenticationRequired()
    return context


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    return get_auth_context(request, db).user


def current_user_csrf(request: Request, db: Session = Depends(get_db)) -> User:
    context = get_auth_context(request, db)
    require_csrf(request, context)
    return context.user


def require_request_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin or origin not in settings.frontend_origins:
        raise InvalidCsrfToken()


def require_csrf(request: Request, context: AuthContext) -> None:
    require_request_origin(request)
    supplied = request.headers.get(settings.csrf_header_name, "")
    if not supplied or not secret_matches(supplied, context.session.csrf_hash):
        raise InvalidCsrfToken()
