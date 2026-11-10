from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .workflow import MAX_SEQUENCE_GARMENTS


class PersonPhotoView(BaseModel):
    id: UUID
    image_url: str
    width: int
    height: int
    consent_version: str
    consented_at: datetime
    from_avatar: bool
    created_at: datetime


class AvatarPhotoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: bool


class TryOnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    garment_id: UUID
    person_photo_id: UUID


class TryOnSequenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    garment_ids: list[UUID] = Field(min_length=2, max_length=MAX_SEQUENCE_GARMENTS)
    person_photo_id: UUID


class TryOnOotdSequenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_ids: list[int] = Field(min_length=2, max_length=MAX_SEQUENCE_GARMENTS)
    person_photo_id: UUID


class TryOnGarmentView(BaseModel):
    id: str
    image_url: str
    category: str | None = None
    name: str | None = None


class TryOnJobView(BaseModel):
    id: UUID
    state: str
    mode: str
    status_url: str
    result_url: str | None = None
    person_image_url: str
    person_image_label: str = "Person"
    garment_image_url: str | None = None
    garments: list[TryOnGarmentView] = Field(default_factory=list)
    workflow: str = "single"
    garment_category: str | None = None
    queue_position: int | None = None
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
