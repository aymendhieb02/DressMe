import importlib.util
import json
import sys
import threading
from pathlib import Path

from .checksum import verify_bundle


class ModelRuntime:
    def __init__(self, bundle: Path):
        self.bundle = bundle
        verify_bundle(bundle)
        # The bundle self-test runs at Docker build time. Keep startup to one model load.
        sys.path.insert(0, str(bundle))
        from attributes import GarmentDescriber
        from quality_checks import check_image

        self.describer = GarmentDescriber(bundle=str(bundle), device="cpu")
        self.check_image = check_image
        self.predict_lock = threading.Lock()
        self.description_module = self.describer.clf.description
        self.model_version = self.describer.clf.arch["experiment_id"]
        self.taxonomy_version = self.describer.clf.taxonomy["version"]
        self.description_version = self.description_module.SCHEMA["version"]
        quality_config = json.loads((bundle / "quality_config.json").read_text(encoding="utf-8"))
        self.quality_version = quality_config["version"]

    def predict(self, image_path: str):
        with self.predict_lock:
            return self.describer.predict(image_path)

    def describe(self, confirmed: dict):
        # Delegate rendering, normalization, and semantics to the bundle template.
        category = confirmed.get("category", "unknown")
        return self.description_module.describe(
            category,
            "user_confirmed" if "category" in confirmed else "not_estimated",
            confirmed={k: v for k, v in confirmed.items() if k != "category"},
        )
