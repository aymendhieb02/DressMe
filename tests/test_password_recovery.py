from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import uuid

from sqlalchemy import select
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from app.auth import recovery
from app.auth.security import hash_password
from app.config import settings
from app.database import Base
from app.models import PasswordRecoveryChallenge, User


def _register(client, origin, email="recover@example.invalid", password="old secure password"):
    return client.post("/auth/register", headers=origin, json={"email": email, "password": password})


def _configure_capture(monkeypatch, tmp_path):
    monkeypatch.setattr(recovery, "settings", replace(
        settings,
        email_delivery_mode="capture",
        email_capture_path=tmp_path / "captured-mail",
        password_reset_pepper="isolated-test-pepper",
        password_reset_cooldown_seconds=60,
        password_reset_attempt_limit=5,
        password_reset_rate_limit_count=20,
        password_reset_rate_window_seconds=900,
    ))
    monkeypatch.setattr(recovery, "rate_limiter", recovery.WindowLimiter())
    return tmp_path / "captured-mail"


def _request(client, origin, email):
    return client.post("/auth/password-reset/request", headers=origin, json={"email": email})


def _complete(client, origin, email, code, new_password="new secure password"):
    return client.post("/auth/password-reset/complete", headers=origin, json={
        "email": email, "code": code, "new_password": new_password,
    })


def _captured_code(mail_path):
    messages = list(mail_path.glob("*.eml"))
    assert len(messages) == 1
    email = BytesParser(policy=policy.default).parsebytes(messages[0].read_bytes())
    return email.get_body(preferencelist=("plain",)).get_content().splitlines()[2]


def test_password_recovery_is_generic_single_use_revokes_sessions_and_requires_sign_in(client, origin, monkeypatch, tmp_path):
    mail_path = _configure_capture(monkeypatch, tmp_path)
    created = _register(client, origin)
    assert created.status_code == 201
    original_cookie = client.cookies.get("dressme_session")

    known = _request(client, origin, "recover@example.invalid")
    unknown = _request(client, origin, "unknown@example.invalid")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    code = _captured_code(mail_path)
    assert len(code) == 8 and code.isdecimal()

    with client.app.state.testing_session_factory() as db:
        user = db.scalar(select(User).where(User.email == "recover@example.invalid"))
        challenge = db.get(PasswordRecoveryChallenge, user.id)
        assert code not in challenge.code_verifier
        assert len(challenge.code_verifier) == 64

    reset = _complete(client, origin, "recover@example.invalid", code)
    assert reset.status_code == 204
    assert client.get("/auth/me").status_code == 401
    replay = _complete(client, origin, "recover@example.invalid", code)
    assert replay.status_code == 400
    assert client.post("/auth/login", headers=origin, json={
        "email": "recover@example.invalid", "password": "old secure password",
    }).status_code == 401
    assert client.post("/auth/login", headers=origin, json={
        "email": "recover@example.invalid", "password": "new secure password",
    }).status_code == 200
    assert original_cookie


def test_recovery_cooldown_expiry_attempt_limit_and_replacement(monkeypatch, client, origin, tmp_path):
    mail_path = _configure_capture(monkeypatch, tmp_path)
    _register(client, origin, email="limits@example.invalid")
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "utc_now", lambda: now)

    first = _request(client, origin, "limits@example.invalid")
    assert first.status_code == 202
    assert _request(client, origin, "limits@example.invalid").json() == first.json()
    assert len(list(mail_path.glob("*.eml"))) == 1
    old_code = _captured_code(mail_path)

    now += timedelta(seconds=61)
    assert _request(client, origin, "limits@example.invalid").status_code == 202
    messages = list(mail_path.glob("*.eml"))
    assert len(messages) == 2
    codes = {
        BytesParser(policy=policy.default).parsebytes(message.read_bytes())
        .get_body(preferencelist=("plain",)).get_content().splitlines()[2]
        for message in messages
    }
    assert old_code in codes and len(codes) == 2
    new_code = next(code for code in codes if code != old_code)
    assert _complete(client, origin, "limits@example.invalid", old_code).status_code == 400
    assert _complete(client, origin, "limits@example.invalid", new_code).status_code == 204


def test_invalid_code_attempts_are_limited_and_unknown_account_verification_is_generic(client, origin, monkeypatch, tmp_path):
    mail_path = _configure_capture(monkeypatch, tmp_path)
    _register(client, origin, email="attempts@example.invalid")
    _request(client, origin, "attempts@example.invalid")
    unknown = _complete(client, origin, "missing@example.invalid", "00000000")
    assert unknown.status_code == 400
    for _ in range(5):
        invalid = _complete(client, origin, "attempts@example.invalid", "00000000")
    assert invalid.status_code == 400
    code = _captured_code(mail_path)
    assert _complete(client, origin, "attempts@example.invalid", code).status_code == 400


def test_recovery_code_expiry_is_enforced(client, origin, monkeypatch, tmp_path):
    mail_path = _configure_capture(monkeypatch, tmp_path)
    monkeypatch.setattr(recovery, "settings", replace(
        recovery.settings, password_reset_code_ttl_seconds=60,
    ))
    _register(client, origin, email="expires@example.invalid")
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "utc_now", lambda: now)
    assert _request(client, origin, "expires@example.invalid").status_code == 202
    code = _captured_code(mail_path)
    now += timedelta(seconds=61)
    assert _complete(client, origin, "expires@example.invalid", code).status_code == 400


def test_atomic_recovery_claim_allows_only_one_concurrent_consumer(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'recovery-race.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add(User(id=user_id, email="race@example.invalid", password_hash="unused"))
        db.add(PasswordRecoveryChallenge(
            user_id=user_id, code_verifier="a" * 64, created_at=now,
            expires_at=now + timedelta(minutes=5), attempts=0,
        ))
        db.commit()

    def claim():
        with Session(engine) as db:
            claimed = db.execute(
                update(PasswordRecoveryChallenge)
                .where(
                    PasswordRecoveryChallenge.user_id == user_id,
                    PasswordRecoveryChallenge.code_verifier == "a" * 64,
                    PasswordRecoveryChallenge.consumed_at.is_(None),
                    PasswordRecoveryChallenge.attempts < 5,
                    PasswordRecoveryChallenge.expires_at > now,
                )
                .values(consumed_at=now)
            )
            db.commit()
            return claimed.rowcount

    from concurrent.futures import ThreadPoolExecutor

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(lambda _index: claim(), range(2)))
        assert sorted(outcomes) == [0, 1]
    finally:
        engine.dispose()


def test_login_accepts_legacy_password_shorter_than_new_account_policy(client, origin):
    with client.app.state.testing_session_factory() as db:
        db.add(User(email="legacy@example.invalid", password_hash=hash_password("short")))
        db.commit()
    response = client.post("/auth/login", headers=origin, json={
        "email": "legacy@example.invalid", "password": "short",
    })
    assert response.status_code == 200


def test_password_recovery_requires_frontend_origin(client):
    response = client.post("/auth/password-reset/request", json={"email": "nobody@example.invalid"})
    assert response.status_code == 403
