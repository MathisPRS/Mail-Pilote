import pytest
from app.models import User
PASSWORD = "correct horse battery"

H = {"X-Requested-With": "mail-pilot"}
SETUP = {"username": "mathis", "password": PASSWORD, "display_name": "Mathis"}


def test_setup_once_then_409(client):
    assert client.get("/api/auth/status").json() == {
        "setup_done": False, "authenticated": False, "setup_token_required": False,
    }
    assert client.post("/api/auth/setup", json=SETUP, headers=H).status_code == 201
    assert client.post("/api/auth/setup", json=SETUP, headers=H).status_code == 409
    assert client.get("/api/auth/status").json() == {
        "setup_done": True, "authenticated": False, "setup_token_required": False,
    }


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

    assert client_ip("127.0.0.1", "6.6.6.6, 203.0.113.9") == "203.0.113.9"
    assert client_ip("127.0.0.1", "not-an-ip") == "127.0.0.1"
    assert client_ip("172.18.0.2", "9.9.9.9") == "9.9.9.9"
    assert client_ip("8.8.8.8", "9.9.9.9") == "8.8.8.8"
    assert client_ip("testclient", "9.9.9.9") == "testclient"


def test_authenticated_request_refreshes_cookie(auth_client):
    r = auth_client.get("/api/auth/me")
    cookie = r.headers["set-cookie"].lower()
    assert "mp_session=" in cookie and "max-age=2592000" in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie


# ---------- audit T16 : DoS argon2, course du premier lancement, jeton d'installation ----------

import threading
import time

from sqlalchemy import func, select

from app.auth import service
from app.config import get_settings


class SlowHasher:
    """Hasher factice lent qui mesure la concurrence maximale observée."""

    def __init__(self, delay=0.2):
        self.delay, self.active, self.peak = delay, 0, 0
        self._lock = threading.Lock()

    def _work(self):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.delay)
        with self._lock:
            self.active -= 1

    def hash(self, password):
        self._work()
        return "fake$" + password

    def verify(self, h, password):
        self._work()
        return h == "fake$" + password


def _run_parallel(fns):
    out = [None] * len(fns)

    def run(i, fn):
        out[i] = fn()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_password_hashing_concurrency_is_bounded(monkeypatch):
    fake = SlowHasher(0.1)
    monkeypatch.setattr(service, "_hasher", fake)
    monkeypatch.setattr(service, "_hash_slots", threading.BoundedSemaphore(2))
    monkeypatch.setattr(service, "HASH_WAIT_SECONDS", 5)
    _run_parallel([lambda: service.verify_password("fake$x", "x")] * 8)
    assert fake.peak == 2


def test_busy_hasher_returns_429_without_counting_a_failure(client, monkeypatch):
    client.post("/api/auth/setup", json=SETUP, headers=H)
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(service, "_hash_slots", slots)
    monkeypatch.setattr(service, "HASH_WAIT_SECONDS", 0.05)
    slots.acquire()  # toutes les places occupées
    try:
        r = client.post("/api/auth/login", json={"username": "mathis", "password": PASSWORD}, headers=H)
        assert r.status_code == 429
        assert r.json()["detail"] == "Trop de tentatives, réessaie dans quelques instants."
        r = client.post("/api/auth/setup", json={**SETUP, "username": "autre"}, headers=H)
        assert r.status_code in (409, 429)
    finally:
        slots.release()
    r = client.post("/api/auth/login", json={"username": "mathis", "password": PASSWORD}, headers=H)
    assert r.status_code == 200


def test_concurrent_logins_never_exceed_bound(client, monkeypatch):
    fake = SlowHasher(0.2)
    monkeypatch.setattr(service, "_hasher", fake)
    client.post("/api/auth/setup", json=SETUP, headers=H)
    fake.peak = 0
    monkeypatch.setattr(service, "_hash_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(service, "HASH_WAIT_SECONDS", 0.05)
    login = lambda: client.post(
        "/api/auth/login", json={"username": "mathis", "password": PASSWORD}, headers=H
    ).status_code
    codes = _run_parallel([login] * 4)
    assert fake.peak == 1
    assert 429 in codes and 200 in codes


def test_concurrent_setups_create_a_single_user(client, db, monkeypatch):
    monkeypatch.setattr(service, "_hasher", SlowHasher(0.2))
    setup = lambda name: (lambda: client.post(
        "/api/auth/setup", json={**SETUP, "username": name}, headers=H
    ).status_code)
    codes = _run_parallel([setup("alice"), setup("bob")])
    assert sorted(codes) == [201, 409]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(User)) == 1


def test_second_user_rejected_at_db_level(db):
    service.create_user(db, "un", PASSWORD, "")
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db.add(User(username="deux", password_hash="x", display_name=""))
        db.commit()


@pytest.fixture
def setup_token(settings, monkeypatch):
    monkeypatch.setenv("MP_SETUP_TOKEN", "jeton-installation-secret")
    get_settings.cache_clear()
    yield "jeton-installation-secret"
    get_settings.cache_clear()


def test_setup_token_required_when_configured(setup_token, client):
    assert client.get("/api/auth/status").json()["setup_token_required"] is True
    for bad in (None, "", "faux", "jeton-installation-secretX", "é"):
        body = SETUP if bad is None else {**SETUP, "setup_token": bad}
        r = client.post("/api/auth/setup", json=body, headers=H)
        assert r.status_code == 403
        assert r.json()["detail"] == "Jeton d'installation invalide"
    r = client.post("/api/auth/setup", json={**SETUP, "setup_token": setup_token}, headers=H)
    assert r.status_code == 201
    assert client.get("/api/auth/status").json()["setup_token_required"] is False


def test_password_fields_have_max_length(client):
    long = "a" * 1025
    assert client.post("/api/auth/setup", json={**SETUP, "password": long}, headers=H).status_code == 422
    r = client.post("/api/auth/login", json={"username": "mathis", "password": long}, headers=H)
    assert r.status_code == 422
