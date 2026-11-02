"""Short lived, DB-bound access credentials for the browser application."""
from datetime import timedelta
import uuid

import jwt
from jwt import InvalidTokenError

from ..config import settings
from .service import utc_now

ISSUER = "dressme"
AUDIENCE = "dressme-browser"


def create_access(user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    now = utc_now()
    return jwt.encode({
        "sub": str(user_id), "sid": str(session_id), "purpose": "access",
        "iss": ISSUER, "aud": AUDIENCE, "iat": now,
        "exp": now + timedelta(seconds=settings.access_ttl_seconds),
    }, settings.jwt_secret, algorithm="HS256")


def verify_access(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"],
                            issuer=ISSUER, audience=AUDIENCE,
                            options={"require": ["sub", "sid", "purpose", "iss", "aud", "iat", "exp"]})
        if claims["purpose"] != "access":
            return None
        return uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
    except (InvalidTokenError, ValueError, KeyError, TypeError):
        return None
