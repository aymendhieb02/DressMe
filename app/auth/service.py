from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuthSession, User
from .security import hash_password, new_secret, secret_hash, verify_password

_DUMMY_PASSWORD_HASH = hash_password("dressme-fixed-invalid-account-check")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def create_user(db: Session, email: str, password: str, gender: str | None = None) -> User:
    user = User(email=email, password_hash=hash_password(password), gender=gender)
    db.add(user)
    db.flush()
    return user


def create_session(db: Session, user: User, family_id: uuid.UUID | None = None) -> tuple[AuthSession, str, str]:
    if family_id is None:
        # A new independent login replaces every earlier browser session.
        db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=utc_now()))
    cookie_token = new_secret()
    csrf_token = new_secret()
    session = AuthSession(
        user_id=user.id,
        token_hash=secret_hash(cookie_token),
        csrf_hash=secret_hash(csrf_token),
        family_id=family_id or uuid.uuid4(),
        expires_at=utc_now() + timedelta(seconds=settings.session_ttl_seconds),
    )
    db.add(session)
    db.flush()
    return session, cookie_token, csrf_token


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = find_user(db, email)
    if user is None:
        verify_password(_DUMMY_PASSWORD_HASH, password)
        return None
    return user if verify_password(user.password_hash, password) else None
