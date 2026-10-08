import asyncio
import io
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from PIL import Image, UnidentifiedImageError

from .config import ALLOWED_FORMATS, BUNDLE_DIR, CONTENT_TYPES, MAX_UPLOAD_BYTES
from .errors import ServiceError, service_error_handler, validation_error_handler
from .model_runtime import ModelRuntime
from .schemas import DescribeRequest


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.runtime = ModelRuntime(BUNDLE_DIR)
    yield


app = FastAPI(title="DressMe BO6 ML Service", version="1.0.0", lifespan=lifespan)
app.add_exception_handler(ServiceError, service_error_handler)
app.add_exception_handler(422, validation_error_handler)


@app.get("/health")
async def health():
    runtime: ModelRuntime = app.state.runtime
    return {
        "status": "ok",
        "model_version": runtime.model_version,
        "taxonomy_version": runtime.taxonomy_version,
        "description_version": runtime.description_version,
        "quality_version": runtime.quality_version,
    }


async def _read_image(upload: UploadFile) -> tuple[bytes, str]:
    if upload.content_type not in CONTENT_TYPES:
        raise ServiceError(415, "unsupported_media_type", "Upload a JPEG, PNG, or WEBP image.")
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ServiceError(413, "file_too_large", "Image exceeds the 10 MB upload limit.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format
            image.verify()
        if image_format not in ALLOWED_FORMATS:
            raise ServiceError(415, "unsupported_media_type", "Upload a JPEG, PNG, or WEBP image.")
        return data, {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image_format]
    except ServiceError:
        raise
    except (OSError, SyntaxError, ValueError, UnidentifiedImageError):
        raise ServiceError(422, "unreadable_image", "The uploaded file is not a readable image.") from None


@app.post("/analyze")
async def analyze(image: UploadFile = File(...)):
    data, suffix = await _read_image(image)
    runtime: ModelRuntime = app.state.runtime
    with tempfile.TemporaryDirectory() as directory:
        image_path = Path(directory) / ("upload" + suffix)
        image_path.write_bytes(data)
        # Bundle inference and quality analysis use synchronous CPU work.
        quality = await asyncio.to_thread(runtime.check_image, str(image_path))
        try:
            prediction = await asyncio.to_thread(runtime.predict, str(image_path))
        except ValueError as exc:
            if str(exc).startswith("unreadable image:"):
                raise ServiceError(422, "unreadable_image", str(exc)) from None
            raise
    return {"quality": quality, "prediction": prediction}


@app.post("/describe")
async def describe(body: DescribeRequest):
    runtime: ModelRuntime = app.state.runtime
    confirmed = body.confirmed.model_dump(exclude_none=True)
    try:
        return runtime.describe(confirmed)
    except ValueError as exc:
        raise ServiceError(422, "invalid_confirmed_fields", str(exc)) from None
