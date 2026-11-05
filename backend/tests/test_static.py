from fastapi.testclient import TestClient

from app.main import create_app


def _dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>SPA</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    return tmp_path


def test_spa_fallback_returns_index_html(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_FRONTEND_DIST", str(_dist(tmp_path)))
    client = TestClient(create_app())

    for path in ("/", "/box/all/inbox", "/login"):
        r = client.get(path)
        assert r.status_code == 200
        assert "SPA" in r.text
    assert client.get("/assets/app.js").text == "console.log(1)"


def test_unknown_api_path_is_json_404(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_FRONTEND_DIST", str(_dist(tmp_path)))
    client = TestClient(create_app())

    r = client.get("/api/unknown")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert client.get("/api/health").json() == {"status": "ok"}


def test_path_traversal_never_leaves_dist(tmp_path, monkeypatch):
    dist = _dist(tmp_path / "dist") if (tmp_path / "dist").mkdir() is None else None
    (tmp_path / "outside.txt").write_text("outside")
    monkeypatch.setenv("MP_FRONTEND_DIST", str(dist))
    client = TestClient(create_app())

    r = client.get("/..%2foutside.txt")
    assert "outside" not in r.text


def test_missing_dist_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_FRONTEND_DIST", str(tmp_path / "absent"))
    client = TestClient(create_app())

    assert client.get("/api/health").status_code == 200
    assert client.get("/box/all/inbox").status_code == 404
