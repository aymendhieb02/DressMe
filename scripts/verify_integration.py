"""Disposable local HTTP check for the mounted BO6 contract and ownership boundary."""
import csv
import io
from pathlib import Path
from uuid import uuid4

import requests

BASE = "http://127.0.0.1:8002/studio-api"
ORIGIN = "http://127.0.0.1:8002"
PHOTO = Path(__file__).resolve().parents[1] / "data/img/P01133864.jpg"


def call(session, method, path, *, csrf=None, expected=200, extra_headers=None, **kwargs):
    headers = {"Origin": ORIGIN}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    headers.update(extra_headers or {})
    response = session.request(method, BASE + path, headers=headers, timeout=45, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:300])
    return response.json() if response.content else None


def account():
    session = requests.Session()
    password = "Local-check-" + uuid4().hex
    auth = call(session, "POST", "/auth/register", expected=201,
                json={"email": f"integration-{uuid4().hex}@example.invalid", "password": password})
    return session, auth["csrf_token"], password


def main():
    a, token_a, password_a = account()
    b, token_b, password_b = account()
    try:
        call(a, "POST", "/garments/analyze", csrf=token_a, expected=415,
             files={"image": ("bad.txt", b"not an image", "text/plain")})
        call(a, "POST", "/garments/analyze", csrf=token_a, expected=413,
             files={"image": ("large.jpg", b"0" * (10 * 1024 * 1024 + 1), "image/jpeg")})
        with PHOTO.open("rb") as file:
            pending = call(a, "POST", "/garments/analyze", csrf=token_a, expected=201,
                           files={"image": (PHOTO.name, file, "image/jpeg")},
                           extra_headers={"Idempotency-Key": str(uuid4())})
        assert pending["prediction"]["model_version"] == "E03_efficientnet_b0"
        described = call(a, "POST", "/garments/describe", csrf=token_a,
                         json={"pending_upload_id": pending["id"], "confirmed": {"category": "trousers"}})
        assert described["text"]
        garment = call(a, "POST", "/garments", csrf=token_a, expected=201,
                       json={"pending_upload_id": pending["id"], "category": "trousers", "garment_photo_type": "flat-lay"})
        assert garment["description"] == described["text"] and not garment["description_is_manual"]
        own = call(a, "GET", f"/garments/{garment['id']}")
        assert own["id"] == garment["id"]
        image = a.get(BASE + garment["image_url"], timeout=20)
        assert image.status_code == 200 and image.content
        for path in (f"/garments/{garment['id']}", garment["image_url"]):
            assert b.get(BASE + path, timeout=20).status_code == 404
        call(b, "PATCH", f"/garments/{garment['id']}", csrf=token_b, expected=404,
             json={"name": "not owned"})
        call(b, "DELETE", f"/garments/{garment['id']}", csrf=token_b, expected=404)
        assert call(b, "GET", "/garments")["total"] == 0
        edited = call(a, "PATCH", f"/garments/{garment['id']}", csrf=token_a,
                      json={"description": "My reviewed trousers."})
        assert edited["description_is_manual"] and edited["description"] == "My reviewed trousers."
        assert call(a, "GET", "/garments")["total"] == 1
        for session, expected_rows in ((a, 1), (b, 0)):
            export = session.get(BASE + "/garments/export.csv", timeout=20)
            assert export.status_code == 200
            rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
            assert len(rows) == expected_rows
            assert "image_key" not in export.text and "DATABASE_URL" not in export.text
            if expected_rows:
                assert rows[0]["garment_id"] == garment["id"]
                assert rows[0]["description"] == "My reviewed trousers."
        call(a, "DELETE", f"/garments/{garment['id']}", csrf=token_a, expected=204)
        assert a.get(BASE + f"/garments/{garment['id']}", timeout=20).status_code == 404
        assert a.get(BASE + garment["image_url"], timeout=20).status_code == 404
        print("PASS real BO6 analyze, confirmed description, save, private image, edit, list, cross-user 404")
        print("PASS upload limits, cross-user mutation denial, owned CSV isolation, private deletion")
        print("model_version", pending["prediction"]["model_version"], "suggestions", len(pending["prediction"]["suggestions"]))
    finally:
        for session, token, password in ((a, token_a, password_a), (b, token_b, password_b)):
            call(session, "DELETE", "/auth/account", csrf=token, expected=204,
                 json={"password": password, "confirmation": "DELETE"})
        print("PASS disposable account cleanup")


if __name__ == "__main__":
    main()
