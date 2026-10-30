import io
from uuid import UUID, uuid4

from PIL import Image, ImageDraw, ImageOps
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from ..database import SessionLocal
from ..models import Garment, PersonPhoto, StorageDeletion, TryOnAttempt, TryOnJob, utcnow
from ..storage.local_disk import LocalPrivateStorage
from .adapters import MOCK_ADAPTER, UNSUPPORTED_ADAPTER, supports_mock_profile


def _claim(job_id: UUID, session_factory: sessionmaker) -> tuple[UUID, dict] | None:
    token = uuid4()
    with session_factory() as db:
        job = db.get(TryOnJob, job_id)
        if job is None or job.state != "queued" or job.cancellation_requested_at is not None:
            return None
        number = job.attempt_count + 1
        result = db.execute(
            update(TryOnJob)
            .where(
                TryOnJob.id == job_id,
                TryOnJob.state == "queued",
                TryOnJob.cancellation_requested_at.is_(None),
            )
            .values(state="running", attempt_count=number, active_attempt_token=token, updated_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            db.rollback()
            return None
        db.add(TryOnAttempt(job_id=job_id, attempt_number=number, attempt_token=token, state="running"))
        db.commit()
        job = db.get(TryOnJob, job_id)
        return token, {"user_id": job.user_id, "mode": job.mode, "input": dict(job.input_snapshot), "settings": job.settings_snapshot}


def _mock_preview(person_bytes: bytes, garment_bytes: bytes) -> bytes:
    canvas = Image.new("RGB", (1000, 680), "#f3efe9")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1000, 104), fill="#1f2933")
    draw.text((32, 24), "MOCK TRY-ON · NO IMAGE GENERATION", fill="white")
    draw.text((32, 58), "Workflow preview only. This is not a generated outfit or fit result.", fill="#d8dee5")
    draw.text((140, 124), "PERSON PHOTO", fill="#1f2933")
    draw.text((655, 124), "GARMENT PHOTO", fill="#1f2933")

    for data, box in ((person_bytes, (44, 154, 480, 600)), (garment_bytes, (520, 154, 956, 600))):
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.contain(source.convert("RGB"), (box[2] - box[0], box[3] - box[1]))
        x = box[0] + (box[2] - box[0] - image.width) // 2
        y = box[1] + (box[3] - box[1] - image.height) // 2
        canvas.paste(image, (x, y))
        draw.rectangle(box, outline="#9ba3a8", width=2)
    draw.text((369, 626), "MOCK PREVIEW — NOT A VIRTUAL TRY-ON", fill="#9b2c2c")
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _fail(job_id: UUID, token: UUID, code: str, session_factory: sessionmaker) -> None:
    now = utcnow()
    with session_factory() as db:
        db.execute(
            update(TryOnJob)
            .where(TryOnJob.id == job_id, TryOnJob.state == "running", TryOnJob.active_attempt_token == token)
            .values(state="failed", error_code=code, active_attempt_token=None, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.attempt_token == token))
        if attempt is not None:
            attempt.state, attempt.error_code, attempt.finished_at = "failed", code, now
        db.commit()


def _publish(job_id: UUID, token: UUID, result_key: str, session_factory: sessionmaker) -> bool:
    now = utcnow()
    with session_factory() as db:
        result = db.execute(
            update(TryOnJob)
            .where(
                TryOnJob.id == job_id,
                TryOnJob.state == "running",
                TryOnJob.active_attempt_token == token,
                TryOnJob.cancellation_requested_at.is_(None),
            )
            .values(
                state="succeeded",
                result_key=result_key,
                result_metadata={
                    "mode": "mock",
                    "adapter": MOCK_ADAPTER,
                    "notice": "Workflow preview only. No virtual try-on model ran.",
                },
                active_attempt_token=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.attempt_token == token))
        if result.rowcount == 1:
            if attempt is not None:
                attempt.state, attempt.finished_at = "succeeded", now
            db.commit()
            return True
        job = db.get(TryOnJob, job_id)
        if job is not None and job.active_attempt_token == token and job.cancellation_requested_at is not None:
            job.state, job.active_attempt_token, job.updated_at = "cancelled", None, now
            if attempt is not None:
                attempt.state, attempt.finished_at = "cancelled", now
        db.commit()
        return False


def process_mock_job(job_id: str, session_factory: sessionmaker = SessionLocal, storage: LocalPrivateStorage | None = None) -> None:
    """Run one mock delivery; the database claim token makes duplicate deliveries harmless."""
    try:
        parsed_id = UUID(job_id)
    except ValueError:
        return
    claim = _claim(parsed_id, session_factory)
    if claim is None:
        return
    token, snapshot = claim
    if not supports_mock_profile(snapshot["mode"], snapshot["settings"]):
        _fail(parsed_id, token, UNSUPPORTED_ADAPTER, session_factory)
        return
    private_storage = storage or LocalPrivateStorage()
    result_key = None
    try:
        with session_factory() as db:
            job = db.get(TryOnJob, parsed_id)
            photo = db.get(PersonPhoto, job.person_photo_id) if job is not None else None
            garment = db.get(Garment, job.garment_id) if job is not None else None
            if (
                job is None
                or photo is None
                or garment is None
                or job.user_id != snapshot["user_id"]
                or photo.user_id != job.user_id
                or garment.user_id != job.user_id
                or photo.consent_version != snapshot["input"]["consent_version"]
                or photo.image_key != snapshot["input"]["person_photo_image_key"]
                or garment.image_key != snapshot["input"]["garment_image_key"]
            ):
                unavailable = True
            else:
                unavailable = False
            if job is not None and job.cancellation_requested_at is not None:
                job.state, job.active_attempt_token, job.updated_at = "cancelled", None, utcnow()
                attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.attempt_token == token))
                if attempt is not None:
                    attempt.state, attempt.finished_at = "cancelled", utcnow()
                db.commit()
                return
            if not unavailable:
                person_key = snapshot["input"]["person_photo_image_key"]
                garment_key = snapshot["input"]["garment_image_key"]
        if unavailable:
            _fail(parsed_id, token, "input_unavailable", session_factory)
            return

        person_bytes = private_storage.read(person_key)
        garment_bytes = private_storage.read(garment_key)
        output_bytes = _mock_preview(person_bytes, garment_bytes)
        result_key = private_storage.put(output_bytes)
        if not _publish(parsed_id, token, result_key, session_factory):
            private_storage.delete(result_key)
    except HTTPException:
        _fail(parsed_id, token, "input_unavailable", session_factory)
    except Exception:
        _fail(parsed_id, token, "worker_error", session_factory)
        if result_key is not None:
            with session_factory() as db:
                referenced = db.scalar(select(TryOnJob.id).where(TryOnJob.result_key == result_key))
            if referenced is None:
                try:
                    private_storage.delete(result_key)
                except Exception:
                    with session_factory() as db:
                        if db.scalar(select(StorageDeletion.id).where(StorageDeletion.image_key == result_key)) is None:
                            db.add(StorageDeletion(image_key=result_key))
                            db.commit()


def run_mock_job(job_id: str) -> None:
    process_mock_job(job_id)
