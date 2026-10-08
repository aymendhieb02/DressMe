from dataclasses import dataclass
import os
from pathlib import Path


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("APP_ENV", "development").strip().lower()
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://dressme:dressme@localhost:5432/dressme",
    )
    frontend_origins: tuple[str, ...] = tuple(
        origin.strip().rstrip("/")
        for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    )
    session_ttl_seconds: int = _integer("SESSION_TTL_SECONDS", 12 * 60 * 60, 300, 30 * 24 * 60 * 60)
    login_limit_count: int = _integer("LOGIN_LIMIT_COUNT", 10, 1, 100)
    login_window_seconds: int = _integer("LOGIN_WINDOW_SECONDS", 60, 1, 3600)
    auth_cookie_name: str = "dressme_session"
    csrf_header_name: str = "X-CSRF-Token"
    bo6_service_url: str = os.getenv("BO6_SERVICE_URL", "http://ml-service:8000").rstrip("/")
    bo6_connect_timeout_seconds: float = 2.0
    bo6_read_timeout_seconds: float = 30.0
    bo6_write_timeout_seconds: float = 10.0
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    vton_mode: str = os.getenv("VTON_MODE", "mock").strip().lower()
    max_person_photos: int = _integer("MAX_PERSON_PHOTOS", 10, 1, 50)
    max_outstanding_jobs: int = _integer("MAX_OUTSTANDING_JOBS", 3, 1, 20)
    max_queued_jobs: int = _integer("MAX_QUEUED_JOBS", 200, 1, 10000)
    max_upload_bytes: int = _integer("MAX_UPLOAD_BYTES", 10 * 1024 * 1024, 1024, 50 * 1024 * 1024)
    max_image_pixels: int = _integer("MAX_IMAGE_PIXELS", 40_000_000, 100_000, 100_000_000)
    pending_upload_ttl_seconds: int = _integer("PENDING_UPLOAD_TTL_SECONDS", 3600, 60, 24 * 3600)
    storage_path: Path = Path(os.getenv("STORAGE_PATH", "./data/private-images"))

    def __post_init__(self) -> None:
        if self.vton_mode not in {"mock", "real"}:
            raise ValueError("VTON_MODE must be 'mock' or 'real'")
        if self.environment == "production":
            if self.database_url.endswith("dressme:dressme@localhost:5432/dressme"):
                raise ValueError("production requires an explicit DATABASE_URL and credential")
            if not self.frontend_origins:
                raise ValueError("production requires an explicit frontend origin")
            if not self.storage_path.is_absolute():
                raise ValueError("production requires an absolute private storage path")

    @property
    def cookie_secure(self) -> bool:
        return self.environment == "production"


settings = Settings()


def get_settings() -> Settings:
    return settings
