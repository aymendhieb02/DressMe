"""Category facts for the team wardrobe. The confirmed category decides these, never the prediction."""
import uuid

SUPER_AND_OUTFIT_CATEGORY = {
    "t-shirt": ("top", "top"),
    "shirt": ("top", "top"),
    "blouse": ("top", "top"),
    "top": ("top", "top"),
    "sweater": ("top", "top"),
    "cardigan": ("top", "top"),
    "sweatshirt": ("top", "top"),
    "vest": ("top", "outer"),
    "pants": ("bottom", "bottom"),
    "trousers": ("bottom", "bottom"),  # legacy label for pants
    "jeans": ("bottom", "bottom"),
    "shorts": ("bottom", "bottom"),
    "skirt": ("bottom", "bottom"),
    "dress": ("dress", "dress"),
    "jumpsuit": ("dress", "dress"),
    "jacket": ("outerwear", "outer"),
    "coat": ("outerwear", "outer"),
    "shoes": ("shoes", "shoes"),
    "bag": ("bag", "bag"),
    "accessory": ("accessory", "other"),
}


def wardrobe_fields(category: str) -> dict:
    super_category, outfit_cat = SUPER_AND_OUTFIT_CATEGORY[category]
    return {"super_category": super_category, "outfit_cat": outfit_cat}


def new_item_code() -> str:
    """Stands in for a catalog code. Catalog codes all start with P, so these cannot collide."""
    return "w_" + uuid.uuid4().hex
