"""Origin-checked, single-use password recovery with captured-mail development support."""

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import hmac
import secrets
import smtplib
import ssl
import threading
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import AuthSession, PasswordRecoveryChallenge, User
from .dependencies import InvalidCsrfToken
from .schemas import PasswordResetComplete, PasswordResetRequest
from .security import hash_password
from .service import utc_now


router = APIRouter(prefix="/auth", tags=["authentication"])
_GENERIC_RESPONSE = {"message": "If an account exists for that email, recovery instructions have been sent."}
_INVALID_RESPONSE = {"error": {"code": "password_reset_invalid", "message": "The recovery request is invalid or expired."}}


class WindowLimiter:
    """Per-process request guard; challenge attempts are also persisted in the database."""

    def __init__(self):
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        import time

        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - settings.password_reset_rate_window_seconds:
                events.popleft()
            if len(events) >= settings.password_reset_rate_limit_count:
                return False
            events.append(now)
            if len(self._events) > 5000:
                for stale in [name for name, values in self._events.items() if not values or values[-1] <= now - settings.password_reset_rate_window_seconds]:
                    self._events.pop(stale, None)
            return True


rate_limiter = WindowLimiter()


def _email_key(email: str) -> str:
    return hmac.new(settings.password_reset_pepper.encode(), email.encode(), hashlib.sha256).hexdigest()


def _code_verifier(code: str) -> str:
    return hmac.new(settings.password_reset_pepper.encode(), code.encode(), hashlib.sha256).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _remote_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _message(recipient: str, code: str) -> EmailMessage:
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = settings.smtp_from
    message["Subject"] = "Your DressMe recovery code"
    message.set_content(
        "Use this one-time DressMe password recovery code:\n\n"
        f"{code}\n\nIt expires shortly. If you did not request this, you can ignore this email."
    )
    return message


def deliver_recovery_email(recipient: str, code: str) -> None:
    message = _message(recipient, code)
    if settings.email_delivery_mode == "capture":
        settings.email_capture_path.mkdir(parents=True, exist_ok=True)
        # Captured email is a local developer mailbox, kept outside static serving and ignored by Git.
        destination = settings.email_capture_path / f"{uuid.uuid4().hex}.eml"
        destination.write_bytes(message.as_bytes())
        return

    context = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds, context=context) as smtp:
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as smtp:
        smtp.ehlo()
        if settings.smtp_security == "starttls":
            smtp.starttls(context=context)
            smtp.ehlo()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin or origin not in settings.frontend_origins:
        raise InvalidCsrfToken()
    return True


@router.post("/password-reset/request", status_code=202)
def request_password_reset(body: PasswordResetRequest, request: Request, db: Session = Depends(get_db)):
    _origin_allowed(request)
    remote = _remote_key(request)
    address_key = _email_key(body.email)
    allowed = rate_limiter.allow(f"request-ip:{remote}") and rate_limiter.allow(f"request-email:{address_key}")
    if not allowed:
        # Keep the public response identical for existing, unknown and throttled addresses.
        return JSONResponse(status_code=202, content=_GENERIC_RESPONSE)

    now = utc_now()
    user = db.scalar(select(User).where(User.email == body.email).with_for_update())
    if user is not None:
        challenge = db.scalar(
            select(PasswordRecoveryChallenge)
            .where(PasswordRecoveryChallenge.user_id == user.id)
            .with_for_update()
        )
        if challenge is not None and challenge.consumed_at is None:
            created = _as_utc(challenge.created_at)
            if created > now - timedelta(seconds=settings.password_reset_cooldown_seconds):
                return JSONResponse(status_code=202, content=_GENERIC_RESPONSE)

        code = f"{secrets.randbelow(100_000_000):08d}"
        if challenge is None:
            challenge = PasswordRecoveryChallenge(
                user_id=user.id,
                code_verifier=_code_verifier(code),
                created_at=now,
                expires_at=now + timedelta(seconds=settings.password_reset_code_ttl_seconds),
                attempts=0,
            )
            db.add(challenge)
        else:
            # Replacing the verifier invalidates any previously delivered code.
            challenge.code_verifier = _code_verifier(code)
            challenge.created_at = now
            challenge.expires_at = now + timedelta(seconds=settings.password_reset_code_ttl_seconds)
            challenge.attempts = 0
            challenge.consumed_at = None
        try:
            deliver_recovery_email(body.email, code)
            db.commit()
        except Exception:
            db.rollback()
            # Do not reveal whether an account exists or whether its mail provider failed.
    return JSONResponse(status_code=202, content=_GENERIC_RESPONSE)


@router.post("/password-reset/complete")
def complete_password_reset(body: PasswordResetComplete, request: Request, db: Session = Depends(get_db)):
    _origin_allowed(request)
    address_key = _email_key(body.email)
    remote = _remote_key(request)
    if not rate_limiter.allow(f"verify-ip:{remote}") or not rate_limiter.allow(f"verify-email:{address_key}"):
        return JSONResponse(status_code=429, content=_INVALID_RESPONSE)

    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        # Do comparable keyed work for unknown addresses without storing or sending anything.
        hmac.compare_digest(_code_verifier(body.code), _code_verifier("00000000"))
        db.rollback()
        return JSONResponse(status_code=400, content=_INVALID_RESPONSE)

    challenge = db.scalar(
        select(PasswordRecoveryChallenge)
        .where(PasswordRecoveryChallenge.user_id == user.id)
    )
    now = utc_now()
    supplied_verifier = _code_verifier(body.code)
    valid = (
        challenge is not None
        and challenge.consumed_at is None
        and challenge.attempts < settings.password_reset_attempt_limit
        and _as_utc(challenge.expires_at) > now
        and hmac.compare_digest(supplied_verifier, challenge.code_verifier)
    )

    if valid:
        # The conditional UPDATE is the atomic single-use claim. Concurrent submissions
        # serialize on this row in PostgreSQL; only one can observe rowcount == 1.
        claimed = db.execute(
            update(PasswordRecoveryChallenge)
            .where(
                PasswordRecoveryChallenge.user_id == user.id,
                PasswordRecoveryChallenge.code_verifier == supplied_verifier,
                PasswordRecoveryChallenge.consumed_at.is_(None),
                PasswordRecoveryChallenge.attempts < settings.password_reset_attempt_limit,
                PasswordRecoveryChallenge.expires_at > now,
            )
            .values(consumed_at=now)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount == 1:
            user.password_hash = hash_password(body.new_password)
            db.execute(
                update(AuthSession)
                .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now)
                .execution_options(synchronize_session=False)
            )
            db.commit()
            return JSONResponse(status_code=204, content=None)

    if challenge is not None:
        # Count invalid, expired and mismatched submissions atomically. Exhaustion burns it.
        db.execute(
            update(PasswordRecoveryChallenge)
            .where(
                PasswordRecoveryChallenge.user_id == user.id,
                PasswordRecoveryChallenge.consumed_at.is_(None),
                PasswordRecoveryChallenge.attempts < settings.password_reset_attempt_limit,
            )
            .values(
                attempts=PasswordRecoveryChallenge.attempts + 1,
                consumed_at=now if challenge.attempts + 1 >= settings.password_reset_attempt_limit else None,
            )
            .execution_options(synchronize_session=False)
        )
    db.commit()
    return JSONResponse(status_code=400, content=_INVALID_RESPONSE)
