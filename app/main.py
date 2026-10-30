import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth.router import router as auth_router
from .avatars.router import router as avatars_router
from .common.errors import http_error_handler, unhandled_error_handler, validation_error_handler
from .common.middleware import RequestContextMiddleware
from .config import settings
from .database import engine
from .garments.router import router as garments_router
from .ml.client import BO6Client, BO6ServiceError
from .models import AvatarRender, Garment, PendingUpload, RefreshSession, StorageDeletion, User  # register metadata for Alembic
from .storage.local_disk import LocalPrivateStorage
from .storage.cleanup import drain_storage_deletions, expire_pending_uploads
from .tryon.router import router as tryon_router
from .tryon.runtime import tryon_runtime_status
from fastapi.exceptions import RequestValidationError
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from .auth.dependencies import AuthenticationRequired, InvalidCsrfToken
from .common.errors import error_response


async def cleanup_pass():
    await asyncio.to_thread(expire_pending_uploads)
    await asyncio.to_thread(drain_storage_deletions)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Migrations are explicit; the backend never loads the BO6 model or GPU runtime.
    LocalPrivateStorage()
    async def cleanup_loop():
        while True:
            await asyncio.sleep(30)
            try:
                await asyncio.to_thread(expire_pending_uploads)
                await asyncio.to_thread(drain_storage_deletions)
            except Exception:
                # The durable cleanup intents remain queued for the next pass.
                continue

    task = asyncio.create_task(cleanup_loop(), name="dressme-storage-cleanup")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="DressMe Application API", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.frontend_origins), allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token", "X-CSRF-Bootstrap", "X-Request-ID"])
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


async def authentication_error_handler(request: Request, _exc: Exception):
    return error_response(request, 401, "authentication_required", "A valid session is required.")


async def csrf_error_handler(request: Request, _exc: Exception):
    return error_response(request, 403, "csrf_failed", "The request origin or CSRF token is invalid.")


app.add_exception_handler(AuthenticationRequired, authentication_error_handler)
app.add_exception_handler(InvalidCsrfToken, csrf_error_handler)
app.include_router(auth_router)
app.include_router(avatars_router)
app.include_router(garments_router)
app.include_router(tryon_router)


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/try-on")
def try_on_runtime():
    return tryon_runtime_status()


@app.get("/health/ready")
async def ready():
    database_ok = False
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        pass
    try:
        ml = await BO6Client().health()
        ml_ok = ml.status == "ok"
        ml_version = ml.model_version if ml_ok else None
    except BO6ServiceError:
        ml_ok, ml_version = False, None
    status = "ok" if database_ok and ml_ok else "not_ready"
    return JSONResponse(status_code=200 if status == "ok" else 503,
                        content={"status": status, "dependencies": {"database": database_ok, "bo6_service": ml_ok},
                                 "model_version": ml_version,
                                 "inference_mode": "bo6_real" if ml_ok else "unavailable",
                                 "vton_mode": settings.vton_mode,
                                 "real_vton_ready": False})
