"""Only public, exact provider origins may reach the browser."""


import json
import os
from pathlib import Path
import subprocess
import sys


def test_studio_config_exposes_only_exact_https_origins(monkeypatch):
    from api import studio_config

    for url in (
        "https://demo.avaturn.dev/private-token",
        "https://demo.avaturn.dev:444",
        "https://user:pass@demo.avaturn.dev",
        "https://demo.avaturn.dev?token=secret",
        "https://[broken",
        "http://demo.avaturn.dev",
    ):
        monkeypatch.setenv("AVATURN_URL", url)
        result = studio_config()
        assert result["avaturn_url"] is None and result["export_origins"] == []
        assert result["upload_limits"]["image_bytes"] > 0
        assert result["upload_limits"]["avatar_bytes"] > 0

    monkeypatch.setenv("AVATURN_URL", "https://demo.avaturn.dev")
    monkeypatch.setenv("AVATURN_EXPORT_ORIGINS", "https://assets.example.com,https://bad.example.com:444,https://[broken")
    result = studio_config()
    assert result["avaturn_url"] == "https://demo.avaturn.dev"
    assert result["export_origins"] == ["https://assets.example.com", "https://demo.avaturn.dev"]


def test_combined_entrypoint_dotenv_precedence_and_public_config_are_isolated(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    (tmp_path / "static").mkdir()
    (tmp_path / ".env").write_text(
        "DATABASE_URL=sqlite:///dotenv-database.db\n"
        "BO6_SERVICE_URL=http://ml-from-dotenv:9000\n"
        "AVATURN_URL=https://demo.avaturn.dev\n"
        "PASSWORD_RESET_PEPPER=private-pepper-sentinel\n"
        "SMTP_PASSWORD=private-smtp-sentinel\n"
        "REDIS_URL=redis://:private-redis-sentinel@localhost/14\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    for key in ("BO6_SERVICE_URL", "AVATURN_URL", "AVATURN_EXPORT_ORIGINS", "SMTP_PASSWORD", "PASSWORD_RESET_PEPPER", "REDIS_URL"):
        env.pop(key, None)
    env.update({
        "PYTHONPATH": str(repo),
        "DRESSME_DATA": str(repo / "data"),
        "DATABASE_URL": "sqlite:///explicit-process-database.db",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    script = """
import json
import api
from app.config import get_settings, settings
from app.main import app as studio_app
print(json.dumps({
  'database_url': settings.database_url,
  'bo6_service_url': settings.bo6_service_url,
  'same_settings': get_settings() is settings,
  'studio_title': studio_app.title,
  'public_config': api.studio_config(),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=90, check=True,
    )
    output = json.loads(result.stdout.strip().splitlines()[-1])
    assert output["database_url"] == "sqlite:///explicit-process-database.db"
    assert output["bo6_service_url"] == "http://ml-from-dotenv:9000"
    assert output["same_settings"] is True
    assert output["studio_title"] == "DressMe Application API"
    assert output["public_config"] == {
        "avaturn_url": "https://demo.avaturn.dev",
        "export_origins": ["https://demo.avaturn.dev"],
        "upload_limits": {
            "image_bytes": 10 * 1024 * 1024,
            "avatar_bytes": 50 * 1024 * 1024,
            "image_content_types": ["image/jpeg", "image/png", "image/webp"],
            "avatar_extensions": [".glb"],
        },
    }
    for sentinel in ("private-pepper-sentinel", "private-smtp-sentinel", "private-redis-sentinel"):
        assert sentinel not in result.stdout
        assert sentinel not in result.stderr
