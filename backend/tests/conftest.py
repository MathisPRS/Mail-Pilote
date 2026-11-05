import pytest

from app import db as db_module
from app.config import get_settings


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
