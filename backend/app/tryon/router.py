import asyncio
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.dependencies import current_user, current_user_csrf
from ..config import get_settings
from ..database import get_db
from ..models import (
    Garment,
    PendingUpload,
    PersonPhoto,
    StorageDeletion,
    TryOnJob,
    TryOnJobOutbox,
    User,
    utcnow,
)
from ..storage.cleanup import acknowledge_storage_deletion, record_storage_deletion_failure
from ..storage.local_disk import LocalPrivateStorage
from ..uploads import normalize_image
from .deletion import delete_jobs
from .schemas import PersonPhotoView, TryOnCreate, TryOnJobList, TryOnJobView

router = APIRouter(tags=["try-on"])
CONSENT_VERSION = "person-photo-use-v1"


def _http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _photo_view(row: PersonPhoto) -> PersonPhotoView:
    return PersonPhotoView(
        id=row.id,
        image_url=f"/person-photos/{row.id}/image",
        width=row.width,
        height=row.height,
        consent_version=row.consent_version,
        consented_at=row.consented_at,
        created_at=row.created_at,
    )


def _job_view(row: TryOnJob, replayed: bool = False) -> TryOnJobView:
    return TryOnJobView(
        id=row.id,
        state=row.state,
        mode=row.mode,
        status_url=f"/try-on/jobs/{row.id}",
        result_url=f"/try-on/jobs/{row.id}/result" if row.state == "succeeded" and row.result_key else None,
        error_code=row.error_code,
        cancellation_requested=row.cancellation_requested_at is not None,
        settings_snapshot=row.settings_snapshot,
        result_metadata=row.result_metadata,
        created_at=row.created_at,
        updated_at=row.updated_at,
        replayed=replayed,
    )


async def _delete_private_keys(db: Session, keys: list[str]) -> bool:
    storage = LocalPrivateStorage()
    cleanup_pending = False
    for key in keys:
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            record_storage_deletion_failure(db, key)
            cleanup_pending = True
            continue
        acknowledge_storage_deletion(db, key)
    return cleanup_pending


def _deletion_response(cleanup_pending: bool) -> Response:
    if cleanup_pending:
        return JSONResponse(status_code=202, content={"status": "deletion_queued", "message": "Access was revoked; private file cleanup is queued for retry."})
    return Response(status_code=204)


@router.post("/person-photos", response_model=PersonPhotoView, status_code=201)
async def upload_person_photo(
    image: UploadFile = File(...),
    consent: bool = Form(...),
    user: User = Depends(current_user_csrf),
    db: Session = Depends(get_db),
):
    if consent is not True:
        raise _http_error(422, "photo_consent_required", "Confirm the photo-use consent before uploading.")
    owner = db.scalar(select(User).where(User.id == user.id).with_for_update())
    count = db.scalar(select(func.count()).select_from(PersonPhoto).where(PersonPhoto.user_id == user.id)) or 0
    if count >= get_settings().max_person_photos:
        raise _http_error(429, "person_photo_limit", "Delete a saved person photo before adding another.")
    if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise _http_error(415, "unsupported_media_type", "Upload a JPEG, PNG, or WEBP image.")
    data, width, height, digest = normalize_image(await image.read(get_settings().max_upload_bytes + 1))
    storage = LocalPrivateStorage()
    image_key = await asyncio.to_thread(storage.put, data)
    try:
        row = PersonPhoto(
            user_id=owner.id,
            image_key=image_key,
            image_sha256=digest,
            width=width,
            height=height,
            consent_version=CONSENT_VERSION,
            consented_at=utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _photo_view(row)
    except Exception:
        db.rollback()
        try:
            await asyncio.to_thread(storage.delete, image_key)
        except Exception:
            pass
        raise


@router.get("/person-photos", response_model=list[PersonPhotoView])
def list_person_photos(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PersonPhoto).where(PersonPhoto.user_id == user.id).order_by(PersonPhoto.created_at.desc()).limit(50)
    ).all()
    return [_photo_view(row) for row in rows]


@router.get("/person-photos/{photo_id}/image")
def person_photo_image(photo_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(PersonPhoto).where(PersonPhoto.id == photo_id, PersonPhoto.user_id == user.id))
    if row is None:
        raise _http_error(404, "person_photo_not_found", "Person photo not found.")
    content = LocalPrivateStorage().read(row.image_key)
    return Response(content, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/person-photos/{photo_id}", status_code=204)
async def delete_person_photo(photo_id: UUID, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    row = db.scalar(select(PersonPhoto).where(PersonPhoto.id == photo_id, PersonPhoto.user_id == user.id))
    if row is None:
        raise _http_error(404, "person_photo_not_found", "Person photo not found.")
    jobs = db.scalars(select(TryOnJob).where(TryOnJob.person_photo_id == row.id, TryOnJob.user_id == user.id)).all()
    keys = [row.image_key]
    for job in jobs:
        if job.result_key:
            keys.append(job.result_key)
            db.add(StorageDeletion(image_key=job.result_key))
    delete_jobs(db, jobs)
    db.add(StorageDeletion(image_key=row.image_key))
    db.delete(row)
    db.commit()
    cleanup_pending = await _delete_private_keys(db, keys)
    return _deletion_response(cleanup_pending)


@router.post("/try-on/jobs", response_model=TryOnJobView, status_code=202)
def create_tryon_job(
    body: TryOnCreate,
    user: User = Depends(current_user_csrf),
    db: Session = Depends(get_db),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
):
    settings = get_settings()
    if settings.vton_mode == "real":
        raise _http_error(503, "real_vton_unavailable", "Real try-on is not enabled on this runtime; no mock result was substituted.")
    if settings.vton_mode != "mock":
        raise _http_error(503, "vton_mode_unavailable", "Try-on mode is not available.")

    key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    fingerprint_body = {"garment_id": str(body.garment_id), "person_photo_id": str(body.person_photo_id), "mode": "mock"}
    fingerprint = hashlib.sha256(json.dumps(fingerprint_body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    existing = db.scalar(select(TryOnJob).where(TryOnJob.user_id == user.id, TryOnJob.idempotency_key_hash == key_hash))
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise _http_error(409, "idempotency_conflict", "This idempotency key was already used for a different request.")
        return _job_view(existing, replayed=True)

    owner = db.scalar(select(User).where(User.id == user.id).with_for_update())
    garment = db.scalar(select(Garment).where(Garment.id == body.garment_id, Garment.user_id == owner.id))
    if garment is None:
        raise _http_error(404, "garment_not_found", "Garment not found.")
    photo = db.scalar(select(PersonPhoto).where(PersonPhoto.id == body.person_photo_id, PersonPhoto.user_id == owner.id))
    if photo is None:
        raise _http_error(404, "person_photo_not_found", "Person photo not found.")
    if photo.consent_version != CONSENT_VERSION:
        raise _http_error(422, "photo_consent_invalid", "A current photo-use consent is required.")
    if not garment.vton_eligibility.get("candidate_category"):
        raise _http_error(422, "unsupported_garment", "This garment has no supported try-on category mapping.")

    outstanding = db.scalar(
        select(func.count()).select_from(TryOnJob).where(
            TryOnJob.user_id == owner.id, TryOnJob.state.in_(["queued", "running"])
        )
    ) or 0
    if outstanding >= settings.max_outstanding_jobs:
        raise _http_error(429, "user_job_limit", "Wait for or cancel an existing try-on before submitting another.")
    global_outstanding = db.scalar(
        select(func.count()).select_from(TryOnJob).where(TryOnJob.state.in_(["queued", "running"]))
    ) or 0
    if global_outstanding >= settings.max_queued_jobs:
        raise _http_error(429, "queue_full", "The try-on queue is full. Please try again later.")

    job = TryOnJob(
        user_id=owner.id,
        garment_id=garment.id,
        person_photo_id=photo.id,
        idempotency_key_hash=key_hash,
        request_fingerprint=fingerprint,
        mode="mock",
        state="queued",
        settings_snapshot={"mode": "mock", "adapter": "mock-preview-v1"},
        input_snapshot={
            "garment_revision": garment.updated_at.isoformat(),
            "garment_category": garment.category,
            "garment_photo_type": garment.garment_photo_type,
            "candidate_vton_category": garment.vton_eligibility["candidate_category"],
            "garment_image_key": garment.image_key,
            "garment_image_sha256": db.scalar(select(PendingUpload.image_sha256).where(PendingUpload.id == garment.pending_upload_id)),
            "person_photo_image_key": photo.image_key,
            "person_photo_sha256": photo.image_sha256,
            "consent_version": photo.consent_version,
        },
    )
    db.add(job)
    try:
        db.flush()
        db.add(TryOnJobOutbox(job_id=job.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(TryOnJob).where(TryOnJob.user_id == user.id, TryOnJob.idempotency_key_hash == key_hash))
        if existing is not None and existing.request_fingerprint == fingerprint:
            return _job_view(existing, replayed=True)
        if existing is not None:
            raise _http_error(409, "idempotency_conflict", "This idempotency key was already used for a different request.") from None
        raise _http_error(409, "job_conflict", "The job could not be created safely; retry with a new idempotency key.") from None
    db.refresh(job)
    return _job_view(job)


@router.get("/try-on/jobs", response_model=TryOnJobList)
def list_tryon_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(TryOnJob).where(TryOnJob.user_id == user.id).order_by(TryOnJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return TryOnJobList(items=[_job_view(row) for row in rows])


@router.get("/try-on/jobs/{job_id}", response_model=TryOnJobView)
def get_tryon_job(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(TryOnJob).where(TryOnJob.id == job_id, TryOnJob.user_id == user.id))
    if row is None:
        raise _http_error(404, "job_not_found", "Try-on job not found.")
    return _job_view(row)


@router.get("/try-on/jobs/{job_id}/result")
def get_tryon_result(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(TryOnJob).where(TryOnJob.id == job_id, TryOnJob.user_id == user.id))
    if row is None or row.state != "succeeded" or not row.result_key:
        raise _http_error(404, "result_not_found", "Try-on result not found.")
    content = LocalPrivateStorage().read(row.result_key)
    return Response(content, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/try-on/jobs/{job_id}/cancel", response_model=TryOnJobView)
def cancel_tryon_job(job_id: UUID, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    row = db.scalar(select(TryOnJob).where(TryOnJob.id == job_id, TryOnJob.user_id == user.id))
    if row is None:
        raise _http_error(404, "job_not_found", "Try-on job not found.")
    if row.state == "queued":
        db.execute(
            update(TryOnJob).where(TryOnJob.id == row.id, TryOnJob.state == "queued")
            .values(state="cancelled", updated_at=utcnow()).execution_options(synchronize_session=False)
        )
    elif row.state == "running" and row.cancellation_requested_at is None:
        row.cancellation_requested_at = utcnow()
    db.commit()
    db.refresh(row)
    return _job_view(row)


@router.delete("/try-on/jobs/{job_id}", status_code=204)
async def delete_tryon_job(job_id: UUID, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    row = db.scalar(select(TryOnJob).where(TryOnJob.id == job_id, TryOnJob.user_id == user.id))
    if row is None:
        raise _http_error(404, "job_not_found", "Try-on job not found.")
    keys = []
    if row.result_key:
        keys.append(row.result_key)
        db.add(StorageDeletion(image_key=row.result_key))
    delete_jobs(db, [row])
    db.commit()
    cleanup_pending = await _delete_private_keys(db, keys)
    return _deletion_response(cleanup_pending)
