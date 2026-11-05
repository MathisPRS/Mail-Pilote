import pytest

from app.crypto import encrypt
from app.models import PushSubscription
from app.notify import gotify, webpush
from app.settings_store import AlertSettings, set_alerts


def test_requires_auth(client):
    assert client.get("/api/push/vapid-public-key").status_code == 401


def test_vapid_public_key_stable(auth_client, settings):
    a = auth_client.get("/api/push/vapid-public-key").json()["key"]
    b = auth_client.get("/api/push/vapid-public-key").json()["key"]
    assert a == b and len(a) == 87  # point P-256 non compressé, base64url sans padding
    priv = settings.data_dir / "vapid" / "private_key.pem"
    assert priv.exists() and oct(priv.stat().st_mode & 0o777) == "0o600"


def test_subscribe_upserts(auth_client, db):
    body = {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": "k1", "auth": "a1"}}
    assert auth_client.post("/api/push/subscribe", json=body).status_code == 204
    body["keys"]["auth"] = "a2"
    assert auth_client.post("/api/push/subscribe", json=body).status_code == 204
    db.expire_all()
    rows = db.query(PushSubscription).all()
    assert len(rows) == 1 and rows[0].auth == "a2"


def test_subscribe_rejects_bad_payload(auth_client):
    r = auth_client.post("/api/push/subscribe", json={"endpoint": "https://p"})
    assert r.status_code == 422


def test_test_channel_not_configured(auth_client):
    r = auth_client.post("/api/alerts/test", json={"channel": "gotify"})
    assert r.status_code == 400 and "Gotify" in r.json()["detail"]
    r = auth_client.post("/api/alerts/test", json={"channel": "webpush"})
    assert r.status_code == 400


def test_test_gotify_ok_and_failure(auth_client, db, monkeypatch):
    set_alerts(db, AlertSettings(gotify=True, gotify_url="http://g", gotify_token_enc=encrypt("t")))
    calls = []

    async def ok(url, token, title, message, priority, click_url=None):
        calls.append((url, token, title, message))

    monkeypatch.setattr(gotify, "send_gotify", ok)
    r = auth_client.post("/api/alerts/test", json={"channel": "gotify"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert calls == [("http://g", "t", "Mail Pilot · Test", "Les notifications fonctionnent.")]

    async def bad(*a, **k):
        raise RuntimeError("secret-token")

    monkeypatch.setattr(gotify, "send_gotify", bad)
    r = auth_client.post("/api/alerts/test", json={"channel": "gotify"})
    assert r.status_code == 502 and r.json()["detail"] == "Échec de l'envoi"


def test_test_webpush_ok(auth_client, db, monkeypatch):
    set_alerts(db, AlertSettings(webpush=True))
    db.add(PushSubscription(endpoint="https://fcm.googleapis.com/1", p256dh="k", auth="a"))
    db.commit()
    seen = []
    monkeypatch.setattr(webpush, "send_webpush", lambda sub, payload: seen.append(payload))
    r = auth_client.post("/api/alerts/test", json={"channel": "webpush"})
    assert r.status_code == 200
    assert seen[0]["title"] == "Mail Pilot · Test"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/x",
        "https://127.0.0.1/x",
        "https://localhost/x",
        "https://169.254.169.254/latest",
        "https://[::1]/x",
        "https://2130706433/",
        "https://0x7f000001/",
        "https://127.1/",
        "https://0177.0.0.1/",
        "https://0/",
        "https://127.0.0.1.nip.io/x",
        "https://evil.com/web.push.apple.com",
        "https://web.push.apple.com.evil.com/x",
        "https://evilpush.apple.com.evil.io/x",
        "https://u@web.push.apple.com/x",
        "https://web.push.apple.com:8443/x",
        "https://fcm.googleapis.com/" + "a" * 2100,
    ],
)
def test_subscribe_rejects_unsafe_endpoint(auth_client, endpoint):
    body = {"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}}
    assert auth_client.post("/api/push/subscribe", json=body).status_code == 422


def test_subscribe_rejects_oversized_keys(auth_client):
    body = {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": "k" * 257, "auth": "a"}}
    assert auth_client.post("/api/push/subscribe", json=body).status_code == 422


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://web.push.apple.com/QGxIj8",
        "HTTPS://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com:443/wpush/v2/x",
    ],
)
def test_subscribe_accepts_known_push_services(auth_client, endpoint):
    body = {"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}}
    assert auth_client.post("/api/push/subscribe", json=body).status_code == 204
