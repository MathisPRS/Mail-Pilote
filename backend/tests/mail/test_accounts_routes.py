import pytest

from app import db as db_module
from app.crypto import decrypt
from app.mail import accounts_routes, imap
from app.models import MailAccount


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    def fake(host, port, username, password):
        recorded.append((host, port, username, password))

    monkeypatch.setattr(accounts_routes, "test_connection", fake)
    return recorded


def _post(c, **over):
    body = {"provider": "gmail", "email": "me@gmail.com", "password": "app-pass-1234"}
    body.update(over)
    return c.post("/api/accounts", json=body)


def test_create_gmail_uses_preset_host(auth_client, calls):
    r = _post(auth_client)
    assert r.status_code == 201, r.text
    data = r.json()
    assert calls == [("imap.gmail.com", 993, "me@gmail.com", "app-pass-1234")]
    assert data["provider"] == "gmail"
    assert data["label"] == "Gmail"
    assert data["color"] == "#D93025"
    assert data["status"] == "ok"
    assert auth_client.get("/api/accounts").json()[0]["id"] == data["id"]


def test_create_imap_custom_host_and_username(auth_client, calls):
    r = _post(auth_client, provider="imap", email="a@laposte.net", imap_host="imap.laposte.net",
              username="login42", label="Poste")
    assert r.status_code == 201, r.text
    assert calls == [("imap.laposte.net", 993, "login42", "app-pass-1234")]
    assert r.json()["label"] == "Poste"
    assert _post(auth_client, provider="imap", email="b@x.fr").status_code == 422


def test_invalid_provider_422(auth_client, calls):
    assert _post(auth_client, provider="yahoo").status_code == 422


def test_duplicate_409(auth_client, calls):
    assert _post(auth_client).status_code == 201
    r = _post(auth_client)
    assert r.status_code == 409
    assert r.json()["detail"] == "Cette boîte est déjà configurée"


def test_create_fails_on_bad_password_400(auth_client, monkeypatch):
    def boom(*a):
        raise imap.MailAuthError("no")

    monkeypatch.setattr(accounts_routes, "test_connection", boom)
    r = _post(auth_client)
    assert r.status_code == 400
    assert r.json() == {"detail": "Identifiants refusés par le serveur"}
    assert auth_client.get("/api/accounts").json() == []


def test_create_fails_on_unreachable_400(auth_client, monkeypatch):
    def boom(*a):
        raise imap.MailConnectError("down")

    monkeypatch.setattr(accounts_routes, "test_connection", boom)
    r = _post(auth_client)
    assert r.status_code == 400
    assert r.json() == {"detail": "Serveur injoignable"}


def test_secret_never_returned(auth_client, calls):
    r = _post(auth_client)
    listing = auth_client.get("/api/accounts")
    for resp in (r, listing):
        assert "app-pass-1234" not in resp.text
        assert "secret" not in resp.text


def test_secret_encrypted_in_db(auth_client, calls):
    _post(auth_client)
    s = db_module.SessionLocal()
    try:
        acc = s.query(MailAccount).one()
        assert acc.secret_enc != "app-pass-1234"
        assert decrypt(acc.secret_enc) == "app-pass-1234"
    finally:
        s.close()


def test_patch_password_retests_and_resets_status(auth_client, calls):
    aid = _post(auth_client).json()["id"]
    s = db_module.SessionLocal()
    acc = s.get(MailAccount, aid)
    acc.status, acc.status_message = "error", "bad"
    s.commit()
    s.close()
    calls.clear()
    r = auth_client.patch(f"/api/accounts/{aid}", json={"password": "new-pass", "label": "Perso"})
    assert r.status_code == 200, r.text
    assert calls == [("imap.gmail.com", 993, "me@gmail.com", "new-pass")]
    assert r.json()["status"] == "ok" and r.json()["status_message"] is None
    assert r.json()["label"] == "Perso"
    s = db_module.SessionLocal()
    assert decrypt(s.get(MailAccount, aid).secret_enc) == "new-pass"
    s.close()


def test_patch_enabled_and_bad_password(auth_client, calls, monkeypatch):
    aid = _post(auth_client).json()["id"]
    assert auth_client.patch(f"/api/accounts/{aid}", json={"enabled": False}).json()["enabled"] is False
    monkeypatch.setattr(accounts_routes, "test_connection",
                        lambda *a: (_ for _ in ()).throw(imap.MailAuthError("x")))
    assert auth_client.patch(f"/api/accounts/{aid}", json={"password": "z"}).status_code == 400
    assert auth_client.patch("/api/accounts/999", json={"enabled": True}).status_code == 404


def test_delete(auth_client, calls):
    aid = _post(auth_client).json()["id"]
    assert auth_client.delete(f"/api/accounts/{aid}").status_code == 204
    assert auth_client.get("/api/accounts").json() == []
    assert auth_client.delete(f"/api/accounts/{aid}").status_code == 404


def test_requires_auth(client):
    assert client.get("/api/accounts").status_code == 401
    assert client.post("/api/accounts", json={}, headers={"X-Requested-With": "mail-pilot"}).status_code == 401
