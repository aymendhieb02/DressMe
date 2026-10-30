"""Disposable two-stage persistence check; run prepare, restart app, then finish."""
import json
import os
from pathlib import Path
from uuid import uuid4

import requests

from verify_integration import BASE, PHOTO, call

STATE = Path(os.environ["LOCALAPPDATA"]) / "DressMe" / "rihab-integration" / "restart-check.json"


def prepare():
    if STATE.exists():
        raise RuntimeError("A restart check is already pending; finish or inspect it before starting another")
    session = requests.Session()
    password = "Restart-check-" + uuid4().hex
    auth = call(session, "POST", "/auth/register", expected=201,
                json={"email": f"restart-{uuid4().hex}@example.invalid", "password": password})
    token = auth["csrf_token"]
    with PHOTO.open("rb") as file:
        pending = call(session, "POST", "/garments/analyze", csrf=token, expected=201,
                       files={"image": (PHOTO.name, file, "image/jpeg")})
    garment = call(session, "POST", "/garments", csrf=token, expected=201,
                   json={"pending_upload_id": pending["id"], "category": "trousers",
                         "garment_photo_type": "flat-lay"})
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"cookies": requests.utils.dict_from_cookiejar(session.cookies),
                                 "password": password, "garment_id": garment["id"],
                                 "image_url": garment["image_url"]}), encoding="utf-8")
    print("PASS disposable garment saved; restart the application service, then run finish")


def finish():
    record = json.loads(STATE.read_text(encoding="utf-8"))
    session = requests.Session()
    session.cookies = requests.utils.cookiejar_from_dict(record["cookies"])
    garment = call(session, "GET", "/garments/" + record["garment_id"])
    assert garment["id"] == record["garment_id"]
    image = session.get(BASE + record["image_url"], timeout=20)
    assert image.status_code == 200 and image.content
    print("PASS owned garment, session and private image persisted across application restart")
    token = call(session, "POST", "/auth/csrf", extra_headers={"X-CSRF-Bootstrap": "1"})["csrf_token"]
    call(session, "DELETE", "/auth/account", csrf=token, expected=204,
         json={"password": record["password"], "confirmation": "DELETE"})
    STATE.unlink()
    print("PASS disposable account cleanup")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["prepare"]:
        prepare()
    elif sys.argv[1:] == ["finish"]:
        finish()
    else:
        raise SystemExit("usage: verify_restart.py prepare|finish")
