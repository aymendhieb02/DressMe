from typing import Literal
from pydantic import BaseModel, ConfigDict

Category = Literal["dress", "jacket", "jeans", "shirt", "shorts", "skirt", "sweater", "sweatshirt", "t-shirt", "top", "trousers",
                   "blouse", "cardigan", "vest", "pants", "jumpsuit", "coat", "shoes", "bag", "accessory"]
Color = Literal["beige", "black", "blue", "brown", "green", "grey", "navy", "orange", "pink", "purple", "red", "white", "yellow",
                "unknown", "gold", "silver", "multi"]
Pattern = Literal["solid", "striped", "checked", "printed", "floral", "not_visible", "unknown"]
SleeveLength = Literal["sleeveless", "short", "long", "three_quarter", "not_visible", "unknown"]
Material = Literal["cashmere", "cotton", "denim", "leather", "linen", "silk", "suede", "synthetic", "wool"]
Season = Literal["all", "winter", "summer"]


class ConfirmedFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category | None = None
    color: Color | None = None
    pattern: Pattern | None = None
    sleeve_length: SleeveLength | None = None
    material: Material | None = None
    season: Season | None = None


class DescribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: ConfirmedFields
