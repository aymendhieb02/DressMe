from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PersonPhotoView(BaseModel):
    id: UUID
    image_url: str
    width: int
    height: int
    consent_version: str
    consented_at: datetime
    created_at: datetime


class TryOnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    garment_id: UUID
    person_photo_id: UUID


class TryOnJobView(BaseModel):
    id: UUID
    state: str
    mode: str
    status_url: str
    result_url: str | None = None
    error_code: str | None = None
    cancellation_requested: bool = False
    settings_snapshot: dict
    result_metadata: dict | None = None
    created_at: datetime
    updated_at: datetime
    replayed: bool = False


class TryOnJobList(BaseModel):
    items: list[TryOnJobView]


class ConsentForm(BaseModel):
    consent: bool = Field(...)
