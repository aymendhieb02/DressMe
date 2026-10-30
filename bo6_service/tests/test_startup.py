import asyncio
import json

import pytest
from fastapi import FastAPI

from app import main
from app.model_runtime import ModelRuntime


def test_startup_rejects_bundle_checksum_mismatch(tmp_path):
    (tmp_path / "asset.bin").write_bytes(b"tampered")
    (tmp_path / "checksums.json").write_text(json.dumps({
        "asset.bin": {"bytes": 8, "sha256": "0" * 64},
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Model bundle integrity check failed: checksum mismatch: asset.bin"):
        ModelRuntime(tmp_path)


def test_application_startup_constructs_one_runtime(monkeypatch):
    calls = []

    class RuntimeStub:
        def __init__(self, bundle):
            calls.append(bundle)

    monkeypatch.setattr(main, "ModelRuntime", RuntimeStub)
    application = FastAPI()

    async def enter_lifespan():
        async with main.lifespan(application):
            assert isinstance(application.state.runtime, RuntimeStub)

    asyncio.run(enter_lifespan())
    assert calls == [main.BUNDLE_DIR]
