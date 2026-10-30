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


class AvatarRenderView(BaseModel):
    id: UUID
    avatar_id: UUID
    source_avatar_version: int
    source_avatar_sha256: str
    profile_id: str
    profile_version: int
    render_settings: dict
    image_url: str
    image_sha256: str
    width: int
    height: int
    renderer_version: str
    created_at: datetime
