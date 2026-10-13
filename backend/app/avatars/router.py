import asyncio
import hashlib
import re
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
from ..models import Avatar, AvatarConsent, StorageDeletion, User, utcnow
from ..storage.cleanup import acknowledge_storage_deletion, record_storage_deletion_failure
from ..storage.local_disk import LocalPrivateStorage
from .glb import AvatarAssetError, validate_avatar_glb
from .schemas import AvatarConsentRequest, AvatarConsentView, AvatarView


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


def _queue_delete(db: Session, key: str) -> None:
    if db.scalar(select(StorageDeletion.id).where(StorageDeletion.image_key == key)) is None:
        db.add(StorageDeletion(image_key=key))


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
    try:
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
    return _avatar_view(current, consent)


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
    _queue_delete(db, key)
    db.delete(row)
    db.commit()
    storage = LocalPrivateStorage()
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:
        record_storage_deletion_failure(db, key)
        return Response(status_code=202, content=b'{"status":"deletion_queued"}', media_type="application/json")
    acknowledge_storage_deletion(db, key)
    return Response(status_code=204)
