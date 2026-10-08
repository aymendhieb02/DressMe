import io

import pytest
from PIL import Image


def test_analyze_valid_image(client, valid_jpeg):
    response = client.post("/analyze", files={"image": ("top.jpg", valid_jpeg, "image/jpeg")})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"quality", "prediction"}
    assert body["quality"]["advisory_only"] is True
    assert body["prediction"]["score_type"] == "uncalibrated_softmax"
    assert "description_fields" in body["prediction"]
    assert body["quality"]["warnings"]


@pytest.mark.parametrize(("format_name", "content_type"), [
    ("PNG", "image/png"),
    ("WEBP", "image/webp"),
])
def test_analyze_accepts_png_and_webp(client, format_name, content_type):
    image_bytes = io.BytesIO()
    Image.new("RGB", (256, 256), (80, 140, 200)).save(image_bytes, format=format_name)
    suffix = "png" if format_name == "PNG" else "webp"
    response = client.post("/analyze", files={
        "image": ("garment." + suffix, image_bytes.getvalue(), content_type),
    })
    assert response.status_code == 200
    assert response.json()["prediction"]["score_type"] == "uncalibrated_softmax"


def test_corrupt_image_returns_422(client):
    response = client.post("/analyze", files={"image": ("broken.jpg", b"not an image", "image/jpeg")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_image"


def test_oversized_image_returns_413(client):
    response = client.post("/analyze", files={"image": ("large.jpg", b"x" * (10 * 1024 * 1024 + 1), "image/jpeg")})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_unsupported_file_returns_415(client):
    response = client.post("/analyze", files={"image": ("photo.gif", b"GIF89a", "image/gif")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
