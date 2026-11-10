import dataclasses
import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.config import Settings, get_settings
from app.models import TryOnAttempt, TryOnJob, utcnow
from app.storage.local_disk import LocalPrivateStorage
from app.tryon import adapters, worker_tasks
from app.tryon.adapters import FASHN_ADAPTER, FashnResult, choose_backend, fashn_runtime_problem, run_fashn
from app.tryon.worker_tasks import process_real_job
from tests.test_tryon_dispatcher import _create_job

SECRET = "sk-remote-do-not-leak-7f3a9c"
URL = "https://fixed-name.ngrok-free.app"


def _png():
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 80, 180)).save(stream, format="PNG")
    return stream.getvalue()


def _settings(tmp_path=None, **overrides):
    values = dict(
        vton_mode="real", storage_path=tmp_path, vton_runtime_dir="runtime", vton_timeout_seconds=280,
        vton_min_free_vram_mib=3500, vton_min_free_ram_mib=3072, vton_abort_free_ram_mib=460,
        vton_remote_url=URL, vton_remote_api_key=SECRET, vton_backend_force="",
    )
    return SimpleNamespace(**{**values, **overrides})


@pytest.fixture
def capacity(monkeypatch):
    """Local runtime present, plenty of memory. Tests lower the numbers they need."""
    monkeypatch.setattr(adapters, "local_runtime_problem", lambda _settings: None)
    monkeypatch.setattr(adapters, "free_ram_mib", lambda: 8000)
    monkeypatch.setattr(adapters, "free_vram_mib", lambda: 4000)
    monkeypatch.setattr(adapters, "POLL_SECONDS", 0.01)


@pytest.fixture
def backends(monkeypatch, capacity):
    calls = []

    def fake(name):
        def run(*_args, **_kwargs):
            calls.append(name)
            return FashnResult(output_path=Path("result.png"))
        return run

    monkeypatch.setattr(adapters, "_run_local_fashn", fake("local"))
    monkeypatch.setattr(adapters, "_run_remote_fashn", fake("remote"))
    return calls


def _run(tmp_path, settings, **kwargs):
    person, garment = tmp_path / "person.png", tmp_path / "garment.png"
    person.write_bytes(_png())
    garment.write_bytes(_png())
    return run_fashn(person, garment, "tops", "flat-lay", output_dir=tmp_path / "out", settings=settings, **kwargs)


def _answer(monkeypatch, response=None, error=None):
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(adapters.httpx, "post", post)
    return seen


def test_enough_capacity_uses_local_and_never_the_remote(tmp_path, backends):
    result = _run(tmp_path, _settings())
    assert backends == ["local"] and result.details["backend"] == "local"


@pytest.mark.parametrize("ram,vram", [(1000, 4000), (8000, 300), (1000, 300), (8000, None)])
def test_a_shortfall_uses_the_remote_when_configured(tmp_path, backends, monkeypatch, ram, vram):
    monkeypatch.setattr(adapters, "free_ram_mib", lambda: ram)
    monkeypatch.setattr(adapters, "free_vram_mib", lambda: vram)
    result = _run(tmp_path, _settings())
    assert backends == ["remote"] and result.details["backend"] == "remote"


@pytest.mark.parametrize("ram,vram,failure", [(1000, 4000, "insufficient_memory"), (8000, 300, "gpu_busy"), (8000, None, "gpu_unavailable")])
def test_a_shortfall_without_a_remote_keeps_the_existing_failure(tmp_path, backends, monkeypatch, ram, vram, failure):
    monkeypatch.setattr(adapters, "free_ram_mib", lambda: ram)
    monkeypatch.setattr(adapters, "free_vram_mib", lambda: vram)
    result = _run(tmp_path, _settings(vton_remote_url=""))
    assert backends == [] and result.failure == failure


def test_force_local_skips_the_capacity_check(tmp_path, backends, monkeypatch):
    monkeypatch.setattr(adapters, "free_ram_mib", lambda: pytest.fail("force must skip the check"))
    monkeypatch.setattr(adapters, "free_vram_mib", lambda: pytest.fail("force must skip the check"))
    _run(tmp_path, _settings(vton_backend_force="local"))
    assert backends == ["local"]


def test_force_remote_skips_the_capacity_check(tmp_path, backends, monkeypatch):
    monkeypatch.setattr(adapters, "free_ram_mib", lambda: pytest.fail("force must skip the check"))
    monkeypatch.setattr(adapters, "free_vram_mib", lambda: pytest.fail("force must skip the check"))
    _run(tmp_path, _settings(vton_backend_force="remote"))
    assert backends == ["remote"]


def test_force_remote_without_a_url_is_a_typed_failure(tmp_path, backends):
    assert _run(tmp_path, _settings(vton_backend_force="remote", vton_remote_url="")).failure == "remote_unavailable"
    assert backends == []


def test_force_local_without_a_runtime_is_a_typed_failure(tmp_path, backends, monkeypatch):
    monkeypatch.setattr(adapters, "local_runtime_problem", lambda _settings: "the runtime is missing: python")
    assert _run(tmp_path, _settings(vton_backend_force="local")).failure == "runtime_unavailable"
    assert backends == []


def test_a_missing_local_runtime_uses_the_remote(tmp_path, backends, monkeypatch):
    monkeypatch.setattr(adapters, "local_runtime_problem", lambda _settings: "the runtime is missing: python")
    _run(tmp_path, _settings())
    assert backends == ["remote"]


def test_decision_is_logged_with_its_numbers(tmp_path, backends, monkeypatch, capsys):
    monkeypatch.setattr(adapters, "free_ram_mib", lambda: 2599)
    _run(tmp_path, _settings())
    log = capsys.readouterr().err
    assert "backend=remote" in log and "ram=2599/3072MiB" in log and "vram=4000/3500MiB" in log
    _run(tmp_path, _settings(vton_backend_force="local"))
    assert "backend=local: forced" in capsys.readouterr().err


def test_real_gate_accepts_a_remote_only_machine():
    assert fashn_runtime_problem(_settings(vton_runtime_dir="")) is None
    assert fashn_runtime_problem(_settings(vton_runtime_dir="", vton_backend_force="local")) is not None
    assert fashn_runtime_problem(_settings(vton_runtime_dir="", vton_remote_url="")) is not None
    assert "VTON_REMOTE_URL" in fashn_runtime_problem(_settings(vton_remote_url="", vton_backend_force="remote"))


def test_remote_sends_the_contract_and_saves_the_png(tmp_path, capacity, monkeypatch):
    seen = _answer(monkeypatch, httpx.Response(200, content=_png()))
    result = _run(tmp_path, _settings(vton_backend_force="remote"))
    assert result.failure is None and result.output_path == tmp_path / "out" / "output_00.png"
    assert result.output_path.read_bytes() == _png() and result.details["backend"] == "remote"
    assert seen["url"] == URL + "/tryon"
    assert seen["headers"] == {"Authorization": f"Bearer {SECRET}"}
    assert seen["data"] == {"category": "tops", "garment_photo_type": "flat-lay"}
    assert set(seen["files"]) == {"person", "garment"}


def test_remote_timeout_is_the_setting_plus_the_allowance_under_the_job_limit(tmp_path, capacity, monkeypatch):
    seen = _answer(monkeypatch, httpx.Response(200, content=_png()))
    _run(tmp_path, _settings(vton_backend_force="remote", vton_timeout_seconds=100))
    assert seen["timeout"] == 100 + adapters.REMOTE_NETWORK_ALLOWANCE_SECONDS
    _run(tmp_path, _settings(vton_backend_force="remote", vton_timeout_seconds=290))
    assert seen["timeout"] == adapters.REMOTE_MAX_SECONDS < 450


FAILURES = [
    ("refused", dict(error=httpx.ConnectError("refused")), "remote_unavailable"),
    ("timeout", dict(error=httpx.ReadTimeout("slow")), "remote_unavailable"),
    ("unexpected", dict(error=RuntimeError("anything else")), "remote_unavailable"),
    ("tunnel offline", dict(response=httpx.Response(404, headers={"ngrok-error-code": "ERR_NGROK_3200"}, text="offline")), "remote_unavailable"),
    ("401", dict(response=httpx.Response(401, text="no")), "remote_auth_failed"),
    ("500", dict(response=httpx.Response(500, text="boom")), "remote_inference_failed"),
    ("503", dict(response=httpx.Response(503, text="busy")), "remote_busy"),
    ("html", dict(response=httpx.Response(200, text="<html>not an image</html>")), "remote_bad_response"),
    ("truncated", dict(response=httpx.Response(200, content=_png()[:20])), "remote_bad_response"),
    ("jpeg", dict(response=httpx.Response(200, content=b"\xff\xd8\xff\xe0 not png")), "remote_bad_response"),
    ("404", dict(response=httpx.Response(404, text="missing")), "remote_bad_response"),
]


@pytest.mark.parametrize("name,answer,failure", FAILURES, ids=[case[0] for case in FAILURES])
def test_remote_failures_are_typed(tmp_path, capacity, monkeypatch, name, answer, failure):
    _answer(monkeypatch, **answer)
    result = _run(tmp_path, _settings(vton_backend_force="remote"))
    assert result.failure == failure and result.output_path is None
    assert not (tmp_path / "out" / "output_00.png").exists()


def test_401_is_requested_once_with_no_automatic_retry(tmp_path, capacity, monkeypatch):
    calls = []

    def post(*_args, **_kwargs):
        calls.append(1)
        return httpx.Response(401)

    monkeypatch.setattr(adapters.httpx, "post", post)
    assert _run(tmp_path, _settings(vton_backend_force="remote")).failure == "remote_auth_failed"
    assert len(calls) == 1


def test_unreadable_inputs_do_not_raise(tmp_path, capacity, monkeypatch):
    _answer(monkeypatch, httpx.Response(200, content=_png()))
    result = run_fashn(tmp_path / "missing.png", tmp_path / "missing.png", "tops", "flat-lay",
                       output_dir=tmp_path / "out", settings=_settings(vton_backend_force="remote"))
    assert result.failure == "remote_unavailable"


def test_a_failing_cancel_check_does_not_raise(tmp_path, capacity, monkeypatch):
    release = threading.Event()

    def slow(*_args, **_kwargs):
        release.wait(5)
        return httpx.Response(200, content=_png())

    monkeypatch.setattr(adapters.httpx, "post", slow)

    def broken():
        raise RuntimeError(f"database down {SECRET}")

    try:
        assert _run(tmp_path, _settings(vton_backend_force="remote"), should_cancel=broken).failure == "remote_unavailable"
    finally:
        release.set()


def test_cancel_and_heartbeat_keep_working_during_the_call(tmp_path, capacity, monkeypatch):
    release = threading.Event()

    def slow(*_args, **_kwargs):
        release.wait(5)
        return httpx.Response(200, content=_png())

    monkeypatch.setattr(adapters.httpx, "post", slow)
    ticks = []
    try:
        result = _run(tmp_path, _settings(vton_backend_force="remote"), should_cancel=lambda: len(ticks) >= 3, tick=lambda: ticks.append(1))
    finally:
        release.set()
    assert result.failure == "cancelled" and len(ticks) >= 3


def test_a_silent_server_hits_the_deadline(tmp_path, capacity, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(adapters.httpx, "post", lambda *a, **k: release.wait(5))
    monkeypatch.setattr(adapters, "REMOTE_NETWORK_ALLOWANCE_SECONDS", 0)
    try:
        assert _run(tmp_path, _settings(vton_backend_force="remote", vton_timeout_seconds=0.05)).failure == "remote_unavailable"
    finally:
        release.set()


def _real_job(client, origin, monkeypatch, tmp_path):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        job.mode, job.settings_snapshot = "real", {"mode": "real", "adapter": FASHN_ADAPTER}
        db.commit()
    monkeypatch.setattr(worker_tasks, "get_settings", lambda: _settings(tmp_path, vton_backend_force="remote"))
    return job_id, factory


@pytest.mark.parametrize("name,answer,failure", FAILURES, ids=[case[0] for case in FAILURES])
def test_remote_failures_end_the_job_failed_with_their_code(client, origin, monkeypatch, tmp_path, capacity, name, answer, failure):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    _answer(monkeypatch, **answer)
    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path))
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        assert (job.state, job.error_code, job.result_key, job.active_attempt_token) == ("failed", failure, None, None)
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.job_id == job_id))
        assert (attempt.state, attempt.error_code) == ("failed", failure)
    assert not list(tmp_path.glob(".vton-*"))


def test_remote_success_stores_a_private_result(client, origin, monkeypatch, tmp_path, capacity):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    _answer(monkeypatch, httpx.Response(200, content=_png()))
    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path))
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        assert job.state == "succeeded" and job.result_metadata["backend"] == "remote"
        assert LocalPrivateStorage(tmp_path).read(job.result_key) == _png()


def test_cancel_during_a_remote_call_cancels_the_job(client, origin, monkeypatch, tmp_path, capacity):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    release = threading.Event()

    def slow(*_args, **_kwargs):
        with factory() as db:
            db.get(TryOnJob, job_id).cancellation_requested_at = utcnow()
            db.commit()
        release.wait(5)
        return httpx.Response(200, content=_png())

    monkeypatch.setattr(adapters.httpx, "post", slow)
    try:
        process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path))
    finally:
        release.set()
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        assert (job.state, job.result_key) == ("cancelled", None)


LEAKS = [
    dict(error=httpx.ConnectError(f"cannot reach Bearer {SECRET}")),
    dict(error=RuntimeError(f"Authorization: Bearer {SECRET}")),
    dict(response=httpx.Response(401, text=f"bad key {SECRET}")),
    dict(response=httpx.Response(500, text=f"trace with {SECRET}")),
    dict(response=httpx.Response(200, text=f"echo {SECRET}")),
]


@pytest.mark.parametrize("answer", LEAKS, ids=["transport", "unexpected", "401", "500", "body"])
def test_the_api_key_never_reaches_logs_or_stored_errors(client, origin, monkeypatch, tmp_path, capacity, capsys, answer):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    _answer(monkeypatch, **answer)
    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path))
    captured = capsys.readouterr()
    assert SECRET not in captured.out and SECRET not in captured.err
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.job_id == job_id))
        stored = json.dumps([job.error_code, job.result_metadata, job.settings_snapshot, job.input_snapshot, attempt.error_code], default=str)
    assert job.state == "failed" and SECRET not in stored


def test_the_api_key_is_not_in_printed_settings_or_the_child_environment(monkeypatch):
    settings = dataclasses.replace(get_settings(), vton_remote_api_key=SECRET)
    assert SECRET not in repr(settings) and SECRET not in str(settings)
    monkeypatch.setenv("VTON_REMOTE_API_KEY", SECRET)
    assert SECRET not in json.dumps(adapters._child_environment())


@pytest.mark.parametrize("field,value,message", [
    ("vton_backend_force", "cloud", "VTON_BACKEND_FORCE"),
    ("vton_remote_url", "http://example.com", "VTON_REMOTE_URL"),
    ("vton_remote_url", "ftp://example.com", "VTON_REMOTE_URL"),
])
def test_settings_reject_invalid_remote_values(field, value, message):
    with pytest.raises(ValueError, match=message):
        dataclasses.replace(get_settings(), **{field: value})


def test_settings_accept_https_and_loopback():
    for url in (URL, "http://127.0.0.1:9000", "http://localhost:9000"):
        assert isinstance(dataclasses.replace(get_settings(), vton_remote_url=url), Settings)


def test_large_photos_are_shrunk_below_the_server_limit(tmp_path):
    noise = Image.effect_noise((2400, 3600), 90).convert("RGB")
    source = tmp_path / "large.png"
    noise.save(source)
    assert source.stat().st_size > 10 * 1024 * 1024

    sent = adapters._upload_png(source)

    assert len(sent) < 10 * 1024 * 1024
    with Image.open(io.BytesIO(sent)) as image:
        assert image.format == "PNG"
        assert max(image.size) == adapters.REMOTE_MAX_IMAGE_SIDE
        assert image.size[1] / image.size[0] == pytest.approx(1.5, abs=0.01)


def test_small_photos_keep_their_size(tmp_path):
    source = tmp_path / "small.png"
    source.write_bytes(_png())
    with Image.open(io.BytesIO(adapters._upload_png(source))) as image:
        assert image.size == (8, 8)
