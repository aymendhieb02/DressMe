import asyncio
import csv
import io
from datetime import timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..auth.dependencies import current_user, current_user_csrf
from ..config import get_settings
from ..database import get_db
from .eligibility import POLICY_VERSION, evaluate_vton_eligibility
from ..tryon.deletion import delete_jobs
from ..ml.client import BO6Client, BO6Rejected, BO6Unavailable
from ..models import Garment, PendingUpload, StorageDeletion, TryOnJob, User, utcnow
from ..storage.cleanup import acknowledge_storage_deletion, record_storage_deletion_failure
from ..storage.local_disk import LocalPrivateStorage
from ..uploads import normalize_image
from .schemas import DescribeInput, GarmentList, GarmentPatch, GarmentView, PendingUploadView, SaveGarmentInput
from .review import BOTTOM_CATEGORIES, normalize_review

router = APIRouter(prefix="/garments", tags=["wardrobe"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "garment_not_found", "message": "Garment not found."})


def _pending(db: Session, pending_id: UUID, user_id: UUID) -> PendingUpload:
    row = db.scalar(select(PendingUpload).where(PendingUpload.id == pending_id, PendingUpload.user_id == user_id))
    expires = row.expires_at if row is not None else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if row is None or row.consumed_at is not None or expires <= utcnow():
        raise HTTPException(status_code=404, detail={"code": "upload_unavailable", "message": "Pending upload is unavailable or expired."})
    return row


def _serialize(row: Garment) -> GarmentView:
    return GarmentView(
        id=row.id, category=row.category, color=row.color, pattern=row.pattern, sleeve_length=row.sleeve_length,
        garment_photo_type=row.garment_photo_type, vton_eligibility=row.vton_eligibility,
        vton_eligibility_version=row.vton_eligibility_version,
        description=row.description, description_is_manual=row.description_is_manual, name=row.name, notes=row.notes,
        image_url=f"/garments/{row.id}/image", prediction_snapshot=row.prediction_snapshot,
        quality_snapshot=row.quality_snapshot, field_sources=row.field_sources, was_corrected=row.was_corrected,
        model_version=row.model_version, taxonomy_version=row.taxonomy_version,
        description_version=row.description_version, created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat(),
        description_provenance=row.description_provenance,
    )


def _description_fields(row: Garment) -> dict:
    fields = {"category": row.category}
    for name in ("color", "pattern", "sleeve_length"):
        value = getattr(row, name)
        if value is not None:
            fields[name] = value
    return normalize_review(fields)


def _serialize_pending(row: PendingUpload) -> PendingUploadView:
    return PendingUploadView(id=row.id, image_url=f"/garments/uploads/{row.id}/image", image_sha256=row.image_sha256,
                             width=row.width, height=row.height, quality=row.quality_snapshot, prediction=row.prediction_snapshot,
                             expires_at=row.expires_at.isoformat())


def _replay_saved(db: Session, body: SaveGarmentInput, user_id: UUID) -> GarmentView | None:
    row = db.scalar(select(Garment).where(Garment.pending_upload_id == body.pending_upload_id, Garment.user_id == user_id))
    if row is None:
        return None
    fields = normalize_review(body.model_dump(include={"category", "color", "pattern", "sleeve_length"}, exclude_none=True))
    matches = all(getattr(row, key) == fields.get(key) for key in ("category", "color", "pattern", "sleeve_length"))
    matches = matches and row.garment_photo_type == body.garment_photo_type and row.name == body.name and row.notes == body.notes
    matches = matches and row.description_is_manual == (body.description is not None)
    if body.description is not None:
        matches = matches and row.description == body.description.strip()
    if not matches:
        raise HTTPException(status_code=409, detail={"code": "upload_already_consumed", "message": "This upload was already saved with different details. Open your wardrobe to review it."})
    return _serialize(row)


def _csv_cell(value) -> str:
    """Serialize user-controlled text safely for spreadsheet applications."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        text = value.isoformat()
    else:
        text = str(value)
    formula_candidate = text.lstrip()
    if (text and (ord(text[0]) < 32 or ord(text[0]) == 127)) or formula_candidate.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@router.post("/analyze", response_model=PendingUploadView, status_code=201)
async def analyze_upload(
    image: UploadFile = File(...),
    idempotency_key: UUID | None = Header(None, alias="Idempotency-Key"),
    user: User = Depends(current_user_csrf),
    db: Session = Depends(get_db),
):
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if image.content_type not in allowed:
        raise HTTPException(status_code=415, detail={"code": "unsupported_media_type", "message": "Upload a JPEG, PNG, or WEBP image."})
    data, width, height, digest = normalize_image(await image.read(get_settings().max_upload_bytes + 1))
    if idempotency_key is not None:
        existing = db.get(PendingUpload, idempotency_key)
        if existing is not None:
            if existing.user_id != user.id or existing.image_sha256 != digest:
                raise HTTPException(status_code=409, detail={"code": "upload_request_conflict", "message": "Choose the photo again to start a new analysis."})
            return _serialize_pending(_pending(db, idempotency_key, user.id))
    storage = LocalPrivateStorage()
    image_key = await asyncio.to_thread(storage.put, data)
    try:
        result = await BO6Client().analyze(data, "upload.png", "image/png")
        prediction, quality = result.prediction, result.quality
        pending = PendingUpload(
            **({"id": idempotency_key} if idempotency_key is not None else {}),
            user_id=user.id, image_key=image_key, content_type="image/png", image_sha256=digest,
            width=width, height=height, quality_snapshot=quality, prediction_snapshot=prediction,
            model_version=prediction["model_version"], taxonomy_version=prediction["taxonomy_version"],
            description_version=prediction["description_version"], quality_version=quality["version"],
            expires_at=utcnow() + timedelta(seconds=get_settings().pending_upload_ttl_seconds),
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        return _serialize_pending(pending)
    except IntegrityError:
        # Concurrent retries can both finish inference; only one owns the key.
        db.rollback()
        await asyncio.to_thread(storage.delete, image_key)
        existing = db.get(PendingUpload, idempotency_key) if idempotency_key else None
        if existing is not None and existing.user_id == user.id and existing.image_sha256 == digest:
            return _serialize_pending(_pending(db, existing.id, user.id))
        raise HTTPException(status_code=409, detail={"code": "upload_request_conflict", "message": "Choose the photo again to start a new analysis."}) from None
    except BO6Rejected:
        db.rollback()
        await asyncio.to_thread(storage.delete, image_key)
        raise HTTPException(status_code=422, detail={"code": "bo6_rejected_input", "message": "The analysis service rejected this image."}) from None
    except BO6Unavailable:
        db.rollback()
        await asyncio.to_thread(storage.delete, image_key)
        raise HTTPException(status_code=503, detail={"code": "ml_unavailable", "message": "Garment analysis is temporarily unavailable. Your upload was not saved."}) from None
    except Exception:
        db.rollback()
        await asyncio.to_thread(storage.delete, image_key)
        raise


@router.post("/describe")
async def describe_review(body: DescribeInput, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    _pending(db, body.pending_upload_id, user.id)
    try:
        described = await BO6Client().describe(normalize_review(body.confirmed.model_dump(exclude_none=True)))
        return described.model_dump()
    except BO6Rejected:
        raise HTTPException(status_code=422, detail={"code": "bo6_rejected_input", "message": "The description service rejected these fields."}) from None
    except BO6Unavailable:
        raise HTTPException(status_code=503, detail={"code": "ml_unavailable", "message": "Description generation is temporarily unavailable."}) from None


@router.get("/uploads/{pending_id}/image")
def pending_image(pending_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    pending = _pending(db, pending_id, user.id)
    content = LocalPrivateStorage().read(pending.image_key)
    return Response(content, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/uploads/{pending_id}", status_code=204)
def delete_pending_upload(pending_id: UUID, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    pending = db.scalar(select(PendingUpload).where(PendingUpload.id == pending_id, PendingUpload.user_id == user.id))
    if pending is None:
        raise HTTPException(status_code=404, detail={"code": "upload_unavailable", "message": "Pending upload is unavailable."})
    if pending.consumed_at is not None:
        raise HTTPException(status_code=409, detail={"code": "upload_already_consumed", "message": "The upload belongs to a saved garment."})
    db.add(StorageDeletion(image_key=pending.image_key))
    image_key = pending.image_key
    db.delete(pending)
    db.commit()
    try:
        LocalPrivateStorage().delete(image_key)
    except Exception:
        record_storage_deletion_failure(db, image_key)
        return JSONResponse(status_code=202, content={"status": "deletion_queued", "message": "Access was revoked; private file cleanup is queued for retry."})
    deletion = db.scalar(select(StorageDeletion).where(StorageDeletion.image_key == image_key))
    if deletion is not None:
        db.delete(deletion)
        db.commit()
    return Response(status_code=204)


@router.post("", response_model=GarmentView, status_code=201)
async def save_garment(body: SaveGarmentInput, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    replay = _replay_saved(db, body, user.id)
    if replay is not None:
        return replay
    pending = _pending(db, body.pending_upload_id, user.id)
    fields = normalize_review(body.model_dump(include={"category", "color", "pattern", "sleeve_length"}, exclude_none=True))
    manual = body.description is not None
    description_provenance = {"source": "user_manual"}
    if manual:
        description = body.description.strip()
        if not description:
            raise HTTPException(status_code=422, detail={"code": "invalid_description", "message": "Description must not be blank."})
        description_version = pending.description_version
    else:
        try:
            described = await BO6Client().describe(fields)
        except BO6Rejected:
            raise HTTPException(status_code=422, detail={"code": "bo6_rejected_input", "message": "The description service rejected these fields."}) from None
        except BO6Unavailable:
            raise HTTPException(status_code=503, detail={"code": "ml_unavailable", "message": "Description generation is temporarily unavailable; the garment was not saved."}) from None
        description, description_version = described.text, described.schema_version
        description_provenance = described.provenance
    sources = {name: ("user_confirmed" if name in fields else "not_estimated") for name in ("category", "color", "pattern", "sleeve_length")}
    sources["garment_photo_type"] = "user_confirmed"
    corrected = {name: (fields.get(name) != pending.prediction_snapshot.get("description_fields", {}).get(name))
                 for name in ("category", "color", "pattern", "sleeve_length") if name in fields}
    garment = Garment(
        user_id=user.id, pending_upload_id=pending.id, image_key=pending.image_key, category=body.category,
        garment_photo_type=body.garment_photo_type,
        vton_eligibility=evaluate_vton_eligibility(body.category, body.garment_photo_type),
        vton_eligibility_version=POLICY_VERSION,
        color=fields.get("color"), pattern=fields.get("pattern"), sleeve_length=fields.get("sleeve_length"),
        description=description, description_is_manual=manual, name=body.name, notes=body.notes,
        prediction_snapshot=pending.prediction_snapshot, quality_snapshot=pending.quality_snapshot,
        field_sources=sources, was_corrected=corrected, model_version=pending.model_version,
        taxonomy_version=pending.taxonomy_version, description_version=description_version,
        description_provenance=description_provenance,
    )
    pending.consumed_at = utcnow()
    db.add(garment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = _replay_saved(db, body, user.id)
        if replay is not None:
            return replay
        raise HTTPException(status_code=409, detail={"code": "upload_already_consumed", "message": "This pending upload has already been saved."}) from None
    db.refresh(garment)
    return _serialize(garment)


@router.get("", response_model=GarmentList)
def list_garments(
    category: str | None = None, color: str | None = None,
    q: str | None = Query(None, max_length=200),
    sort: Literal["newest", "oldest"] = "newest",
    page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    stmt = select(Garment).where(Garment.user_id == user.id)
    count_stmt = select(func.count()).select_from(Garment).where(Garment.user_id == user.id)
    if category is not None:
        stmt, count_stmt = stmt.where(Garment.category == category), count_stmt.where(Garment.category == category)
    if color is not None:
        stmt, count_stmt = stmt.where(Garment.color == color), count_stmt.where(Garment.color == color)
    if q is not None and q.strip():
        # Literal substring search over the whole owned wardrobe, before paging.
        condition = Garment.description.icontains(q.strip(), autoescape=True)
        stmt, count_stmt = stmt.where(condition), count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    ordering = (Garment.created_at.asc(), Garment.id.asc()) if sort == "oldest" else (Garment.created_at.desc(), Garment.id.desc())
    rows = db.scalars(stmt.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)).all()
    return GarmentList(items=[_serialize(row) for row in rows], page=page, page_size=page_size, total=total)


@router.get("/export.csv")
def export_garments_csv(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Garment).where(Garment.user_id == user.id).order_by(Garment.created_at, Garment.id)
    ).all()
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow((
        "garment_id", "category", "garment_photo_type", "color", "pattern", "sleeve_length",
        "description", "description_mode", "name", "notes", "created_at", "updated_at",
    ))
    for row in rows:
        writer.writerow(tuple(_csv_cell(value) for value in (
            row.id, row.category, row.garment_photo_type, row.color, row.pattern, row.sleeve_length,
            row.description, "manual" if row.description_is_manual else "generated", row.name, row.notes,
            row.created_at, row.updated_at,
        )))
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="dressme-wardrobe.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Export-Row-Count": str(len(rows)),
        },
    )


@router.get("/{garment_id}", response_model=GarmentView)
def get_garment(garment_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(Garment).where(Garment.id == garment_id, Garment.user_id == user.id))
    if row is None:
        raise _not_found()
    return _serialize(row)


@router.get("/{garment_id}/image")
def garment_image(garment_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(Garment).where(Garment.id == garment_id, Garment.user_id == user.id))
    if row is None:
        raise _not_found()
    content = LocalPrivateStorage().read(row.image_key)
    return Response(content, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.patch("/{garment_id}", response_model=GarmentView)
async def update_garment(garment_id: UUID, body: GarmentPatch, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    row = db.scalar(select(Garment).where(Garment.id == garment_id, Garment.user_id == user.id))
    if row is None:
        raise _not_found()
    changes = body.model_dump(exclude_unset=True)
    description_fields_changed = any(
        name in changes for name in ("category", "color", "pattern", "sleeve_length")
    )
    if "category" in changes and changes["category"] is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_category", "message": "Category cannot be cleared."})
    manual_description = changes.pop("description", None) if "description" in changes else None
    for key, value in changes.items():
        setattr(row, key, value)
    if row.category in BOTTOM_CATEGORIES and row.sleeve_length is not None:
        row.sleeve_length = None
        changes["sleeve_length"] = None
        description_fields_changed = True
    if "garment_photo_type" in changes:
        row.field_sources["garment_photo_type"] = "user_confirmed"
        flag_modified(row, "field_sources")
    if "category" in changes or "garment_photo_type" in changes:
        row.vton_eligibility = evaluate_vton_eligibility(row.category, row.garment_photo_type)
        row.vton_eligibility_version = POLICY_VERSION
        flag_modified(row, "vton_eligibility")
    if "description" in body.model_fields_set:
        if manual_description is None or not manual_description.strip():
            raise HTTPException(status_code=422, detail={"code": "invalid_description", "message": "Description must not be blank."})
        row.description, row.description_is_manual = manual_description.strip(), True
        row.description_provenance = {"source": "user_manual"}
        flag_modified(row, "description_provenance")
    elif description_fields_changed and not row.description_is_manual:
        try:
            described = await BO6Client().describe(_description_fields(row))
        except BO6Rejected:
            db.rollback()
            raise HTTPException(status_code=422, detail={"code": "bo6_rejected_input", "message": "The description service rejected these fields."}) from None
        except BO6Unavailable:
            db.rollback()
            raise HTTPException(status_code=503, detail={"code": "ml_unavailable", "message": "Description regeneration is temporarily unavailable; edits were not saved."}) from None
        row.description, row.description_version = described.text, described.schema_version
        row.description_provenance = described.provenance
        flag_modified(row, "description_provenance")
    for key, value in changes.items():
        if key in {"category", "color", "pattern", "sleeve_length"}:
            row.field_sources[key] = "user_confirmed" if value is not None else "not_estimated"
            row.was_corrected[key] = value != row.prediction_snapshot.get("description_fields", {}).get(key)
            flag_modified(row, "field_sources")
            flag_modified(row, "was_corrected")
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.post("/{garment_id}/regenerate-description", response_model=GarmentView)
async def regenerate_description(garment_id: UUID, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    row = db.scalar(select(Garment).where(Garment.id == garment_id, Garment.user_id == user.id))
    if row is None:
        raise _not_found()
    try:
        described = await BO6Client().describe(_description_fields(row))
    except BO6Rejected:
        raise HTTPException(status_code=422, detail={"code": "bo6_rejected_input", "message": "The description service rejected these fields."}) from None
    except BO6Unavailable:
        raise HTTPException(status_code=503, detail={"code": "ml_unavailable", "message": "Description regeneration is temporarily unavailable."}) from None
    row.description, row.description_version, row.description_is_manual = described.text, described.schema_version, False
    row.description_provenance = described.provenance
    flag_modified(row, "description_provenance")
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/{garment_id}", status_code=204)
async def delete_garment(garment_id: UUID, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    row = db.scalar(select(Garment).where(Garment.id == garment_id, Garment.user_id == user.id))
    if row is None:
        raise _not_found()
    pending = db.scalar(select(PendingUpload).where(PendingUpload.id == row.pending_upload_id, PendingUpload.user_id == user.id))
    jobs = db.scalars(select(TryOnJob).where(TryOnJob.garment_id == row.id, TryOnJob.user_id == user.id)).all()
    keys = [row.image_key]
    db.add(StorageDeletion(image_key=row.image_key))
    for job in jobs:
        if job.result_key:
            keys.append(job.result_key)
            db.add(StorageDeletion(image_key=job.result_key))
    delete_jobs(db, jobs)
    db.flush()
    db.delete(row)
    if pending is not None:
        db.delete(pending)
    db.commit()
    cleanup_pending = False
    for key in keys:
        try:
            await asyncio.to_thread(LocalPrivateStorage().delete, key)
        except Exception:
            record_storage_deletion_failure(db, key)
            cleanup_pending = True
            continue
        acknowledge_storage_deletion(db, key)
    if cleanup_pending:
        return JSONResponse(status_code=202, content={"status": "deletion_queued", "message": "Access was revoked; private file cleanup is queued for retry."})
    return Response(status_code=204)
