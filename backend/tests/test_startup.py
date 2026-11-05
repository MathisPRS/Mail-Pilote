import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

MSG = "MP_SECRET_KEY manquante ou trop courte (32 caractères minimum)"


@pytest.mark.parametrize("key", ["", "trop-court"])
def test_refuses_short_secret(settings, monkeypatch, key):
    monkeypatch.setenv("MP_SECRET_KEY", key)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError) as exc:
        with TestClient(create_app()):
            pass
    assert str(exc.value) == MSG


def test_starts_and_initialises_with_valid_secret(settings, monkeypatch):
    monkeypatch.setenv("MP_SECRET_KEY", "k" * 40)
    get_settings.cache_clear()
    from app import db as db_module

    db_module.configure(f"sqlite:///{settings.data_dir / 'start.db'}")
    try:
        with TestClient(create_app()) as c:
            assert c.get("/api/health").json() == {"status": "ok"}
        assert (settings.data_dir / "start.db").exists()
    finally:
        db_module.dispose()


def test_security_headers_present(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>SPA</html>")
    (tmp_path / "sw.js").write_text("//sw")
    (tmp_path / "assets" / "app-abc.js").write_text("1")
    monkeypatch.setenv("MP_FRONTEND_DIST", str(tmp_path))
    c = TestClient(create_app())
    for path in ("/api/health", "/", "/login"):
        h = c.get(path).headers
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "img-src 'self' data:" in csp
        assert "frame-src 'self'" in csp
        assert "object-src 'none'" in csp
        assert "base-uri 'none'" in csp
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert h["strict-transport-security"] == "max-age=31536000"


def test_cache_control(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>SPA</html>")
    (tmp_path / "sw.js").write_text("//sw")
    (tmp_path / "assets" / "app-abc.js").write_text("1")
    monkeypatch.setenv("MP_FRONTEND_DIST", str(tmp_path))
    c = TestClient(create_app())
    for path in ("/", "/index.html", "/sw.js", "/login"):
        assert c.get(path).headers["cache-control"] == "no-cache"
    assert "immutable" in c.get("/assets/app-abc.js").headers["cache-control"]


def test_head_on_spa_is_allowed(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>SPA</html>")
    monkeypatch.setenv("MP_FRONTEND_DIST", str(tmp_path))
    r = TestClient(create_app()).head("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_anti_clickjacking_headers():
    c = TestClient(create_app())
    for path in ("/api/health", "/", "/login"):
        h = c.get(path).headers
        assert "frame-ancestors 'self'" in h["content-security-policy"]
        assert h["x-frame-options"] == "SAMEORIGIN"


def test_api_responses_are_not_cached(auth_client):
    # corps de mails, réglages : jamais dans le cache HTTP du navigateur (appareil partagé)
    for path in ("/api/auth/me", "/api/auth/status", "/api/health"):
        assert auth_client.get(path).headers["cache-control"] == "no-store"


def test_openapi_and_docs_not_exposed():
    """Toute l'API est authentifiée : son schéma et la doc interactive ne sont pas publiés."""
    c = TestClient(create_app())
    for path in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
        r = c.get(path)
        assert "openapi" not in r.text.lower() and "swagger" not in r.text.lower(), path
