from dataclasses import dataclass


POLICY_VERSION = "bo6-fashn-candidate-v1"

# These are semantic candidates from the inspected project contract, not visually
# validated product compatibility. No category is enabled until that review exists.
_CANDIDATES = {
    "dress": "one-pieces",
    "jeans": "bottoms",
    "shorts": "bottoms",
    "skirt": "bottoms",
    "trousers": "bottoms",
    "shirt": "tops",
    "sweater": "tops",
    "sweatshirt": "tops",
    "t-shirt": "tops",
    "top": "tops",
}


@dataclass(frozen=True)
class Eligibility:
    status: str
    eligible: bool
    candidate_category: str | None
    reason: str | None
    policy_version: str


def evaluate_vton_eligibility(category: str, garment_photo_type: str) -> dict:
    candidate = _CANDIDATES.get(category)
    if garment_photo_type not in {"flat-lay", "model"}:
        return Eligibility("blocked", False, candidate, "unsupported_photo_type", POLICY_VERSION).__dict__
    if candidate is None:
        return Eligibility("blocked", False, None, "unsupported_category", POLICY_VERSION).__dict__
    return Eligibility(
        "disabled", False, candidate, "mapping_not_visually_validated", POLICY_VERSION
    ).__dict__
