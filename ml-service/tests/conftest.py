import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def client():
    from app.main import app
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def valid_jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), (30, 100, 180)).save(buffer, "JPEG")
    return buffer.getvalue()
