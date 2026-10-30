import hashlib
import io
import warnings

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import get_settings

FORMATS = {"JPEG", "PNG", "WEBP"}


def normalize_image(data: bytes) -> tuple[bytes, int, int, str]:
    settings = get_settings()
    if not data:
        raise HTTPException(status_code=422, detail={"code": "empty_image", "message": "Upload a readable JPEG, PNG, or WEBP image."})
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail={"code": "file_too_large", "message": "Image exceeds the 10 MB upload limit."})
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as check:
                fmt = check.format
                if fmt not in FORMATS:
                    raise HTTPException(status_code=415, detail={"code": "unsupported_media_type", "message": "Upload a JPEG, PNG, or WEBP image."})
                if getattr(check, "n_frames", 1) != 1:
                    raise HTTPException(status_code=415, detail={"code": "animated_image", "message": "Animated images are not supported."})
                if check.width * check.height > settings.max_image_pixels:
                    raise HTTPException(status_code=413, detail={"code": "image_dimensions_exceeded", "message": "Image dimensions exceed the supported limit."})
                check.verify()
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                width, height = image.size
                buffer = io.BytesIO()
                image.save(buffer, format="PNG", optimize=True)
                normalized = buffer.getvalue()
        if len(normalized) > settings.max_upload_bytes * 2:
            raise HTTPException(status_code=413, detail={"code": "normalized_image_too_large", "message": "Decoded image exceeds the private storage limit."})
        return normalized, width, height, hashlib.sha256(normalized).hexdigest()
    except HTTPException:
        raise
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, UnidentifiedImageError):
        raise HTTPException(status_code=422, detail={"code": "unreadable_image", "message": "The uploaded file is not a readable image."}) from None
