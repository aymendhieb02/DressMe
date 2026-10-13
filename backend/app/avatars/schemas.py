from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AvatarConsentRequest(BaseModel):
    accepted: bool


class AvatarConsentView(BaseModel):
    id: UUID
    provider: str
    consent_version: str
    consented_at: datetime


class AvatarView(BaseModel):
    id: UUID
    provider: str
    provider_avatar_id: str
    model_url: str
    asset_sha256: str
    asset_size: int
    version: int
    consent_version: str
    created_at: datetime
    updated_at: datetime
