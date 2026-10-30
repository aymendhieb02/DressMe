import asyncio
import hashlib
import io
import json
import re
import zipfile
from datetime import timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.dependencies import current_user, current_user_csrf
from ..config import get_settings
from ..database import get_db
from ..models import Avatar, AvatarConsent, AvatarRender, StorageDeletion, User, utcnow
from ..storage.cleanup import acknowledge_storage_deletion, record_storage_deletion_failure
from ..storage.local_disk import LocalPrivateStorage
from .glb import AvatarAssetError, validate_avatar_glb
from .render_profile import (
    MAX_RENDER_BYTES,
    PROFILE_ID,
    PROFILE_VERSION,
    RENDERER_VERSION,
    profile_settings,
    validate_camera_settings,
    validate_render_png,
)
from .schemas import AvatarConsentRequest, AvatarConsentView, AvatarRenderView, AvatarView


router = APIRouter(prefix="/avatars", tags=["avatars"])
AVATAR_PROVIDER = "avaturn"
CONSENT_VERSION = "avaturn-photo-processing-v1"
PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _consent_view(row: AvatarConsent) -> AvatarConsentView:
    consented_at = row.consented_at
    if consented_at.tzinfo is None:
        consented_at = consented_at.replace(tzinfo=timezone.utc)
    return AvatarConsentView(
        id=row.id, provider=row.provider, consent_version=row.consent_version, consented_at=consented_at,
    )


def _avatar_view(row: Avatar, consent: AvatarConsent | None = None) -> AvatarView:
    consent_version = consent.consent_version if consent else CONSENT_VERSION
    return AvatarView(
        id=row.id,
        provider=row.provider,
        provider_avatar_id=row.provider_avatar_id,
        model_url=f"/avatars/{row.id}/model",
        asset_sha256=row.asset_sha256,
        asset_size=row.asset_size,
        version=row.version,
        consent_version=consent_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _avatar_render_view(row: AvatarRender) -> AvatarRenderView:
    return AvatarRenderView(
        id=row.id,
        avatar_id=row.avatar_id,
        source_avatar_version=row.source_avatar_version,
        source_avatar_sha256=row.source_avatar_sha256,
        profile_id=row.profile_id,
        profile_version=row.profile_version,
        render_settings=row.render_settings,
        image_url=f"/avatars/renders/{row.id}/image",
        image_sha256=row.image_sha256,
        width=row.width,
        height=row.height,
        renderer_version=row.renderer_version,
        created_at=row.created_at,
    )


def _queue_delete(db: Session, key: str) -> None:
    if db.scalar(select(StorageDeletion.id).where(StorageDeletion.image_key == key)) is None:
        db.add(StorageDeletion(image_key=key))


def _drop_avatar_render(db: Session, avatar_id: UUID, *, delete_metadata: bool = True) -> str | None:
    row = db.scalar(select(AvatarRender).where(AvatarRender.avatar_id == avatar_id).with_for_update())
    if row is None:
        return None
    key = row.image_key
    _queue_delete(db, key)
    if delete_metadata:
        db.delete(row)
    return key


async def _delete_new_file(storage: LocalPrivateStorage, key: str) -> None:
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:
        # No database row points to this uncommitted file. The original error
        # remains primary; periodic storage reconciliation handles orphan files.
        return


@router.post("/consents", response_model=AvatarConsentView, status_code=201)
def record_avatar_consent(
    body: AvatarConsentRequest,
    user: User = Depends(current_user_csrf),
    db: Session = Depends(get_db),
):
    if body.accepted is not True:
        raise _error(422, "avatar_consent_required", "Accept the photo-processing disclosure before opening Avaturn.")
    row = AvatarConsent(
        user_id=user.id,
        provider=AVATAR_PROVIDER,
        consent_version=CONSENT_VERSION,
        consented_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _consent_view(row)


@router.get("/current", response_model=AvatarView | None)
def get_current_avatar(user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(Avatar).where(Avatar.user_id == user.id))
    if row is None:
        return None
    consent = db.get(AvatarConsent, row.consent_id)
    return _avatar_view(row, consent)


@router.put("/current", response_model=AvatarView)
async def save_current_avatar(
    model: UploadFile = File(...),
    provider_avatar_id: str = Form(..., min_length=1, max_length=128),
    consent_id: UUID = Form(...),
    consent_version: str = Form(..., min_length=1, max_length=64),
    user: User = Depends(current_user_csrf),
    db: Session = Depends(get_db),
):
    if not PROVIDER_ID_RE.fullmatch(provider_avatar_id):
        raise _error(422, "invalid_provider_avatar_id", "The provider returned an invalid avatar identifier.")
    if consent_version != CONSENT_VERSION:
        raise _error(422, "avatar_consent_version_invalid", "Accept the current Avaturn photo-processing disclosure before saving.")
    if model.content_type not in {"model/gltf-binary", "application/octet-stream"}:
        raise _error(415, "unsupported_avatar_type", "Upload a binary GLB export from Avaturn.")
    data = await model.read(get_settings().max_avatar_bytes + 1)
    try:
        info = validate_avatar_glb(data, get_settings().max_avatar_bytes)
    except AvatarAssetError as exc:
        raise _error(exc.status_code, exc.code, str(exc)) from None
    digest = hashlib.sha256(data).hexdigest()

    owner = db.scalar(select(User).where(User.id == user.id).with_for_update())
    if owner is None:
        raise _error(401, "authentication_required", "A valid session is required.")
    consent = db.scalar(select(AvatarConsent).where(
        AvatarConsent.id == consent_id,
        AvatarConsent.user_id == user.id,
        AvatarConsent.provider == AVATAR_PROVIDER,
        AvatarConsent.consent_version == CONSENT_VERSION,
    ))
    if consent is None:
        raise _error(403, "avatar_consent_missing", "Record your Avaturn consent before saving an avatar.")
    current = db.scalar(select(Avatar).where(Avatar.user_id == user.id).with_for_update())
    if current and current.provider_avatar_id == provider_avatar_id and current.asset_sha256 == digest:
        return _avatar_view(current, db.get(AvatarConsent, current.consent_id))

    storage = LocalPrivateStorage()
    new_key = await asyncio.to_thread(storage.put_avatar, data)
    previous_key = current.asset_key if current else None
    previous_render_key = None
    try:
        previous_render_key = _drop_avatar_render(db, current.id) if current else None
        if current is None:
            current = Avatar(
                user_id=user.id,
                consent_id=consent.id,
                provider=AVATAR_PROVIDER,
                provider_avatar_id=provider_avatar_id,
                asset_key=new_key,
                asset_sha256=digest,
                asset_size=info.size,
                version=1,
            )
            db.add(current)
        else:
            current.consent_id = consent.id
            current.provider = AVATAR_PROVIDER
            current.provider_avatar_id = provider_avatar_id
            current.asset_key = new_key
            current.asset_sha256 = digest
            current.asset_size = info.size
            current.version += 1
            current.updated_at = utcnow()
            if previous_key:
                _queue_delete(db, previous_key)
        db.commit()
        db.refresh(current)
    except IntegrityError:
        db.rollback()
        await _delete_new_file(storage, new_key)
        current = db.scalar(select(Avatar).where(Avatar.user_id == user.id))
        if current and current.provider_avatar_id == provider_avatar_id and current.asset_sha256 == digest:
            return _avatar_view(current, db.get(AvatarConsent, current.consent_id))
        raise _error(409, "avatar_save_conflict", "Another avatar save completed first. Reload the page and try again.") from None
    except Exception:
        db.rollback()
        await _delete_new_file(storage, new_key)
        raise

    if previous_key:
        try:
            await asyncio.to_thread(storage.delete, previous_key)
        except Exception:
            record_storage_deletion_failure(db, previous_key)
        else:
            acknowledge_storage_deletion(db, previous_key)
    if previous_render_key:
        try:
            await asyncio.to_thread(storage.delete, previous_render_key)
        except Exception:
            record_storage_deletion_failure(db, previous_render_key)
        else:
            acknowledge_storage_deletion(db, previous_render_key)
    return _avatar_view(current, consent)


@router.get("/current/render", response_model=AvatarRenderView | None)
def get_current_avatar_render(user: User = Depends(current_user), db: Session = Depends(get_db)):
    avatar = db.scalar(select(Avatar).where(Avatar.user_id == user.id))
    if avatar is None:
        return None
    row = db.scalar(select(AvatarRender).where(
        AvatarRender.user_id == user.id,
        AvatarRender.avatar_id == avatar.id,
        AvatarRender.source_avatar_version == avatar.version,
        AvatarRender.source_avatar_sha256 == avatar.asset_sha256,
    ))
    return _avatar_render_view(row) if row is not None else None


@router.get("/current/render/export")
def export_current_avatar_render(user: User = Depends(current_user), db: Session = Depends(get_db)):
    avatar = db.scalar(select(Avatar).where(Avatar.user_id == user.id))
    if avatar is None:
        raise _error(404, "avatar_render_not_found", "Avatar render not found.")
    row = db.scalar(select(AvatarRender).where(
        AvatarRender.user_id == user.id,
        AvatarRender.avatar_id == avatar.id,
        AvatarRender.source_avatar_version == avatar.version,
        AvatarRender.source_avatar_sha256 == avatar.asset_sha256,
    ))
    if row is None:
        raise _error(404, "avatar_render_not_found", "Avatar render not found.")

    image_data = LocalPrivateStorage().read(row.image_key)
    if hashlib.sha256(image_data).hexdigest() != row.image_sha256:
        raise _error(500, "avatar_render_integrity_failed", "The saved render failed its integrity check.")
    try:
        validate_render_png(image_data)
    except ValueError:
        raise _error(500, "avatar_render_integrity_failed", "The saved render is not a valid profile PNG.") from None

    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    manifest = {
        "schema": "dressme-avatar-render-manifest-v1",
        "render": {
            "id": str(row.id),
            "profile_id": row.profile_id,
            "profile_version": row.profile_version,
            "renderer_version": row.renderer_version,
            "created_at": created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "file": "avatar-render.png",
            "sha256": row.image_sha256,
            "width": row.width,
            "height": row.height,
        },
        "source_avatar": {
            "id": str(row.avatar_id),
            "version": row.source_avatar_version,
            "sha256": row.source_avatar_sha256,
        },
        "settings": row.render_settings,
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("avatar-render.png", image_data)
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False))

    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={
            "Cache-Control": "private, no-store",
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="dressme-avatar-render-{row.id}.zip"',
        },
    )


@router.put("/current/render", response_model=AvatarRenderView)
async def save_current_avatar_render(
    image: UploadFile = File(...),
    source_avatar_id: UUID = Form(...),
    source_avatar_version: int = Form(..., ge=1),
    source_avatar_sha256: str = Form(..., min_length=64, max_length=64),
    camera_settings_json: str = Form(..., max_length=2048),
    user: User = Depends(current_user_csrf),
    db: Session = Depends(get_db),
):
    if image.content_type != "image/png":
        raise _error(415, "unsupported_avatar_render_type", "Upload a PNG image created by the selected avatar render profile.")
    if not re.fullmatch(r"[0-9a-f]{64}", source_avatar_sha256):
        raise _error(422, "invalid_avatar_render_source", "The source avatar digest is invalid.")
    try:
        camera = validate_camera_settings(json.loads(camera_settings_json))
    except (json.JSONDecodeError, ValueError):
        raise _error(422, "invalid_avatar_render_settings", "The camera settings do not match the selected render profile.") from None
    data = await image.read(MAX_RENDER_BYTES + 1)
    try:
        width, height = validate_render_png(data)
    except ValueError as exc:
        raise _error(422, "invalid_avatar_render", str(exc)) from None

    owner = db.scalar(select(User).where(User.id == user.id).with_for_update())
    if owner is None:
        raise _error(401, "authentication_required", "A valid session is required.")
    avatar = db.scalar(select(Avatar).where(Avatar.user_id == user.id).with_for_update())
    if avatar is None or avatar.id != source_avatar_id or avatar.version != source_avatar_version or avatar.asset_sha256 != source_avatar_sha256:
        raise _error(409, "avatar_render_source_changed", "The saved avatar changed during capture. Reload it and create a new render.")

    storage = LocalPrivateStorage()
    image_key = await asyncio.to_thread(storage.put, data)
    previous_key = None
    try:
        previous = db.scalar(select(AvatarRender).where(AvatarRender.avatar_id == avatar.id).with_for_update())
        previous_key = previous.image_key if previous else None
        if previous is not None:
            _queue_delete(db, previous.image_key)
            db.delete(previous)
            db.flush()
        row = AvatarRender(
            user_id=user.id,
            avatar_id=avatar.id,
            source_avatar_version=avatar.version,
            source_avatar_sha256=avatar.asset_sha256,
            profile_id=PROFILE_ID,
            profile_version=PROFILE_VERSION,
            render_settings=profile_settings(camera),
            image_key=image_key,
            image_sha256=hashlib.sha256(data).hexdigest(),
            width=width,
            height=height,
            renderer_version=RENDERER_VERSION,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    except IntegrityError:
        db.rollback()
        await _delete_new_file(storage, image_key)
        raise _error(409, "avatar_render_conflict", "Another render save completed first. Reload the page and try again.") from None
    except Exception:
        db.rollback()
        await _delete_new_file(storage, image_key)
        raise

    if previous_key:
        try:
            await asyncio.to_thread(storage.delete, previous_key)
        except Exception:
            record_storage_deletion_failure(db, previous_key)
        else:
            acknowledge_storage_deletion(db, previous_key)
    return _avatar_render_view(row)


@router.get("/renders/{render_id}/image")
def get_avatar_render_image(render_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(
        select(AvatarRender)
        .join(Avatar, Avatar.id == AvatarRender.avatar_id)
        .where(
            AvatarRender.id == render_id,
            AvatarRender.user_id == user.id,
            Avatar.user_id == user.id,
            Avatar.version == AvatarRender.source_avatar_version,
            Avatar.asset_sha256 == AvatarRender.source_avatar_sha256,
        )
    )
    if row is None:
        raise _error(404, "avatar_render_not_found", "Avatar render not found.")
    data = LocalPrivateStorage().read(row.image_key)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "Vary": "Cookie", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/current/render", status_code=204)
async def delete_current_avatar_render(
    user: User = Depends(current_user_csrf),
    db: Session = Depends(get_db),
):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    avatar = db.scalar(select(Avatar).where(Avatar.user_id == user.id).with_for_update())
    if avatar is None:
        return Response(status_code=204)
    key = _drop_avatar_render(db, avatar.id)
    if key is None:
        return Response(status_code=204)
    db.commit()
    storage = LocalPrivateStorage()
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:
        record_storage_deletion_failure(db, key)
        return Response(status_code=202, content=b'{"status":"deletion_queued"}', media_type="application/json")
    acknowledge_storage_deletion(db, key)
    return Response(status_code=204)


@router.get("/{avatar_id}/model")
def get_avatar_model(avatar_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(Avatar).where(Avatar.id == avatar_id, Avatar.user_id == user.id))
    if row is None:
        raise _error(404, "avatar_not_found", "Avatar not found.")
    data = LocalPrivateStorage().read_avatar(row.asset_key)
    return Response(
        content=data,
        media_type="model/gltf-binary",
        headers={
            "Cache-Control": "private, no-store",
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'inline; filename="avatar.glb"',
            "X-Avatar-Version": str(row.version),
        },
    )


@router.delete("/current", status_code=204)
async def delete_current_avatar(
    user: User = Depends(current_user_csrf),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(Avatar).where(Avatar.user_id == user.id).with_for_update())
    if row is None:
        return Response(status_code=204)
    key = row.asset_key
    render_key = _drop_avatar_render(db, row.id, delete_metadata=False)
    _queue_delete(db, key)
    db.delete(row)
    db.commit()
    storage = LocalPrivateStorage()
    cleanup_pending = False
    for delete_key in (key, render_key):
        if delete_key is None:
            continue
        try:
            await asyncio.to_thread(storage.delete, delete_key)
        except Exception:
            record_storage_deletion_failure(db, delete_key)
            cleanup_pending = True
        else:
            acknowledge_storage_deletion(db, delete_key)
    if cleanup_pending:
        return Response(status_code=202, content=b'{"status":"deletion_queued"}', media_type="application/json")
    return Response(status_code=204)
