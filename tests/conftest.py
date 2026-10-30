import os
import tempfile

import pytest
from fastapi.testclient import TestClient as BaseTestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models  # noqa: F401
from app.main import app
from app.auth import rate_limit


class TestClient(BaseTestClient):
    """Keep per-request cookie overrides isolated across httpx/httpx2 clients."""

    def request(self, method, url, *, cookies=None, **kwargs):
        if cookies is None:
            return super().request(method, url, **kwargs)
        previous = list(self.cookies.jar)
        self.cookies.clear()
        self.cookies.update(cookies)
        try:
            return super().request(method, url, **kwargs)
        finally:
            self.cookies.clear()
            for cookie in previous:
                self.cookies.jar.set_cookie(cookie)


@pytest.fixture
def client(monkeypatch):
    # Each API fixture has its own database and abuse-guard state, with real limits.
    monkeypatch.setattr(rate_limit, "login_limiter", rate_limit.LoginLimiter())
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_factory = TestingSession
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.testing_session_factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def origin():
    return {"Origin": "http://localhost:5173"}
