import pytest

from app import db as db_module
from app.crypto import decrypt
from app.mail import accounts_routes, imap
from app.models import MailAccount


REAL_START = getattr(accounts_routes, "start_first_analysis", None)


@pytest.fixture(autouse=True)
def first_analysis(monkeypatch):
    """Jamais de vraie synchro IMAP en test : le lancement de l'analyse est enregistré, pas exécuté."""
    started = []
    monkeypatch.setattr(accounts_routes, "start_first_analysis", lambda: started.append("light"), raising=False)
    return started


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


def test_validation_error_does_not_echo_password(auth_client, calls):
    r = auth_client.post("/api/accounts", json={"email": "a@b.fr", "password": "SuperSecret-xyz"})
    assert r.status_code == 422
    assert "SuperSecret-xyz" not in r.text
    assert "input" not in r.json()["detail"][0]


def test_login_validation_error_does_not_echo_password(client):
    r = client.post("/api/auth/login", json={"password": "SuperSecret-xyz"},
                    headers={"X-Requested-With": "mail-pilot"})
    assert r.status_code == 422
    assert "SuperSecret-xyz" not in r.text


def test_invalid_email_422(auth_client, calls):
    assert _post(auth_client, email="not-an-email").status_code == 422
    assert _post(auth_client, email="a@b").status_code == 422


def test_duplicate_email_case_insensitive_409(auth_client, calls):
    assert _post(auth_client, email="Me@Gmail.com ").json()["email"] == "me@gmail.com"
    assert _post(auth_client, email="ME@gmail.com").status_code == 409


def test_empty_label_422(auth_client, calls):
    assert _post(auth_client, label="  ").status_code == 422
    aid = _post(auth_client).json()["id"]
    assert auth_client.patch(f"/api/accounts/{aid}", json={"label": ""}).status_code == 422


def test_max_lengths_and_empty_imap_host(auth_client, calls):
    assert _post(auth_client, label="x" * 61).status_code == 422
    assert _post(auth_client, password="x" * 1025).status_code == 422
    assert _post(auth_client, provider="imap", imap_host="  ").status_code == 422


def test_new_box_starts_background_light_run(auth_client, calls, monkeypatch):
    """Premier lancement : ajouter une boîte synchronise et analyse aussitôt (sans attendre la route)."""
    import asyncio

    from app.analysis import jobs
    from app.models import AnalysisRun, utcnow

    monkeypatch.setattr(accounts_routes, "start_first_analysis", REAL_START)
    started = []

    async def fake_light(s, trigger="schedule"):
        started.append(trigger)
        r = AnalysisRun(kind="light", trigger=trigger, status="running")
        s.add(r)
        s.commit()
        await asyncio.sleep(0)
        r.status, r.finished_at = "ok", utcnow()
        s.commit()
        return r

    monkeypatch.setattr(jobs, "run_light", fake_light)
    assert _post(auth_client).status_code == 201
    for _ in range(50):  # la tâche de fond tourne sur la boucle du serveur de test
        latest = auth_client.get("/api/runs/latest").json()
        if latest["light"]:
            break
    assert started == ["manual"] and latest["light"]["trigger"] == "manual"


def test_failed_box_creation_starts_nothing(auth_client, monkeypatch, first_analysis):
    def boom(*a):
        raise imap.MailAuthError("x")

    monkeypatch.setattr(accounts_routes, "test_connection", boom)
    assert _post(auth_client).status_code == 400
    assert first_analysis == []
