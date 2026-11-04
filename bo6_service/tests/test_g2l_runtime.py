import importlib.util
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.g2l_runtime import G2LRuntime, is_g2l_bundle, normalize_prediction, to_bundle, to_studio

BUNDLE = Path(__file__).resolve().parents[1] / "bundle_g2l"
needs_bundle = pytest.mark.skipif(
    not BUNDLE.is_dir() or importlib.util.find_spec("transformers") is None,
    reason="needs bundle_g2l and the .venv-bo6-g2l environment",
)


def _raw(**overrides):
    raw = {
        "category": "shirt", "score": 0.91, "score_type": "softmax",
        "suggestions": [{"category": "shirt", "score": 0.91}],
        "category_confident": True, "needs_user_review": True,
        "super_category": "top", "outfit_cat": "top",
        "description": "A white cotton shirt.", "desc": "white cotton shirt",
        "description_fields": {"category": "shirt", "color": "white", "pattern": "plain",
                               "material": None, "sleeve_length": "none", "season": "all"},
        "description_provenance": {"category": "classifier", "color": "image_model", "pattern": "image_model",
                                   "material": "withheld_low_confidence", "sleeve_length": "image_model",
                                   "season": "rule"},
        "attribute_scores": {
            "color": {"value": "white", "score": 0.9, "accepted": True, "threshold": 0.63,
                      "suggestions": [{"value": "white", "score": 0.9}]},
            "pattern": {"value": "plain", "score": 0.8, "accepted": True, "threshold": 0.56,
                        "suggestions": [{"value": "plain", "score": 0.8}]},
        },
        "model_version": "g2l-test", "taxonomy_version": "dressme-g2l-v1.0",
        "description_version": "tmpl-g2l-v1.0",
        "embedding_model": "secret-space", "embedding_dim": 512, "embedding": [0.1, 0.2],
    }
    raw.update(overrides)
    return raw


def _assert_no_embedding(value):
    """No embedding key at any depth, and no vector-sized list of numbers under any name."""
    if isinstance(value, dict):
        assert not [key for key in value if "embedding" in key]
        for item in value.values():
            _assert_no_embedding(item)
    elif isinstance(value, list):
        assert not (len(value) > 16 and all(isinstance(item, float) for item in value))
        for item in value:
            _assert_no_embedding(item)


def test_normalize_maps_values_to_studio_vocabulary():
    prediction = normalize_prediction(_raw())
    fields = prediction["description_fields"]
    assert fields["pattern"] == "solid"
    assert fields["sleeve_length"] == "sleeveless"
    assert fields["material"] == "unknown"
    assert prediction["attributes"]["pattern"]["suggestions"][0]["value"] == "solid"


def test_normalize_never_forwards_embedding_data():
    prediction = normalize_prediction(_raw())
    _assert_no_embedding(prediction)
    assert "secret-space" not in json.dumps(prediction)


def test_normalize_reports_attributes_without_a_score_as_ineligible():
    attributes = normalize_prediction(_raw())["attributes"]
    assert set(attributes) == {"color", "pattern", "material", "sleeve_length"}
    assert attributes["material"]["eligible"] is False and attributes["material"]["suggestions"] == []
    assert attributes["color"]["eligible"] is True and attributes["color"]["stated_in_description"] is True


def test_value_mapping_round_trips_and_unset_values_become_none():
    assert to_bundle("pattern", to_studio("pattern", "plain")) == "plain"
    assert to_bundle("sleeve_length", to_studio("sleeve_length", "none")) == "none"
    assert to_studio("color", None) == "unknown"
    assert to_bundle("color", "unknown") is None and to_bundle("pattern", "not_visible") is None


def test_bundle_kind_is_detected_from_the_folder(tmp_path):
    assert not is_g2l_bundle(tmp_path)
    (tmp_path / "dressme_core.py").write_text("", encoding="utf-8")
    assert is_g2l_bundle(tmp_path)


@pytest.fixture(scope="module")
def runtime():
    return G2LRuntime(BUNDLE)


@needs_bundle
def test_runtime_predicts_in_studio_shape_without_embedding(runtime, tmp_path):
    path = tmp_path / "garment.jpg"
    Image.new("RGB", (256, 256), (30, 100, 180)).save(path, "JPEG")
    prediction = runtime.predict(str(path))
    assert prediction["model_version"].startswith("g2l-clip-lr-")
    assert prediction["needs_user_review"] is True and len(prediction["suggestions"]) == 3
    _assert_no_embedding(prediction)


@needs_bundle
def test_runtime_reports_undecodable_files_as_unreadable(runtime, tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="^unreadable image:"):
        runtime.predict(str(path))


@needs_bundle
def test_runtime_describes_confirmed_fields_in_studio_vocabulary(runtime):
    body = runtime.describe({"category": "shirt", "color": "blue", "pattern": "solid",
                             "material": "cotton", "sleeve_length": "sleeveless"})
    assert body["text"] == "A blue cotton shirt."
    assert body["fields"]["pattern"] == "solid" and body["fields"]["sleeve_length"] == "sleeveless"
    assert body["provenance"]["color"] == "user_confirmed" and body["provenance"]["season"] == "rule"
    assert body["schema_version"] == runtime.description_version


@needs_bundle
def test_runtime_describes_unconfirmed_fields_as_not_estimated(runtime):
    body = runtime.describe({"category": "jeans"})
    assert body["text"] == "Jeans."
    assert body["fields"]["color"] == "unknown" and body["provenance"]["color"] == "not_estimated"
