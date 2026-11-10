"""Runtime for the Garments2Look bundle (bundle_g2l/).

Serves the bundle behind the same /analyze and /describe contract as the legacy
runtime, so the application and Studio UI keep one prediction shape. The bundle's
CLIP embedding is never requested or returned: it is not in the team's vector space.
"""
import json
import sys
import threading
from pathlib import Path

from .checksum import verify_bundle

TO_STUDIO = {"pattern": {"plain": "solid"}, "sleeve_length": {"none": "sleeveless"}}
TO_BUNDLE = {field: {studio: bundle for bundle, studio in values.items()} for field, values in TO_STUDIO.items()}
HEAD_TO_FIELD = {"color": "color", "pattern": "pattern", "material": "material", "sleeve": "sleeve_length"}
UNSET = {None, "unknown", "not_visible"}
FORWARDED_KEYS = (
    "category", "score", "score_type", "suggestions", "category_confident", "needs_user_review",
    "super_category", "outfit_cat", "description", "desc", "model_version", "taxonomy_version",
    "description_version",
)


def is_g2l_bundle(bundle: Path) -> bool:
    return (bundle / "dressme_core.py").is_file()


def to_studio(field: str, value):
    """Bundle value -> Studio value. Withheld values stay explicit as "unknown"."""
    if value is None:
        return "unknown"
    return TO_STUDIO.get(field, {}).get(value, value)


def to_bundle(field: str, value):
    """Studio value -> bundle value. Unset values become None so templates leave them out."""
    if value in UNSET:
        return None
    return TO_BUNDLE.get(field, {}).get(value, value)


def _attribute(field: str, score: dict | None, value: str, source: str) -> dict:
    if score is None:
        return {"eligible": False, "reason": source, "threshold": None, "score_type": "softmax",
                "suggestions": [], "value": value, "source": source, "stated_in_description": False}
    return {
        "eligible": True, "reason": None, "threshold": score["threshold"], "score_type": "softmax",
        "suggestions": [{"value": to_studio(field, item["value"]), "score": item["score"]}
                        for item in score["suggestions"]],
        "value": value, "source": source, "stated_in_description": value != "unknown",
    }


def normalize_prediction(raw: dict) -> dict:
    """Bundle predict() output -> the Studio prediction shape. Allow-listed, so no embedding can pass."""
    fields = raw["description_fields"]
    provenance = dict(raw["description_provenance"])
    normalized_fields = {field: to_studio(field, value) for field, value in fields.items()}
    scores = raw.get("attribute_scores", {})
    attributes = {
        field: _attribute(field, scores.get(head), normalized_fields.get(field, "unknown"),
                          provenance.get(field, "not_available"))
        for head, field in HEAD_TO_FIELD.items()
    }
    prediction = {key: raw[key] for key in FORWARDED_KEYS}
    prediction.update(
        description_fields=normalized_fields,
        description_provenance=provenance,
        attributes=attributes,
        color_suggestions=attributes["color"]["suggestions"],
    )
    return prediction


class G2LRuntime:
    def __init__(self, bundle: Path):
        self.bundle = bundle
        verify_bundle(bundle)
        sys.path.insert(0, str(bundle))
        import dressme_core
        from quality_checks import check_image

        self.core = dressme_core
        self.describer = dressme_core.GarmentDescriber(bundle, device="cpu")
        self.check_image = check_image
        self.predict_lock = threading.Lock()
        config = self.describer.cfg
        self.model_version = config["model_version"]
        self.taxonomy_version = config["taxonomy_version"]
        self.description_version = dressme_core.DESCRIPTION_VERSION
        quality_config = json.loads((bundle / "quality_config.json").read_text(encoding="utf-8"))
        self.quality_version = quality_config["version"]

    def predict(self, image_path: str) -> dict:
        with self.predict_lock:
            try:
                raw = self.describer.predict(image_path, return_embedding=False)
            except OSError as exc:
                raise ValueError("unreadable image: the file could not be decoded") from exc
        return normalize_prediction(raw)

    def accepts(self, confirmed: dict) -> bool:
        return True

    def describe(self, confirmed: dict) -> dict:
        fields = {key: to_bundle(key, value) for key, value in confirmed.items()}
        category = fields.get("category")
        season = fields.get("season") or self.core.season_rule(
            category, fields.get("material"), fields.get("sleeve_length"))
        sentence, desc = self.core.render_description(fields)
        names = ("category", "color", "pattern", "sleeve_length", "material")
        result_fields = {name: to_studio(name, fields.get(name)) for name in names}
        result_fields["season"] = season
        provenance = {name: "user_confirmed" if fields.get(name) else "not_estimated" for name in names}
        provenance["season"] = "user_confirmed" if fields.get("season") else "rule"
        return {"text": sentence, "desc": desc, "fields": result_fields, "provenance": provenance,
                "schema_version": self.description_version}
