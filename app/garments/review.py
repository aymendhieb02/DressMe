"""Application review semantics; the frozen BO6 bundle remains unchanged.

Head eligibility governs AI suggestions, not all valid manual fields: dress
and sweater sleeves may be confirmed manually despite no trained sleeve head.
Bottom garments have no sleeves, so remove stale sleeve confirmation there.
"""
BOTTOM_CATEGORIES = frozenset({"jeans", "shorts", "skirt", "trousers"})


def normalize_review(fields: dict) -> dict:
    clean = dict(fields)
    if clean.get("category") in BOTTOM_CATEGORIES:
        clean.pop("sleeve_length", None)
    return clean
