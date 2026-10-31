from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

# Preserve process environment values while applying local development defaults.
load_dotenv(override=False)


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
    tryon_queue_name: str = os.getenv("TRYON_QUEUE_NAME", "try-on").strip() or "try-on"
    vton_mode: str = os.getenv("VTON_MODE", "mock").strip().lower()
    max_person_photos: int = _integer("MAX_PERSON_PHOTOS", 10, 1, 50)
    max_outstanding_jobs: int = _integer("MAX_OUTSTANDING_JOBS", 3, 1, 20)
    max_queued_jobs: int = _integer("MAX_QUEUED_JOBS", 200, 1, 10000)
    max_upload_bytes: int = _integer("MAX_UPLOAD_BYTES", 10 * 1024 * 1024, 1024, 50 * 1024 * 1024)
    max_image_pixels: int = _integer("MAX_IMAGE_PIXELS", 40_000_000, 100_000, 100_000_000)
    pending_upload_ttl_seconds: int = _integer("PENDING_UPLOAD_TTL_SECONDS", 3600, 60, 24 * 3600)
    max_avatar_bytes: int = _integer("MAX_AVATAR_BYTES", 50 * 1024 * 1024, 1024 * 1024, 250 * 1024 * 1024)
    storage_path: Path = Path(os.getenv("STORAGE_PATH", "./data/private-images"))
    password_reset_pepper: str = os.getenv("PASSWORD_RESET_PEPPER", "development-only-change-before-deploy")
    password_reset_code_ttl_seconds: int = _integer("PASSWORD_RESET_CODE_TTL_SECONDS", 600, 60, 1800)
    password_reset_attempt_limit: int = _integer("PASSWORD_RESET_ATTEMPT_LIMIT", 5, 1, 20)
    password_reset_cooldown_seconds: int = _integer("PASSWORD_RESET_COOLDOWN_SECONDS", 60, 10, 3600)
    password_reset_rate_limit_count: int = _integer("PASSWORD_RESET_RATE_LIMIT_COUNT", 10, 1, 100)
    password_reset_rate_window_seconds: int = _integer("PASSWORD_RESET_RATE_WINDOW_SECONDS", 900, 60, 86400)
    email_delivery_mode: str = os.getenv("EMAIL_DELIVERY_MODE", "capture").strip().lower()
    email_capture_path: Path = Path(os.getenv("EMAIL_CAPTURE_PATH", "./data/mail-capture"))
    smtp_host: str = os.getenv("SMTP_HOST", "").strip()
    smtp_port: int = _integer("SMTP_PORT", 587, 1, 65535)
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "DressMe <noreply@localhost>")
    smtp_security: str = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    smtp_timeout_seconds: int = _integer("SMTP_TIMEOUT_SECONDS", 10, 1, 60)

    def __post_init__(self) -> None:
        if self.vton_mode not in {"mock", "real"}:
            raise ValueError("VTON_MODE must be 'mock' or 'real'")
        if self.email_delivery_mode not in {"capture", "smtp"}:
            raise ValueError("EMAIL_DELIVERY_MODE must be 'capture' or 'smtp'")
        if self.smtp_security not in {"starttls", "ssl", "none"}:
            raise ValueError("SMTP_SECURITY must be 'starttls', 'ssl' or 'none'")
        if self.email_delivery_mode == "smtp" and not self.smtp_host:
            raise ValueError("SMTP_HOST is required when EMAIL_DELIVERY_MODE=smtp")
        if self.environment == "production":
            if self.database_url.endswith("dressme:dressme@localhost:5432/dressme"):
                raise ValueError("production requires an explicit DATABASE_URL and credential")
            if not self.frontend_origins:
                raise ValueError("production requires an explicit frontend origin")
            if not self.storage_path.is_absolute():
                raise ValueError("production requires an absolute private storage path")
            if len(self.password_reset_pepper) < 32 or "replace-with" in self.password_reset_pepper.lower() or self.password_reset_pepper == "development-only-change-before-deploy":
                raise ValueError("production requires a random private PASSWORD_RESET_PEPPER of at least 32 characters")
            if self.email_delivery_mode != "smtp" or self.smtp_security == "none":
                raise ValueError("production password recovery requires SMTP with TLS")

    @property
    def cookie_secure(self) -> bool:
        return self.environment == "production"


settings = Settings()


def get_settings() -> Settings:
    return settings
