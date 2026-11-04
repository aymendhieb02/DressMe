from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parents[1]
BUNDLE_DIR = Path(os.getenv("MODEL_BUNDLE_DIR", BASE_DIR / "bundle")).resolve()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
