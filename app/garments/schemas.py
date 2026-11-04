from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["dress", "jacket", "jeans", "shirt", "shorts", "skirt", "sweater", "sweatshirt", "t-shirt", "top", "trousers"]
Color = Literal["beige", "black", "blue", "brown", "green", "grey", "navy", "orange", "pink", "purple", "red", "white", "yellow"]
Pattern = Literal["solid", "striped", "checked", "printed", "floral"]
SleeveLength = Literal["sleeveless", "short", "long"]


class ReviewFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    color: Color | None = None
    pattern: Pattern | None = None
    sleeve_length: SleeveLength | None = None


class DescribeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pending_upload_id: UUID
    confirmed: ReviewFields


class SaveGarmentInput(ReviewFields):
    pending_upload_id: UUID
    garment_photo_type: Literal["flat-lay", "model"]
    description: str | None = Field(default=None, max_length=500)
    name: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class GarmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category | None = None
    garment_photo_type: Literal["flat-lay", "model"] | None = None
    color: Color | None = None
    pattern: Pattern | None = None
    sleeve_length: SleeveLength | None = None
    description: str | None = Field(default=None, max_length=500)
    name: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class PendingUploadView(BaseModel):
    id: UUID
    image_url: str
    image_sha256: str
    width: int
    height: int
    quality: dict
    prediction: dict
    expires_at: str


class GarmentView(BaseModel):
    id: UUID
    category: str
    garment_photo_type: str
    vton_eligibility: dict
    vton_eligibility_version: str
    color: str | None
    pattern: str | None
    sleeve_length: str | None
    description: str
    description_is_manual: bool
    name: str | None
    notes: str | None
    image_url: str
    prediction_snapshot: dict
    quality_snapshot: dict
    field_sources: dict
    was_corrected: dict
    model_version: str
    taxonomy_version: str
    description_version: str
    description_provenance: dict
    created_at: str
    updated_at: str


class GarmentList(BaseModel):
    items: list[GarmentView]
    page: int
    page_size: int
    total: int
