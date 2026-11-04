from typing import Literal
from pydantic import BaseModel, ConfigDict

Category = Literal["dress", "jacket", "jeans", "shirt", "shorts", "skirt", "sweater", "sweatshirt", "t-shirt", "top", "trousers"]
Color = Literal["beige", "black", "blue", "brown", "green", "grey", "navy", "orange", "pink", "purple", "red", "white", "yellow", "unknown"]
Pattern = Literal["solid", "striped", "checked", "printed", "floral", "not_visible", "unknown"]
SleeveLength = Literal["sleeveless", "short", "long", "not_visible", "unknown"]


class ConfirmedFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category | None = None
    color: Color | None = None
    pattern: Pattern | None = None
    sleeve_length: SleeveLength | None = None


class DescribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: ConfirmedFields
