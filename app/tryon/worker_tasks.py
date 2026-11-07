import io
import json
import os
import re
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from ..config import get_settings
from ..database import SessionLocal
from ..models import Garment, PersonPhoto, StorageDeletion, TryOnAttempt, TryOnJob, utcnow
from ..storage.local_disk import LocalPrivateStorage
from .adapters import FASHN_ADAPTER, MOCK_ADAPTER, UNSUPPORTED_ADAPTER, run_fashn, supports_mock_profile, supports_real_profile
from .workflow import SEQUENTIAL_WORKFLOW

DATA_DIR = Path(os.environ.get("DRESSME_DATA", Path(__file__).resolve().parents[2] / "data")).resolve()
CATALOG_CATEGORIES = {"top": "tops", "bottom": "bottoms", "outer": "tops", "dress": "one-pieces"}

HEARTBEAT_SECONDS = 30
_heartbeat = None
_last_heartbeat = 0.0


class TryOnFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TryOnCancelled(Exception):
    pass


def _catalog_image_path(item: dict) -> Path:
    """Resolve only an indexed, supported garment from the shared OOTD catalog."""
    try:
        catalog_id = item["catalog_id"]
        code = item["catalog_code"]
        category = item["garment_category"]
        catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
        codes, categories = catalog["codes"], catalog["cat"]
    except (OSError, ValueError, KeyError, TypeError):
        raise TryOnFailure("input_unavailable") from None
    if (
        type(catalog_id) is not int
        or catalog_id < 0
        or catalog_id >= len(codes)
        or len(codes) != len(categories)
        or codes[catalog_id] != code
        or categories[catalog_id] != category
        or CATALOG_CATEGORIES.get(category) != item.get("candidate_vton_category")
        or item.get("source") != "catalog"
        or not isinstance(code, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", code)
    ):
        raise TryOnFailure("input_unavailable")
    path = (DATA_DIR / "img" / f"{code}.jpg").resolve()
    if DATA_DIR not in path.parents or not path.is_file():
        raise TryOnFailure("input_unavailable")
    return path


def _remove_edge_background(data: bytes) -> tuple[bytes, bool]:
    """Remove a uniform background connected to the image edges; retain uncertain images intact."""
    try:
        source = Image.open(io.BytesIO(data)).convert("RGBA")
        width, height = source.size
        if width < 32 or height < 32:
            return data, False
        rgb = source.convert("RGB")
        points = ((1, 1), (width - 2, 1), (1, height - 2), (width - 2, height - 2))
        corner_colors = []
        patch_size = min(12, width // 4, height // 4)
        for x, y in points:
            box = (max(0, x - patch_size // 2), max(0, y - patch_size // 2),
                   min(width, x + patch_size // 2 + 1), min(height, y + patch_size // 2 + 1))
            stats = ImageStat.Stat(rgb.crop(box))
            if max(stats.stddev) > 24:
                return data, False
            corner_colors.append(stats.mean[:3])
        for index, color in enumerate(corner_colors):
            for other in corner_colors[index + 1:]:
                if sum((a - b) ** 2 for a, b in zip(color, other)) ** 0.5 > 58:
                    return data, False

        removed = Image.new("L", source.size, 0)
        for point in points:
            marked = source.copy()
            ImageDraw.floodfill(marked, point, (255, 0, 255, 0), thresh=42)
            region = marked.getchannel("A").point(lambda alpha: 255 - alpha)
            removed = ImageChops.lighter(removed, region)
        coverage = ImageStat.Stat(removed).mean[0] / 255
        if coverage < 0.01 or coverage > 0.78:
            return data, False
        source.putalpha(ImageChops.darker(source.getchannel("A"), ImageOps.invert(removed)))
        output = io.BytesIO()
        source.save(output, format="PNG", optimize=True)
        return output.getvalue(), True
    except Exception:
        return data, False


def set_heartbeat(heartbeat) -> None:
    """An in-process worker cannot beat during a job, so long real jobs do it from their polling loop."""
    global _heartbeat
    _heartbeat = heartbeat


def _beat() -> None:
    global _last_heartbeat
    if _heartbeat is None or time.monotonic() - _last_heartbeat < HEARTBEAT_SECONDS:
        return
    _last_heartbeat = time.monotonic()
    try:
        _heartbeat()
    except Exception:  # a missed heartbeat must not fail the job
        pass


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
        return token, {
            "user_id": job.user_id,
            "mode": job.mode,
            "garment_id": job.garment_id,
            "input": dict(job.input_snapshot),
            "settings": job.settings_snapshot,
        }


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


def _cancel(job_id: UUID, token: UUID, session_factory: sessionmaker) -> None:
    now = utcnow()
    with session_factory() as db:
        db.execute(
            update(TryOnJob)
            .where(TryOnJob.id == job_id, TryOnJob.state == "running", TryOnJob.active_attempt_token == token)
            .values(state="cancelled", active_attempt_token=None, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.attempt_token == token))
        if attempt is not None:
            attempt.state, attempt.finished_at = "cancelled", now
        db.commit()


def _publish(job_id: UUID, token: UUID, result_key: str, session_factory: sessionmaker, metadata: dict | None = None) -> bool:
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
                result_metadata=metadata or {
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


def _process_job(job_id: str, session_factory: sessionmaker, storage: LocalPrivateStorage | None, supports, generate) -> None:
    """Run one delivery; the database claim token makes duplicate deliveries harmless."""
    try:
        parsed_id = UUID(job_id)
    except ValueError:
        return
    claim = _claim(parsed_id, session_factory)
    if claim is None:
        return
    token, snapshot = claim
    if not supports(snapshot["mode"], snapshot["settings"]):
        _fail(parsed_id, token, UNSUPPORTED_ADAPTER, session_factory)
        return
    private_storage = storage or LocalPrivateStorage()
    result_key = None
    try:
        inputs = snapshot["input"]
        garment_inputs = inputs.get("garments") or [{
            "garment_id": str(snapshot["garment_id"]),
            "garment_image_key": inputs.get("garment_image_key"),
            "garment_category": inputs.get("garment_category"),
            "garment_photo_type": inputs.get("garment_photo_type"),
            "candidate_vton_category": inputs.get("candidate_vton_category"),
        }]
        catalog_sequence = inputs.get("source") == "ootd-catalog"
        if catalog_sequence and any(item.get("source") != "catalog" for item in garment_inputs):
            _fail(parsed_id, token, "input_unavailable", session_factory)
            return
        garment_refs = [
            str(item["catalog_id"] if item.get("source") == "catalog" else item["garment_id"])
            for item in garment_inputs
        ]
        garment_ids = [] if catalog_sequence else [UUID(str(item["garment_id"])) for item in garment_inputs]
        catalog_paths = []
        with session_factory() as db:
            job = db.get(TryOnJob, parsed_id)
            photo = db.get(PersonPhoto, job.person_photo_id) if job is not None else None
            if (
                job is None
                or photo is None
                or job.user_id != snapshot["user_id"]
                or photo.user_id != job.user_id
                or photo.consent_version != snapshot["input"]["consent_version"]
                or photo.image_key != snapshot["input"]["person_photo_image_key"]
                or not garment_inputs
            ):
                unavailable = True
            else:
                unavailable = False
            if not unavailable and catalog_sequence:
                unavailable = job.garment_id is not None
                if not unavailable:
                    try:
                        catalog_paths = [_catalog_image_path(item) for item in garment_inputs]
                    except TryOnFailure:
                        unavailable = True
            elif not unavailable:
                garments = db.scalars(select(Garment).where(Garment.id.in_(garment_ids))).all()
                garment_by_id = {garment.id: garment for garment in garments}
                unavailable = job.garment_id != garment_ids[0] or any(
                    (garment := garment_by_id.get(garment_id)) is None
                    or garment.user_id != job.user_id
                    or garment.image_key != item.get("garment_image_key")
                    for item, garment_id in zip(garment_inputs, garment_ids)
                )
            if job is not None and job.cancellation_requested_at is not None:
                job.state, job.active_attempt_token, job.updated_at = "cancelled", None, utcnow()
                attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.attempt_token == token))
                if attempt is not None:
                    attempt.state, attempt.finished_at = "cancelled", utcnow()
                db.commit()
                return
            if not unavailable:
                person_key = snapshot["input"]["person_photo_image_key"]
                garment_keys = [item.get("garment_image_key") for item in garment_inputs]
        if unavailable:
            _fail(parsed_id, token, "input_unavailable", session_factory)
            return

        person_bytes = private_storage.read(person_key)
        garment_data = [
            path.read_bytes() if catalog_sequence else private_storage.read(key)
            for path, key in zip(catalog_paths or [None] * len(garment_inputs), garment_keys)
        ]
        garment_payload = garment_data[0] if len(garment_data) == 1 else {
            ref: data for ref, data in zip(garment_refs, garment_data)
        }

        def report_progress(step: int, total: int, garment_id: str) -> None:
            if total < 2:
                return
            with session_factory() as db:
                db.execute(
                    update(TryOnJob)
                    .where(
                        TryOnJob.id == parsed_id,
                        TryOnJob.state == "running",
                        TryOnJob.active_attempt_token == token,
                    )
                    .values(
                        result_metadata={
                            "workflow": SEQUENTIAL_WORKFLOW,
                            "current_step": step,
                            "total_steps": total,
                            "current_garment_id": garment_id,
                            "status": "running",
                        },
                        updated_at=utcnow(),
                    )
                    .execution_options(synchronize_session=False)
                )
                db.commit()

        output_bytes, metadata = generate(parsed_id, person_bytes, garment_payload, snapshot, report_progress)
        result_key = private_storage.put(output_bytes)
        if not _publish(parsed_id, token, result_key, session_factory, metadata):
            private_storage.delete(result_key)
    except TryOnCancelled:
        _cancel(parsed_id, token, session_factory)
    except TryOnFailure as failure:
        _fail(parsed_id, token, failure.code, session_factory)
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


def process_mock_job(job_id: str, session_factory: sessionmaker = SessionLocal, storage: LocalPrivateStorage | None = None) -> None:
    def generate(_job_id, person_bytes, garment_payload, _snapshot, _progress):
        garment_bytes = next(iter(garment_payload.values())) if isinstance(garment_payload, dict) else garment_payload
        return _mock_preview(person_bytes, garment_bytes), None

    _process_job(job_id, session_factory, storage, supports_mock_profile, generate)


def _cancel_requested(job_id: UUID, session_factory: sessionmaker) -> bool:
    with session_factory() as db:
        return db.scalar(select(TryOnJob.cancellation_requested_at).where(TryOnJob.id == job_id)) is not None


def process_real_job(
    job_id: str,
    session_factory: sessionmaker = SessionLocal,
    storage: LocalPrivateStorage | None = None,
    runner=run_fashn,
) -> None:
    def generate(parsed_id, person_bytes, garment_payload, snapshot, progress):
        settings = get_settings()
        if settings.vton_mode != "real":
            raise TryOnFailure("real_vton_unavailable")
        private_root = Path(settings.storage_path).resolve()
        private_root.mkdir(parents=True, exist_ok=True)
        inputs = snapshot["input"]
        garment_inputs = inputs.get("garments") or [{
            "garment_id": str(snapshot["garment_id"]),
            "garment_category": inputs["garment_category"],
            "garment_photo_type": inputs["garment_photo_type"],
            "candidate_vton_category": inputs["candidate_vton_category"],
        }]
        garment_bytes_by_id = garment_payload if isinstance(garment_payload, dict) else {
            str(garment_inputs[0].get("catalog_id") if garment_inputs[0].get("source") == "catalog" else garment_inputs[0]["garment_id"]): garment_payload
        }
        # Intermediate images stay private and temporary; only the final image is stored in history.
        with tempfile.TemporaryDirectory(prefix=".vton-", dir=private_root, ignore_cleanup_errors=True) as folder:
            current_person = person_bytes
            step_results = []
            total = len(garment_inputs)
            for index, item in enumerate(garment_inputs, start=1):
                if _cancel_requested(parsed_id, session_factory):
                    raise TryOnCancelled()
                garment_id = str(item.get("catalog_id") if item.get("source") == "catalog" else item["garment_id"])
                if total > 1:
                    progress(index, total, garment_id)
                person_path = Path(folder) / f"person-{index}.png"
                garment_path = Path(folder) / f"garment-{index}.png"
                output_dir = Path(folder) / f"step-{index}" / "output"
                person_path.write_bytes(current_person)
                garment_path.write_bytes(garment_bytes_by_id[garment_id])
                outcome = runner(
                    person_path, garment_path, item.get("candidate_vton_category", inputs["candidate_vton_category"]),
                    item.get("garment_photo_type", inputs["garment_photo_type"]), output_dir=output_dir, settings=settings,
                    should_cancel=lambda: _cancel_requested(parsed_id, session_factory), tick=_beat,
                )
                if outcome.failure == "cancelled":
                    raise TryOnCancelled()
                if outcome.failure:
                    raise TryOnFailure(outcome.failure)
                current_person = outcome.output_path.read_bytes()
                step_results.append({
                    "garment_id": garment_id,
                    "backend": outcome.details.get("backend"),
                    "remote_status": outcome.details.get("remote_status"),
                    "wall_seconds": outcome.details.get("wall_seconds"),
                })
            background_removed = False
            if inputs.get("remove_background"):
                current_person, background_removed = _remove_edge_background(current_person)
            if total == 1:
                return current_person, {"mode": "real", "adapter": FASHN_ADAPTER, **outcome.details,
                                        "background_removed": background_removed}
            return current_person, {
                "mode": "real", "adapter": FASHN_ADAPTER,
                "workflow": SEQUENTIAL_WORKFLOW,
                "steps_completed": total,
                "step_count": total,
                "step_results": step_results,
                "background_removed": background_removed,
            }

    _process_job(job_id, session_factory, storage, supports_real_profile, generate)


def run_mock_job(job_id: str) -> None:
    process_mock_job(job_id)


def run_real_job(job_id: str) -> None:
    process_real_job(job_id)
