import asyncio

from fastapi.testclient import TestClient


def test_outer_app_enters_studio_lifespan_once_and_shuts_down(monkeypatch):
    import api
    import app.main as studio

    started = asyncio.Event()
    calls = {"storage": 0}
    cleanup_calls = {"expire": 0, "drain": 0}

    def storage():
        calls["storage"] += 1

    monkeypatch.setattr(studio, "LocalPrivateStorage", storage)
    monkeypatch.setattr(studio, "expire_pending_uploads", lambda: cleanup_calls.__setitem__("expire", cleanup_calls["expire"] + 1))
    monkeypatch.setattr(studio, "drain_storage_deletions", lambda: cleanup_calls.__setitem__("drain", cleanup_calls["drain"] + 1))

    async def parked_sleep(_delay):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(studio.asyncio, "sleep", parked_sleep)

    async def exercise():
        async with api.app.router.lifespan_context(api.app):
            await asyncio.wait_for(started.wait(), timeout=1)
            await studio.cleanup_pass()
        names = {task.get_name() for task in asyncio.all_tasks() if task is not asyncio.current_task()}
        assert "dressme-storage-cleanup" not in names

    asyncio.run(exercise())
    assert calls["storage"] == 1
    assert cleanup_calls == {"expire": 1, "drain": 1}


def test_studio_can_still_start_directly(monkeypatch):
    import app.main as studio

    started = asyncio.Event()
    calls = {"storage": 0}
    monkeypatch.setattr(studio, "LocalPrivateStorage", lambda: calls.__setitem__("storage", calls["storage"] + 1))

    async def parked_sleep(_delay):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(studio.asyncio, "sleep", parked_sleep)

    with TestClient(studio.app):
        assert calls["storage"] == 1
    assert started.is_set()


def test_expired_upload_and_deferred_file_intent_are_processed(client, origin, monkeypatch):
    from datetime import timedelta
    from uuid import UUID, uuid4

    from sqlalchemy import select

    from app.models import PendingUpload, StorageDeletion, utcnow
    from app.storage import cleanup

    response = client.post("/auth/register", headers=origin,
                           json={"email": "cleanup-fixture@example.invalid", "password": "correct horse battery staple"})
    assert response.status_code == 201
    user_id = response.json()["user"]["id"]
    factory = client.app.state.testing_session_factory
    key = f"{uuid4().hex}.png"
    with factory() as db:
        db.add(PendingUpload(
            user_id=UUID(user_id), image_key=key, content_type="image/png", image_sha256="a" * 64,
            width=10, height=10, quality_snapshot={}, prediction_snapshot={}, model_version="fixture",
            taxonomy_version="fixture", description_version="fixture", quality_version="fixture",
            expires_at=utcnow() - timedelta(seconds=1), consumed_at=None,
        ))
        db.commit()

    monkeypatch.setattr(cleanup, "SessionLocal", factory)
    assert cleanup.expire_pending_uploads() == 1
    with factory() as db:
        assert db.scalar(select(PendingUpload).where(PendingUpload.image_key == key)) is None
        assert db.scalar(select(StorageDeletion).where(StorageDeletion.image_key == key)) is not None

    deleted = []
    class FixtureStorage:
        def delete(self, image_key):
            deleted.append(image_key)
    assert cleanup.drain_storage_deletions(session_factory=factory, storage_factory=FixtureStorage) == 1
    assert deleted == [key]
    with factory() as db:
        assert db.scalar(select(StorageDeletion).where(StorageDeletion.image_key == key)) is None
