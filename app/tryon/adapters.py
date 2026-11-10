"""Persisted adapter contract shared by dispatch and worker delivery, and the real FASHN adapter.

Real inference runs in a child process, one per job, using the separate runtime named by
VTON_RUNTIME_DIR. On Windows RQ cannot fork, so a worker would otherwise run the job inside
its own process: a CUDA crash would kill the worker, no heartbeat would be sent, and a
blocked native call could not be timed out. The child restores that isolation. The polling
loop in run_fashn stays in Python, so timeout, cancellation and heartbeats keep working, and
ending the child releases all VRAM on small GPUs.

Each job picks a backend at run time: local when RAM and VRAM allow it, otherwise the remote
server when one is configured. Both backends return the same FashnResult.
"""

import ctypes
import io
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image


MOCK_ADAPTER = "mock-preview-v1"
FASHN_ADAPTER = "fashn-vton-1.5-v1"
UNSUPPORTED_ADAPTER = "unsupported_vton_adapter"
MOCK_TASK = "app.tryon.worker_tasks.run_mock_job"
REAL_TASK = "app.tryon.worker_tasks.run_real_job"

CATEGORIES = frozenset({"tops", "bottoms", "one-pieces"})
PHOTO_TYPES = frozenset({"model", "flat-lay"})
EXIT_FAILURES = {2: "invalid_input", 3: "weights_invalid", 4: "gpu_out_of_memory", 5: "inference_failed"}
POLL_SECONDS = 2.0
# A remote call gets VTON_TIMEOUT_SECONDS plus this allowance for upload, download and tunnel latency.
# A remote image measured up to 292 s on Kaggle, so a call gets more time than a local run.
REMOTE_NETWORK_ALLOWANCE_SECONDS = 135
# The total must end before RQ's 450 s job_timeout and the 480 s dispatcher lease, or a slow call is retried.
REMOTE_MAX_SECONDS = 420
REMOTE_MAX_IMAGE_SIDE = 1536
CHILD_ENVIRONMENT = (
    "COMSPEC", "LOCALAPPDATA", "NUMBER_OF_PROCESSORS", "PATH", "PATHEXT", "PROCESSOR_ARCHITECTURE",
    "PROGRAMDATA", "PROGRAMFILES", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "WINDIR",
)


def supports_mock_profile(mode: str, settings: object) -> bool:
    """Only an explicitly selected mock profile may enter the mock adapter."""
    return (
        mode == "mock"
        and isinstance(settings, Mapping)
        and settings.get("mode") == "mock"
        and settings.get("adapter") == MOCK_ADAPTER
    )


def supports_real_profile(mode: str, settings: object) -> bool:
    """Only an explicitly selected real profile may enter the FASHN adapter."""
    return (
        mode == "real"
        and isinstance(settings, Mapping)
        and settings.get("mode") == "real"
        and settings.get("adapter") == FASHN_ADAPTER
    )


def delivery_task(mode: str, settings: object) -> str | None:
    """The queue task for a persisted profile, or None when it must not be delivered."""
    if supports_mock_profile(mode, settings):
        return MOCK_TASK
    if supports_real_profile(mode, settings):
        return REAL_TASK
    return None


@dataclass(frozen=True)
class FashnRuntime:
    python: Path
    script: Path
    weights: Path
    manifest: Path


@dataclass(frozen=True)
class FashnResult:
    """A result PNG path, or a typed failure code. Never both."""

    output_path: Path | None = None
    failure: str | None = None
    details: dict = field(default_factory=dict)


def fashn_runtime(root: str | Path) -> FashnRuntime:
    root = Path(root)
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return FashnRuntime(python, root / "package/fashn_infer.py", root / "weights", root / "package/weights_manifest.json")


def fashn_runtime_problem(settings: object) -> str | None:
    """Why real try-on cannot run at all, or None. A configured remote server is enough."""
    force = getattr(settings, "vton_backend_force", "")
    if getattr(settings, "vton_remote_url", "") and force != "local":
        return None
    if force == "remote":
        return "VTON_REMOTE_URL is not set"
    return local_runtime_problem(settings)


def local_runtime_problem(settings: object) -> str | None:
    """Why local inference cannot start on this machine, or None."""
    root = getattr(settings, "vton_runtime_dir", "")
    if not root:
        return "VTON_RUNTIME_DIR is not set"
    runtime = fashn_runtime(root)
    missing = [name for name, path in vars(runtime).items() if not path.exists()]
    return f"the runtime is missing: {', '.join(missing)}" if missing else None


def free_vram_mib() -> int | None:
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
        return int(output.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def free_ram_mib() -> int | None:
    if os.name != "nt":
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in ("total", "available", "page_total", "page_free", "virtual_total", "virtual_free", "extended")
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.available // (1024 * 1024)


def _child_environment() -> dict[str, str]:
    """The child gets system paths only, never the application's secrets."""
    environment = {key: os.environ[key] for key in CHILD_ENVIRONMENT if key in os.environ}
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONIOENCODING="utf-8")
    return environment


def _stop_process_tree(process: subprocess.Popen) -> None:
    """A venv python.exe is a launcher with a child, so killing the handle alone would leave the GPU process."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30, check=False)
    else:
        process.kill()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()


def _read_result(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _log_failure(code: str, stderr_path: Path) -> None:
    try:
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-600:]
    except OSError:
        tail = ""
    print(f"[fashn] {code}: {tail}", file=sys.stderr, flush=True)


@dataclass(frozen=True)
class BackendChoice:
    """Where a job runs and why. failure is set when it cannot run anywhere."""

    backend: str | None
    reason: str
    failure: FashnResult | None = None


def choose_backend(settings: object) -> BackendChoice:
    """Decide per job. Without a remote server, shortfalls keep their existing failure codes."""
    force = getattr(settings, "vton_backend_force", "")
    remote = bool(getattr(settings, "vton_remote_url", ""))
    if force == "remote":
        if remote:
            return BackendChoice("remote", "forced by VTON_BACKEND_FORCE")
        return BackendChoice(None, "forced remote, but VTON_REMOTE_URL is not set", FashnResult(failure="remote_unavailable"))

    runtime_problem = local_runtime_problem(settings)
    if force == "local":
        if runtime_problem:
            return BackendChoice(None, f"forced local, but {runtime_problem}", FashnResult(failure="runtime_unavailable"))
        return BackendChoice("local", "forced by VTON_BACKEND_FORCE")
    if runtime_problem:
        if remote:
            return BackendChoice("remote", f"local unavailable: {runtime_problem}")
        return BackendChoice(None, runtime_problem, FashnResult(failure="runtime_unavailable"))

    free_vram, free_ram = free_vram_mib(), free_ram_mib()
    numbers = (f"ram={free_ram}/{settings.vton_min_free_ram_mib}MiB "
               f"vram={free_vram}/{settings.vton_min_free_vram_mib}MiB")
    if free_vram is None:
        shortfall = FashnResult(failure="gpu_unavailable")
    elif free_vram < settings.vton_min_free_vram_mib:
        shortfall = FashnResult(failure="gpu_busy", details={"free_vram_mib": free_vram})
    elif free_ram is not None and free_ram < settings.vton_min_free_ram_mib:
        shortfall = FashnResult(failure="insufficient_memory", details={"free_ram_mib": free_ram})
    else:
        return BackendChoice("local", f"capacity ok {numbers}")
    if remote:
        return BackendChoice("remote", f"capacity short {numbers}")
    return BackendChoice(None, f"capacity short {numbers}, no remote configured", shortfall)


def run_fashn(
    person_image_path: str | Path,
    garment_image_path: str | Path,
    category: str,
    garment_photo_type: str,
    *,
    output_dir: str | Path,
    settings: object,
    should_cancel: Callable[[], bool] = lambda: False,
    tick: Callable[[], None] = lambda: None,
) -> FashnResult:
    """Generate one try-on image. Returns the PNG path or a typed failure; it does not raise for job failures."""
    if category not in CATEGORIES or garment_photo_type not in PHOTO_TYPES:
        return FashnResult(failure="invalid_input")
    choice = choose_backend(settings)
    print(f"[fashn] backend={choice.backend or 'none'}: {choice.reason}", file=sys.stderr, flush=True)
    if choice.failure is not None:
        return choice.failure
    backend = _run_remote_fashn if choice.backend == "remote" else _run_local_fashn
    result = backend(person_image_path, garment_image_path, category, garment_photo_type,
                     output_dir=output_dir, settings=settings, should_cancel=should_cancel, tick=tick)
    result.details["backend"] = choice.backend
    return result


def _run_local_fashn(
    person_image_path: str | Path,
    garment_image_path: str | Path,
    category: str,
    garment_photo_type: str,
    *,
    output_dir: str | Path,
    settings: object,
    should_cancel: Callable[[], bool],
    tick: Callable[[], None],
) -> FashnResult:
    """Run the local child process. The caller has already checked capacity."""
    runtime = fashn_runtime(settings.vton_runtime_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path, stdout_path, stderr_path = (output_dir / name for name in ("result.json", "stdout.log", "stderr.log"))
    command = [
        str(runtime.python), str(runtime.script), "--weights-dir", str(runtime.weights), "--manifest", str(runtime.manifest),
        "--device", "cuda:0", "--person", str(person_image_path), "--garment", str(garment_image_path),
        "--category", category, "--garment-photo-type", garment_photo_type, "--preset", "preview",
        "--output-dir", str(output_dir), "--result-json", str(result_path),
    ]
    deadline = time.monotonic() + settings.vton_timeout_seconds
    started = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(command, cwd=runtime.script.parent, env=_child_environment(), stdout=stdout, stderr=stderr)
        try:
            while process.poll() is None:
                time.sleep(POLL_SECONDS)
                tick()
                if should_cancel():
                    return FashnResult(failure="cancelled")
                if time.monotonic() > deadline:
                    _log_failure("inference_timeout", stderr_path)
                    return FashnResult(failure="inference_timeout")
                free_ram = free_ram_mib()
                if free_ram is not None and free_ram < settings.vton_abort_free_ram_mib:
                    return FashnResult(failure="insufficient_memory", details={"free_ram_mib": free_ram})
        finally:
            _stop_process_tree(process)

    result = _read_result(result_path)
    details = {key: result[key] for key in ("inference_seconds", "torch_peak_vram_mb", "device", "dtype", "params") if key in result}
    details["wall_seconds"] = round(time.monotonic() - started, 1)
    if process.returncode != 0 or result.get("status") != "ok":
        code = EXIT_FAILURES.get(process.returncode, "inference_crashed")
        _log_failure(code, stderr_path)
        return FashnResult(failure=code, details=details)
    outputs = result.get("outputs") or []
    output_path = Path(outputs[0]["path"]) if outputs else None
    if output_path is None or not output_path.is_file():
        _log_failure("inference_failed", stderr_path)
        return FashnResult(failure="inference_failed", details=details)
    return FashnResult(output_path=output_path, details=details)


def _remote_failure(code: str, started: float, status: int | None = None) -> FashnResult:
    print(f"[fashn] {code}: status={status}", file=sys.stderr, flush=True)
    return FashnResult(failure=code, details={"wall_seconds": round(time.monotonic() - started, 1), "remote_status": status})


def _upload_png(path: str | Path) -> bytes:
    """FASHN works at 576x768, so a full-size photo only slows the upload and can pass the server's 10 MiB limit."""
    with Image.open(path) as source:
        image = source.convert("RGB")
    image.thumbnail((REMOTE_MAX_IMAGE_SIDE, REMOTE_MAX_IMAGE_SIDE))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _is_png(content: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            return image.format == "PNG"
    except Exception:
        return False


def _remote_result(response: httpx.Response, output_dir: Path, started: float) -> FashnResult:
    status = response.status_code
    if response.headers.get("ngrok-error-code"):  # the tunnel answered, not the server behind it
        return _remote_failure("remote_unavailable", started, status)
    if status == 401:
        return _remote_failure("remote_auth_failed", started, status)
    if status == 503:  # the server takes one image at a time, or is not ready yet
        return _remote_failure("remote_busy", started, status)
    if status >= 500:
        return _remote_failure("remote_inference_failed", started, status)
    if status != 200 or not _is_png(response.content):
        return _remote_failure("remote_bad_response", started, status)
    output_path = output_dir / "output_00.png"
    output_path.write_bytes(response.content)
    return FashnResult(output_path=output_path, details={"wall_seconds": round(time.monotonic() - started, 1), "remote_status": status})


def _run_remote_fashn(
    person_image_path: str | Path,
    garment_image_path: str | Path,
    category: str,
    garment_photo_type: str,
    *,
    output_dir: str | Path,
    settings: object,
    should_cancel: Callable[[], bool],
    tick: Callable[[], None],
) -> FashnResult:
    """Same contract as the local path. Only exception type names are logged: messages could carry the key."""
    started = time.monotonic()
    try:
        limit = min(settings.vton_timeout_seconds + REMOTE_NETWORK_ALLOWANCE_SECONDS, REMOTE_MAX_SECONDS)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "person": ("person.png", _upload_png(person_image_path), "image/png"),
            "garment": ("garment.png", _upload_png(garment_image_path), "image/png"),
        }
        api_key = getattr(settings, "vton_remote_api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        outcome: dict = {}

        def post() -> None:
            try:
                outcome["response"] = httpx.post(
                    f"{settings.vton_remote_url}/tryon", files=files, headers=headers, timeout=limit,
                    data={"category": category, "garment_photo_type": garment_photo_type},
                )
            except Exception as error:
                outcome["error"] = type(error).__name__

        # A blocking call here would stop cancellation and heartbeats, so the worker keeps polling.
        request = threading.Thread(target=post, name="fashn-remote", daemon=True)
        request.start()
        deadline = time.monotonic() + limit
        while request.is_alive():
            request.join(POLL_SECONDS)
            tick()
            if request.is_alive() and should_cancel():
                return FashnResult(failure="cancelled", details={"wall_seconds": round(time.monotonic() - started, 1)})
            if request.is_alive() and time.monotonic() > deadline:
                return _remote_failure("remote_unavailable", started)
        if "response" not in outcome:
            print(f"[fashn] remote request failed: {outcome.get('error')}", file=sys.stderr, flush=True)
            return _remote_failure("remote_unavailable", started)
        return _remote_result(outcome["response"], output_dir, started)
    except Exception as error:
        print(f"[fashn] remote path failed: {type(error).__name__}", file=sys.stderr, flush=True)
        return _remote_failure("remote_unavailable", started)
