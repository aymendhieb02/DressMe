import dataclasses
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import TryOnAttempt, TryOnJob, utcnow
from app.storage.local_disk import LocalPrivateStorage
from app.tryon import adapters, dispatcher, router as tryon, worker, worker_tasks
from app.tryon.adapters import FASHN_ADAPTER, FashnResult, FashnRuntime, delivery_task, run_fashn
from app.tryon.worker_tasks import process_mock_job, process_real_job
from tests.test_tryon import _setup_inputs, _upload_person
from tests.test_tryon_dispatcher import CapturingQueue, _create_job

REAL = {"mode": "real", "adapter": FASHN_ADAPTER}
OK_BODY = """
    png = Path(args["--output-dir"]) / "output_00.png"
    png.write_bytes(b"\\x89PNG fake")
    Path(args["--result-json"]).write_text(json.dumps({
        "status": "ok", "outputs": [{"path": str(png)}], "inference_seconds": 1.5,
        "torch_peak_vram_mb": 2784.2, "device": "cuda", "dtype": "torch.bfloat16", "params": {"seed": 42},
    }))
"""


def _runtime(tmp_path, monkeypatch, body):
    script = tmp_path / "fashn_infer.py"
    script.write_text("import json, os, subprocess, sys, time\nfrom pathlib import Path\n"
                      "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))\n" + textwrap.dedent(body), encoding="utf-8")
    runtime = FashnRuntime(Path(sys.executable), script, tmp_path, script)
    monkeypatch.setattr(adapters, "fashn_runtime", lambda _root: runtime)
    monkeypatch.setattr(adapters, "free_vram_mib", lambda: 4000)
    monkeypatch.setattr(adapters, "free_ram_mib", lambda: 8000)
    monkeypatch.setattr(adapters, "POLL_SECONDS", 0.05)
    return SimpleNamespace(vton_runtime_dir="runtime", vton_timeout_seconds=30, vton_min_free_vram_mib=3500,
                           vton_min_free_ram_mib=2048, vton_abort_free_ram_mib=460)


def _run(tmp_path, settings, **kwargs):
    return run_fashn(tmp_path / "p.png", tmp_path / "g.png", "tops", "flat-lay",
                     output_dir=tmp_path / "out", settings=settings, **kwargs)


def _alive(pid):
    listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in listing


def test_adapter_returns_the_png_and_run_details(tmp_path, monkeypatch):
    result = _run(tmp_path, _runtime(tmp_path, monkeypatch, OK_BODY))
    assert result.failure is None and result.output_path.read_bytes().startswith(b"\x89PNG")
    assert result.details["inference_seconds"] == 1.5 and result.details["device"] == "cuda"


def test_adapter_passes_the_proven_arguments(tmp_path, monkeypatch):
    settings = _runtime(tmp_path, monkeypatch, 'Path(args["--result-json"]).write_text(json.dumps({"status": "ok", "outputs": []}))\n'
                                               'Path(args["--output-dir"], "args.json").write_text(json.dumps(args))\n')
    _run(tmp_path, settings)
    seen = json.loads((tmp_path / "out" / "args.json").read_text())
    assert (seen["--device"], seen["--preset"], seen["--category"], seen["--garment-photo-type"]) == ("cuda:0", "preview", "tops", "flat-lay")
    assert "--no-segmentation-free" not in seen and "--skip-verify" not in seen


@pytest.mark.parametrize("code,failure", [(2, "invalid_input"), (3, "weights_invalid"), (4, "gpu_out_of_memory"),
                                          (5, "inference_failed"), (1, "inference_crashed"), (7, "inference_crashed")])
def test_exit_codes_become_typed_failures(tmp_path, monkeypatch, code, failure):
    settings = _runtime(tmp_path, monkeypatch, f"sys.exit({code})\n")
    result = _run(tmp_path, settings)
    assert result.failure == failure and result.output_path is None


def test_a_success_without_a_real_output_is_a_failure(tmp_path, monkeypatch):
    settings = _runtime(tmp_path, monkeypatch, 'Path(args["--result-json"]).write_text(json.dumps({"status": "ok", "outputs": [{"path": "missing.png"}]}))\n')
    assert _run(tmp_path, settings).failure == "inference_failed"


def test_busy_gpu_stops_before_any_process_starts(tmp_path, monkeypatch):
    settings = _runtime(tmp_path, monkeypatch, "pytest_must_not_run\n")
    monkeypatch.setattr(adapters, "free_vram_mib", lambda: 312)
    monkeypatch.setattr(adapters.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start"))
    result = _run(tmp_path, settings)
    assert result.failure == "gpu_busy" and result.details == {"free_vram_mib": 312}


def test_missing_gpu_and_low_ram_are_typed(tmp_path, monkeypatch):
    settings = _runtime(tmp_path, monkeypatch, "pass\n")
    monkeypatch.setattr(adapters.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start"))
    monkeypatch.setattr(adapters, "free_ram_mib", lambda: 900)
    assert _run(tmp_path, settings).failure == "insufficient_memory"
    monkeypatch.setattr(adapters, "free_vram_mib", lambda: None)
    assert _run(tmp_path, settings).failure == "gpu_unavailable"


def test_bad_arguments_and_missing_runtime_are_typed():
    settings = SimpleNamespace(vton_runtime_dir="")
    assert run_fashn("p", "g", "hats", "flat-lay", output_dir="o", settings=settings).failure == "invalid_input"
    assert run_fashn("p", "g", "tops", "product", output_dir="o", settings=settings).failure == "invalid_input"
    assert run_fashn("p", "g", "tops", "model", output_dir="o", settings=settings).failure == "runtime_unavailable"


def test_child_does_not_inherit_application_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "must-stay-in-the-app")
    settings = _runtime(tmp_path, monkeypatch, 'Path(args["--output-dir"], "env.json").write_text(json.dumps(dict(os.environ)))\n')
    _run(tmp_path, settings)
    environment = json.loads((tmp_path / "out" / "env.json").read_text())
    assert "JWT_SECRET" not in environment and environment["HF_HUB_OFFLINE"] == "1"


HANG = """
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(args["--output-dir"], "grandchild.pid").write_text(str(child.pid))
    time.sleep(60)
"""


def _wait_for_grandchild(tmp_path):
    pid_path = tmp_path / "out" / "grandchild.pid"
    for _ in range(200):
        if pid_path.exists() and pid_path.read_text():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(os.name != "nt", reason="the launcher tree is a Windows venv behaviour")
def test_cancel_kills_the_whole_process_tree(tmp_path, monkeypatch):
    settings = _runtime(tmp_path, monkeypatch, HANG)
    result = _run(tmp_path, settings, should_cancel=lambda: _wait_for_grandchild(tmp_path))
    assert result.failure == "cancelled"
    assert not _alive(int((tmp_path / "out" / "grandchild.pid").read_text()))


def test_timeout_stops_a_hung_child(tmp_path, monkeypatch):
    settings = _runtime(tmp_path, monkeypatch, HANG)
    settings.vton_timeout_seconds = 1.5
    started = time.monotonic()
    assert _run(tmp_path, settings).failure == "inference_timeout"
    assert time.monotonic() - started < 20


def test_ram_guard_stops_a_running_child(tmp_path, monkeypatch):
    settings = _runtime(tmp_path, monkeypatch, "time.sleep(60)\n")
    readings = iter([8000] + [300] * 20)
    monkeypatch.setattr(adapters, "free_ram_mib", lambda: next(readings))
    assert _run(tmp_path, settings).failure == "insufficient_memory"


def test_ticks_run_during_inference(tmp_path, monkeypatch):
    settings = _runtime(tmp_path, monkeypatch, "time.sleep(0.5)\n" + OK_BODY)
    ticks = []
    _run(tmp_path, settings, tick=lambda: ticks.append(1))
    assert ticks


def test_delivery_task_selects_by_persisted_profile():
    assert delivery_task("real", REAL).endswith("run_real_job")
    assert delivery_task("mock", {"mode": "mock", "adapter": "mock-preview-v1"}).endswith("run_mock_job")
    for mode, settings in (("real", {"mode": "real", "adapter": "other"}), ("mock", REAL), ("real", {"mode": "mock", "adapter": FASHN_ADAPTER}), ("real", None)):
        assert delivery_task(mode, settings) is None


def _real_job(client, origin, monkeypatch, tmp_path):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        job.mode, job.settings_snapshot = "real", REAL
        db.commit()
    monkeypatch.setattr(worker_tasks, "get_settings", lambda: SimpleNamespace(vton_mode="real", storage_path=tmp_path))
    return job_id, factory


def _success(person, garment, category, photo_type, *, output_dir, settings, should_cancel, tick):
    assert Path(person).read_bytes() and Path(garment).read_bytes()
    assert Path(person).parent.parent == Path(settings.storage_path).resolve()
    output_dir.mkdir(parents=True)
    path = output_dir / "output_00.png"
    path.write_bytes(b"\x89PNG real result")
    return FashnResult(output_path=path, details={"category_seen": category, "photo_seen": photo_type, "inference_seconds": 2.0})


def test_real_job_stores_a_private_result_with_metadata(client, origin, monkeypatch, tmp_path):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path), runner=_success)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        assert job.state == "succeeded" and job.active_attempt_token is None
        assert LocalPrivateStorage(tmp_path).read(job.result_key).startswith(b"\x89PNG real")
        assert job.result_metadata["mode"] == "real" and job.result_metadata["adapter"] == FASHN_ADAPTER
        assert job.result_metadata["category_seen"] == "tops" and job.result_metadata["photo_seen"] == "flat-lay"
        assert db.scalar(select(TryOnAttempt).where(TryOnAttempt.job_id == job_id)).state == "succeeded"
    assert not list(tmp_path.glob(".vton-*"))


def test_duplicate_delivery_runs_the_model_once(client, origin, monkeypatch, tmp_path):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return _success(*args, **kwargs)

    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path), runner=counted)
    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path), runner=counted)
    assert len(calls) == 1


def test_real_failure_is_recorded_with_its_type(client, origin, monkeypatch, tmp_path):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path), runner=lambda *a, **k: FashnResult(failure="gpu_busy"))
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        assert (job.state, job.error_code, job.result_key) == ("failed", "gpu_busy", None)
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.job_id == job_id))
        assert (attempt.state, attempt.error_code) == ("failed", "gpu_busy")


def test_cancel_during_inference_stops_the_job_and_keeps_no_result(client, origin, monkeypatch, tmp_path):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)

    def runner(*_args, should_cancel, **_kwargs):
        assert should_cancel() is False
        with factory() as db:
            db.get(TryOnJob, job_id).cancellation_requested_at = utcnow()
            db.commit()
        assert should_cancel() is True
        return FashnResult(failure="cancelled")

    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path), runner=runner)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        assert (job.state, job.result_key, job.active_attempt_token) == ("cancelled", None, None)
        assert db.scalar(select(TryOnAttempt).where(TryOnAttempt.job_id == job_id)).state == "cancelled"


def test_cancel_arriving_just_after_inference_discards_the_result(client, origin, monkeypatch, tmp_path):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    before = set(tmp_path.glob("*.png"))

    def runner(*args, **kwargs):
        with factory() as db:
            db.get(TryOnJob, job_id).cancellation_requested_at = utcnow()
            db.commit()
        return _success(*args, **kwargs)

    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path), runner=runner)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        assert job.state == "cancelled" and job.result_key is None
    assert set(tmp_path.glob("*.png")) == before


def test_changed_input_ownership_never_reaches_the_model(client, origin, monkeypatch, tmp_path):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        snapshot = dict(job.input_snapshot)
        snapshot["garment_image_key"] = "0" * 32 + ".png"
        job.input_snapshot = snapshot
        db.commit()
    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path), runner=lambda *a, **k: pytest.fail("must not run"))
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        assert (job.state, job.error_code) == ("failed", "input_unavailable")


def test_a_mock_worker_refuses_real_jobs(client, origin, monkeypatch, tmp_path):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    monkeypatch.setattr(worker_tasks, "get_settings", lambda: SimpleNamespace(vton_mode="mock", storage_path=tmp_path))
    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path), runner=lambda *a, **k: pytest.fail("must not run"))
    with factory() as db:
        assert db.get(TryOnJob, job_id).error_code == "real_vton_unavailable"


def test_real_task_refuses_a_mock_job(client, origin, monkeypatch, tmp_path):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    process_real_job(str(job_id), factory, LocalPrivateStorage(tmp_path), runner=lambda *a, **k: pytest.fail("must not run"))
    with factory() as db:
        assert db.get(TryOnJob, job_id).error_code == "unsupported_vton_adapter"


def test_mock_task_refuses_a_real_job(client, origin, monkeypatch, tmp_path):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    process_mock_job(str(job_id), factory, LocalPrivateStorage(tmp_path))
    with factory() as db:
        assert db.get(TryOnJob, job_id).error_code == "unsupported_vton_adapter"


def test_dispatcher_routes_real_jobs_to_the_real_task(client, origin, monkeypatch, tmp_path):
    job_id, factory = _real_job(client, origin, monkeypatch, tmp_path)
    queue = CapturingQueue()
    assert dispatcher.dispatch_pending(queue, factory) == 1
    assert queue.calls[0][0][0] == "app.tryon.worker_tasks.run_real_job"
    assert queue.calls[0][1]["job_timeout"] == 450


def test_router_creates_a_real_job_when_real_mode_is_ready(client, origin, monkeypatch, tmp_path):
    headers, garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers).json()
    monkeypatch.setattr(tryon, "get_settings", lambda: dataclasses.replace(get_settings(), vton_mode="real"))
    monkeypatch.setattr(tryon, "fashn_runtime_problem", lambda _settings: None)
    response = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": "real-mode-ready-01"},
                           json={"garment_id": garment["id"], "person_photo_id": photo["id"]})
    assert response.status_code == 202, response.text
    assert response.json()["mode"] == "real" and response.json()["settings_snapshot"] == REAL


def test_router_still_refuses_real_mode_without_a_runtime(client, origin, monkeypatch, tmp_path):
    headers, garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers).json()
    monkeypatch.setattr(tryon, "get_settings", lambda: dataclasses.replace(get_settings(), vton_mode="real", vton_runtime_dir="", vton_remote_url=""))
    response = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": "real-mode-absent-01"},
                           json={"garment_id": garment["id"], "person_photo_id": photo["id"]})
    assert response.status_code == 503 and response.json()["error"]["code"] == "real_vton_unavailable"


def _fake_worker_stack(monkeypatch, platform):
    created = []

    class FakeWorker:
        def __init__(self, queues, **kwargs):
            created.append((type(self).__name__, kwargs))

        def heartbeat(self):
            pass

        def work(self, **_kwargs):
            pass

    class SimpleWorker(FakeWorker):
        pass

    class Worker(FakeWorker):
        pass

    broker = SimpleNamespace(ping=lambda: True, close=lambda: None)
    monkeypatch.setattr(worker, "SimpleWorker", SimpleWorker)
    monkeypatch.setattr(worker, "Worker", Worker)
    monkeypatch.setattr(worker, "Queue", lambda *a, **k: object())
    monkeypatch.setattr(worker.Redis, "from_url", lambda *a, **k: broker)
    monkeypatch.setattr(worker, "os", SimpleNamespace(name=platform))
    monkeypatch.setattr(worker, "fashn_runtime_problem", lambda _settings: None)
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(
        vton_mode="real", environment="production", redis_url="redis://x", tryon_queue_name="q"))
    return created


def test_real_worker_uses_the_in_process_class_only_on_windows(monkeypatch, capsys):
    created = _fake_worker_stack(monkeypatch, "nt")
    beats = []
    monkeypatch.setattr(worker, "set_heartbeat", beats.append)
    worker.run_worker()
    assert created[0][0] == "SimpleWorker" and len(beats) == 1
    assert "own child process" in capsys.readouterr().err


def test_real_worker_keeps_the_forking_class_on_linux(monkeypatch):
    created = _fake_worker_stack(monkeypatch, "posix")
    monkeypatch.setattr(worker, "set_heartbeat", lambda _beat: pytest.fail("the forking worker beats on its own"))
    worker.run_worker()
    assert created[0][0] == "Worker"


def test_real_worker_refuses_to_start_without_a_runtime(monkeypatch):
    _fake_worker_stack(monkeypatch, "nt")
    monkeypatch.setattr(worker, "fashn_runtime_problem", lambda _settings: "VTON_RUNTIME_DIR is not set")
    monkeypatch.setattr(worker.Redis, "from_url", lambda *a, **k: pytest.fail("must fail before broker access"))
    with pytest.raises(RuntimeError, match="no mock result was substituted"):
        worker.run_worker()


def test_heartbeat_is_rate_limited_and_never_fails_the_job(monkeypatch):
    beats = []

    def beat():
        beats.append(1)
        raise ConnectionError("redis blinked")

    monkeypatch.setattr(worker_tasks, "_last_heartbeat", 0.0)
    worker_tasks.set_heartbeat(beat)
    try:
        worker_tasks._beat()
        worker_tasks._beat()
    finally:
        worker_tasks.set_heartbeat(None)
    assert len(beats) == 1


def test_readiness_reports_real_only_when_it_can_run(client, monkeypatch):
    from app import main
    assert client.get("/health/ready").json()["real_vton_ready"] is False
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, vton_mode="real"))
    monkeypatch.setattr(main, "fashn_runtime_problem", lambda _settings: None)
    assert client.get("/health/ready").json()["real_vton_ready"] is True
