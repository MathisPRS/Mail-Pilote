from app.models import User
PASSWORD = "correct horse battery"

H = {"X-Requested-With": "mail-pilot"}
SETUP = {"username": "mathis", "password": PASSWORD, "display_name": "Mathis"}


def test_setup_once_then_409(client):
    assert client.get("/api/auth/status").json() == {"setup_done": False, "authenticated": False}
    assert client.post("/api/auth/setup", json=SETUP, headers=H).status_code == 201
    assert client.post("/api/auth/setup", json=SETUP, headers=H).status_code == 409
    assert client.get("/api/auth/status").json() == {"setup_done": True, "authenticated": False}


def test_short_password_rejected_422(client):
    r = client.post("/api/auth/setup", json={**SETUP, "password": "short"}, headers=H)
    assert r.status_code == 422


def test_login_sets_httponly_secure_strict_cookie(client):
    client.post("/api/auth/setup", json=SETUP, headers=H)
    r = client.post("/api/auth/login", json={"username": "mathis", "password": PASSWORD}, headers=H)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "mp_session=" in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/me").json()["username"] == "mathis"
    assert client.get("/api/auth/status").json()["authenticated"] is True


def test_session_token_stored_hashed(auth_client, db):
    import hashlib

    from app.models import Session

    token = auth_client.cookies["mp_session"]
    row = db.query(Session).one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in row.token_hash


def test_protected_route_401_without_cookie(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_logout_invalidates_session(auth_client):
    assert auth_client.get("/api/auth/me").status_code == 200
    assert auth_client.post("/api/auth/logout").status_code == 204
    assert auth_client.get("/api/auth/me").status_code == 401


def test_post_without_csrf_header_403(client):
    r = client.post("/api/auth/setup", json=SETUP)
    assert r.status_code == 403
    assert client.get("/api/auth/status").status_code == 200


def test_sixth_failed_login_429(client):
    client.post("/api/auth/setup", json=SETUP, headers=H)
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "mathis", "password": "wrong-password-1"}, headers=H)
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "mathis", "password": PASSWORD}, headers=H)
    assert r.status_code == 429


def test_password_not_stored_in_clear(client, db):
    client.post("/api/auth/setup", json=SETUP, headers=H)
    user = db.query(User).one()
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2")


def test_limiter_ip_and_proxy_trust():
    from app.auth.ratelimit import LoginLimiter, client_ip

    lim = LoginLimiter()
    for i in range(5):
        lim.fail("1.1.1.1", f"user{i}")
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        lim.check("1.1.1.1", "other")
    assert e.value.status_code == 429
    lim.check("2.2.2.2", "other")
    lim.success("2.2.2.2", "other")

    assert client_ip("127.0.0.1", "9.9.9.9, 10.0.0.1") == "9.9.9.9"
    assert client_ip("172.18.0.2", "9.9.9.9") == "9.9.9.9"
    assert client_ip("8.8.8.8", "9.9.9.9") == "8.8.8.8"
    assert client_ip("testclient", "9.9.9.9") == "testclient"
