import os

import pytest

from app import db as db_module
from app.config import get_settings

os.environ["MP_DISABLE_SCHEDULER"] = "1"  # jamais de planificateur dans les tests


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MP_SECRET_KEY", "test-secret-key")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def db(settings):
    db_module.configure(f"sqlite:///{settings.data_dir / 'test.db'}")
    db_module.init_db()
    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.close()
        db_module.dispose()


PASSWORD = "correct horse battery"


@pytest.fixture
def client(db):
    """TestClient HTTPS (cookie Secure) branché sur la base de test, limiteur remis à zéro."""
    from fastapi.testclient import TestClient

    from app.auth.ratelimit import login_limiter
    from app.db import get_db
    from app.main import create_app

    login_limiter.reset()
    app = create_app()

    def _get_db():
        session = db_module.SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def auth_client(client):
    """Client ayant fait setup + login ; envoie X-Requested-With: mail-pilot par défaut."""
    client.headers["X-Requested-With"] = "mail-pilot"
    r = client.post(
        "/api/auth/setup",
        json={"username": "mathis", "password": PASSWORD, "display_name": "Mathis"},
    )
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={"username": "mathis", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client
