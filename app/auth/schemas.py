from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal


class _EmailModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        local, separator, domain = value.partition("@")
        if not separator or not local or "." not in domain or any(ch.isspace() for ch in value):
            raise ValueError("Enter a valid email address.")
        return value


class RegisterCredentials(_EmailModel):
    password: str = Field(min_length=12, max_length=128)


class LoginCredentials(_EmailModel):
    # Existing accounts keep working even if their historical password is shorter.
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(_EmailModel):
    pass


class PasswordResetComplete(_EmailModel):
    code: str = Field(pattern=r"^[0-9]{8}$")
    new_password: str = Field(min_length=12, max_length=128)


class UserPublic(BaseModel):
    id: UUID
    email: str
    role: str
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserPublic
    csrf_token: str


class CsrfToken(BaseModel):
    csrf_token: str


class AccountDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=12, max_length=128)
    confirmation: Literal["DELETE"]
