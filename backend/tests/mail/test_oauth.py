"""Connexion Google / Microsoft (OAuth2 + IMAP XOAUTH2). Réseau simulé (httpx.MockTransport), IMAP simulé."""
import base64
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app import db as db_module
from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.mail import accounts_routes, oauth, oauth_routes
from app.mail.sync import sync_all
from app.models import MailAccount, OAuthState

ORIGIN = "https://mail.exemple.fr"
G_ID, G_SECRET = "g-client-id.apps.googleusercontent.com", "g-client-secret-XYZ"
MS_ID, MS_SECRET = "ms-client-id-0000", "ms-client-secret-XYZ"
MS_TID = "9188040d-6c67-4c5b-b112-36a304b66dad"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def id_token(**claims) -> str:
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps(claims).encode())
    return f"{header}.{payload}.{b64url(b'signature')}"


def google_claims(email="Me@Gmail.com", **over):
    c = {"iss": "https://accounts.google.com", "aud": G_ID, "email": email, "email_verified": True,
         "sub": "123"}
    c.update(over)
    return c


def ms_claims(username="Me@Outlook.fr", **over):
    c = {"iss": f"https://login.microsoftonline.com/{MS_TID}/v2.0", "aud": MS_ID, "tid": MS_TID,
         "preferred_username": username}
    c.update(over)
    return c


@pytest.fixture
def oauth_env(settings, monkeypatch):
    monkeypatch.setenv("MP_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", G_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", G_SECRET)
    monkeypatch.setenv("MS_CLIENT_ID", MS_ID)
    monkeypatch.setenv("MS_CLIENT_SECRET", MS_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TokenServer:
    """Faux endpoint de jetons : file de réponses, requêtes enregistrées."""

    def __init__(self):
        self.responses: list[httpx.Response] = []
        self.requests: list[tuple[str, dict]] = []

    def push(self, status=200, **body):
        self.responses.append(httpx.Response(status, json=body))

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.requests.append((str(request.url), form))
        if not self.responses:
            raise AssertionError("requête de jetons inattendue")
        return self.responses.pop(0)


@pytest.fixture
def tokens(monkeypatch):
    server = TokenServer()
    monkeypatch.setattr(oauth, "_transport", httpx.MockTransport(server.handler))
    return server


@pytest.fixture
def imap_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(oauth_routes, "test_oauth_connection", lambda *a: calls.append(a))
    return calls


@pytest.fixture
def started(monkeypatch):
    out = []
    monkeypatch.setattr(accounts_routes, "start_first_analysis", lambda: out.append("light"))
    return out


def start(c, provider="google", **body):
    r = c.post(f"/api/oauth/{provider}/start", json=body)
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    return url, {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def callback(c, provider="google", **params):
    return c.get(f"/api/oauth/{provider}/callback", params=params, follow_redirects=False)


def reason(r) -> str:
    assert r.status_code == 303, r.text
    return r.headers["location"]


ERR = "/settings/boxes?oauth=error&reason="
OK = "/settings/boxes?oauth=ok"


def g_tokens(tokens, email="Me@Gmail.com", access="ya29.ACCESS-1", refresh="1//REFRESH-1", **claims):
    tokens.push(access_token=access, refresh_token=refresh, expires_in=3599, token_type="Bearer",
                id_token=id_token(**google_claims(email, **claims)))


def connect_google(c, tokens, **kw):
    _, q = start(c)
    g_tokens(tokens, **kw)
    return callback(c, code="auth-code-1", state=q["state"])


# ---------- /providers ----------

def test_providers_requires_session(client):
    assert client.get("/api/oauth/providers").status_code == 401


def test_providers_lists_only_configured(auth_client, settings, monkeypatch):
    monkeypatch.setenv("MP_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", G_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", G_SECRET)
    monkeypatch.delenv("MS_CLIENT_ID", raising=False)
    get_settings.cache_clear()
    assert auth_client.get("/api/oauth/providers").json() == {"google": True, "microsoft": False}
    assert auth_client.post("/api/oauth/microsoft/start", json={}).status_code == 404
    assert auth_client.post("/api/oauth/yahoo/start", json={}).status_code == 404


def test_nothing_configured(auth_client):
    assert auth_client.get("/api/oauth/providers").json() == {"google": False, "microsoft": False}
    assert auth_client.post("/api/oauth/google/start", json={}).status_code == 404


# ---------- /start ----------

def test_start_google_url(auth_client, oauth_env, db):
    url, q = start(auth_client)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["client_id"] == G_ID
    assert q["redirect_uri"] == f"{ORIGIN}/api/oauth/google/callback"
    assert q["response_type"] == "code"
    assert q["scope"] == "openid email https://mail.google.com/"
    assert q["access_type"] == "offline"
    assert q["prompt"] == "consent"
    assert q["code_challenge_method"] == "S256"
    assert len(q["code_challenge"]) == 43
    assert len(q["state"]) >= 43
    assert G_SECRET not in url
    row = db.query(OAuthState).one()
    assert row.state_hash != q["state"] and q["state"] not in row.verifier_enc  # rien en clair
    verifier = decrypt(row.verifier_enc)
    assert b64url(hashlib.sha256(verifier.encode()).digest()) == q["code_challenge"]
    assert row.account_id is None and row.provider == "google"


def test_start_redirect_uri_ignores_request_host(auth_client, oauth_env):
    r = auth_client.post("/api/oauth/google/start", json={}, headers={"Host": "evil.example"})
    q = parse_qs(urlsplit(r.json()["url"]).query)
    assert q["redirect_uri"] == [f"{ORIGIN}/api/oauth/google/callback"]


def test_start_microsoft_url(auth_client, oauth_env):
    url, q = start(auth_client, "microsoft")
    assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert q["client_id"] == MS_ID
    assert q["redirect_uri"] == f"{ORIGIN}/api/oauth/microsoft/callback"
    assert q["scope"] == "openid email offline_access https://outlook.office.com/IMAP.AccessAsUser.All"
    assert q["code_challenge_method"] == "S256"


def test_start_requires_session_and_csrf(client, oauth_env):
    assert client.post("/api/oauth/google/start", json={}).status_code == 403  # CSRF d'abord
    client.headers["X-Requested-With"] = "mail-pilot"
    assert client.post("/api/oauth/google/start", json={}).status_code == 401


def test_start_reconnect_unknown_account_404(auth_client, oauth_env):
    assert auth_client.post("/api/oauth/google/start", json={"account_id": 99}).status_code == 404


# ---------- /callback : state ----------

def test_callback_unknown_state(auth_client, oauth_env, tokens):
    assert reason(callback(auth_client, code="x", state="inconnu")) == ERR + "state"
    assert reason(callback(auth_client, code="x")) == ERR + "state"
    assert tokens.requests == []


def test_callback_expired_state(auth_client, oauth_env, tokens, db):
    _, q = start(auth_client)
    row = db.query(OAuthState).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert reason(callback(auth_client, code="x", state=q["state"])) == ERR + "state"
    assert tokens.requests == []


def test_callback_state_is_single_use(auth_client, oauth_env, tokens, imap_checks, started):
    _, q = start(auth_client)
    g_tokens(tokens)
    assert reason(callback(auth_client, code="c", state=q["state"])) == OK
    assert reason(callback(auth_client, code="c", state=q["state"])) == ERR + "state"
    assert len(tokens.requests) == 1


def test_callback_state_bound_to_provider(auth_client, oauth_env, tokens, db):
    _, q = start(auth_client, "google")
    assert reason(callback(auth_client, "microsoft", code="c", state=q["state"])) == ERR + "state"
    assert tokens.requests == []


def test_callback_works_without_cookie(client, auth_client, oauth_env, tokens, imap_checks, started):
    """Retour depuis Google : le cookie SameSite=Strict n'est pas envoyé."""
    _, q = start(auth_client)
    g_tokens(tokens)
    auth_client.cookies.clear()
    assert reason(callback(auth_client, code="c", state=q["state"])) == OK


def test_callback_access_denied(auth_client, oauth_env, tokens, db):
    _, q = start(auth_client)
    assert reason(callback(auth_client, error="access_denied", state=q["state"])) == ERR + "denied"
    assert tokens.requests == []
    assert db.query(OAuthState).count() == 0  # state consommé


# ---------- /callback : succès ----------

def test_callback_creates_google_account(auth_client, oauth_env, tokens, imap_checks, started, db, caplog):
    caplog.set_level(logging.DEBUG)
    _, q = start(auth_client)
    g_tokens(tokens)
    r = callback(auth_client, code="auth-code-1", state=q["state"])
    assert reason(r) == OK
    url, form = tokens.requests[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "auth-code-1"
    assert form["redirect_uri"] == f"{ORIGIN}/api/oauth/google/callback"
    assert form["client_id"] == G_ID and form["client_secret"] == G_SECRET
    assert b64url(hashlib.sha256(form["code_verifier"].encode()).digest()) == q["code_challenge"]
    assert imap_checks == [("imap.gmail.com", 993, "me@gmail.com", "ya29.ACCESS-1")]
    assert started == ["light"]

    acc = db.query(MailAccount).one()
    assert (acc.provider, acc.auth_type, acc.email, acc.username) == ("gmail", "oauth", "me@gmail.com", "me@gmail.com")
    assert (acc.label, acc.color, acc.imap_host, acc.imap_port) == ("Gmail", "#D93025", "imap.gmail.com", 993)
    assert decrypt(acc.oauth_access_enc) == "ya29.ACCESS-1"
    assert decrypt(acc.oauth_refresh_enc) == "1//REFRESH-1"
    assert "REFRESH" not in acc.oauth_refresh_enc and "ACCESS" not in acc.oauth_access_enc
    assert acc.oauth_expires_at > datetime.now(timezone.utc) + timedelta(minutes=55)

    listed = auth_client.get("/api/accounts").json()
    assert listed[0]["auth_type"] == "oauth"
    raw = json.dumps(listed)
    for secret in ("ACCESS", "REFRESH", "oauth_", "secret"):
        assert secret not in raw
    # journaux du serveur (hors client de test, qui joue le navigateur)
    server_logs = "\n".join(rec.getMessage() for rec in caplog.records if rec.name != "httpx2")
    for secret in ("auth-code-1", "ACCESS-1", "REFRESH-1", G_SECRET, q["state"]):
        assert secret not in server_logs
        assert secret not in r.headers["location"]


def test_access_log_redacts_oauth_query():
    from app.main import create_app

    create_app()
    access = logging.getLogger("uvicorn.access")
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", "/api/oauth/google/callback?code=SECRET&state=S2", "1.1", 303), None)
    assert all(f.filter(rec) for f in access.filters)
    assert "SECRET" not in rec.getMessage() and "S2" not in rec.getMessage()
    assert "/api/oauth/google/callback" in rec.getMessage()
    other = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                              ("1.2.3.4:5", "GET", "/api/messages?folder=inbox", "1.1", 200), None)
    assert all(f.filter(other) for f in access.filters)
    assert "folder=inbox" in other.getMessage()


def test_callback_creates_outlook_account(auth_client, oauth_env, tokens, imap_checks, started, db):
    _, q = start(auth_client, "microsoft")
    tokens.push(access_token="EwB-ms-access", refresh_token="M.R3-refresh", expires_in=3600,
                id_token=id_token(**ms_claims()))
    assert reason(callback(auth_client, "microsoft", code="c", state=q["state"])) == OK
    url, form = tokens.requests[0]
    assert url == "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    assert form["client_secret"] == MS_SECRET and form["code_verifier"]
    assert imap_checks == [("outlook.office365.com", 993, "me@outlook.fr", "EwB-ms-access")]
    acc = db.query(MailAccount).one()
    assert (acc.provider, acc.label, acc.color, acc.auth_type) == ("outlook", "Outlook", "#0F6CBD", "oauth")


@pytest.mark.parametrize("claims", [{"aud": "autre-client"}, {"iss": "https://evil.example"}])
def test_callback_rejects_bad_id_token(auth_client, oauth_env, tokens, imap_checks, started, db, claims):
    _, q = start(auth_client)
    g_tokens(tokens, **claims)
    assert reason(callback(auth_client, code="c", state=q["state"])) == ERR + "exchange"
    assert db.query(MailAccount).count() == 0 and imap_checks == []


def test_callback_ms_rejects_wrong_issuer(auth_client, oauth_env, tokens, imap_checks, db):
    _, q = start(auth_client, "microsoft")
    tokens.push(access_token="a", refresh_token="r", expires_in=3600,
                id_token=id_token(**ms_claims(iss="https://login.microsoftonline.com/autre/v2.0")))
    assert reason(callback(auth_client, "microsoft", code="c", state=q["state"])) == ERR + "exchange"


def test_callback_exchange_refused(auth_client, oauth_env, tokens, imap_checks, db):
    _, q = start(auth_client)
    tokens.push(400, error="invalid_grant")
    assert reason(callback(auth_client, code="c", state=q["state"])) == ERR + "exchange"
    assert db.query(MailAccount).count() == 0


def test_callback_exchange_network_error(auth_client, oauth_env, monkeypatch, imap_checks, db):
    def boom(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(oauth, "_transport", httpx.MockTransport(boom))
    _, q = start(auth_client)
    assert reason(callback(auth_client, code="c", state=q["state"])) == ERR + "exchange"


def test_callback_duplicate(auth_client, oauth_env, tokens, imap_checks, started, db):
    assert reason(connect_google(auth_client, tokens)) == OK
    assert reason(connect_google(auth_client, tokens, email="ME@gmail.com")) == ERR + "duplicate"
    assert db.query(MailAccount).count() == 1


def test_callback_imap_refused(auth_client, oauth_env, tokens, monkeypatch, started, db):
    from app.mail.imap import MailAuthError

    def refuse(*a):
        raise MailAuthError("no")

    monkeypatch.setattr(oauth_routes, "test_oauth_connection", refuse)
    assert reason(connect_google(auth_client, tokens)) == ERR + "imap"
    assert db.query(MailAccount).count() == 0 and started == []


def test_reconnect_updates_tokens(auth_client, oauth_env, tokens, imap_checks, started, db):
    assert reason(connect_google(auth_client, tokens)) == OK
    acc = db.query(MailAccount).one()
    acc.status, acc.status_message = "error", "Reconnexion à Google nécessaire"
    db.commit()
    url, q = start(auth_client, account_id=acc.id)
    assert q["login_hint"] == "me@gmail.com"
    g_tokens(tokens, access="ya29.ACCESS-2", refresh="1//REFRESH-2")
    assert reason(callback(auth_client, code="c2", state=q["state"])) == OK
    db.expire_all()
    acc = db.query(MailAccount).one()
    assert decrypt(acc.oauth_access_enc) == "ya29.ACCESS-2"
    assert decrypt(acc.oauth_refresh_enc) == "1//REFRESH-2"
    assert (acc.status, acc.status_message) == ("ok", None)


def test_reconnect_email_mismatch(auth_client, oauth_env, tokens, imap_checks, started, db):
    assert reason(connect_google(auth_client, tokens)) == OK
    acc = db.query(MailAccount).one()
    _, q = start(auth_client, account_id=acc.id)
    g_tokens(tokens, email="other@gmail.com", access="ya29.OTHER", refresh="1//OTHER")
    assert reason(callback(auth_client, code="c2", state=q["state"])) == ERR + "mismatch"
    db.expire_all()
    acc = db.query(MailAccount).one()
    assert decrypt(acc.oauth_access_enc) == "ya29.ACCESS-1"
    assert db.query(MailAccount).count() == 1


def test_reconnect_wrong_provider_404(auth_client, oauth_env, tokens, imap_checks, started, db):
    assert reason(connect_google(auth_client, tokens)) == OK
    acc_id = db.query(MailAccount).one().id
    assert auth_client.post("/api/oauth/microsoft/start", json={"account_id": acc_id}).status_code == 404


def test_patch_password_refused_on_oauth_account(auth_client, oauth_env, tokens, imap_checks, started, db):
    assert reason(connect_google(auth_client, tokens)) == OK
    acc_id = db.query(MailAccount).one().id
    r = auth_client.patch(f"/api/accounts/{acc_id}", json={"password": "x"})
    assert r.status_code == 400


# ---------- session IMAP d'un compte OAuth ----------

def _oauth_account(db, provider="gmail", expires_in=timedelta(hours=1)):
    host = {"gmail": "imap.gmail.com", "outlook": "outlook.office365.com"}[provider]
    acc = MailAccount(
        provider=provider, label="X", email="me@x.com", imap_host=host, imap_port=993,
        username="me@x.com", secret_enc="", auth_type="oauth",
        oauth_access_enc=encrypt("OLD-ACCESS"), oauth_refresh_enc=encrypt("OLD-REFRESH"),
        oauth_expires_at=datetime.now(timezone.utc) + expires_in,
    )
    db.add(acc)
    db.commit()
    return acc


@pytest.fixture
def imap_client(monkeypatch):
    import imapclient

    instance = MagicMock()
    factory = MagicMock(return_value=instance)
    monkeypatch.setattr(imapclient, "IMAPClient", factory)
    return instance


def test_open_session_uses_xoauth2_without_refresh(db, oauth_env, tokens, imap_client):
    from app.mail.imap import open_session

    acc = _oauth_account(db)
    open_session(acc)
    imap_client.oauth2_login.assert_called_once_with("me@x.com", "OLD-ACCESS")
    imap_client.login.assert_not_called()
    assert tokens.requests == []


def test_open_session_refreshes_and_rotates(db, oauth_env, tokens, imap_client):
    from app.mail.imap import open_session

    acc = _oauth_account(db, expires_in=timedelta(minutes=2))
    tokens.push(access_token="NEW-ACCESS", refresh_token="NEW-REFRESH", expires_in=3600)
    open_session(acc)
    url, form = tokens.requests[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert form == {"grant_type": "refresh_token", "refresh_token": "OLD-REFRESH",
                    "client_id": G_ID, "client_secret": G_SECRET}
    imap_client.oauth2_login.assert_called_once_with("me@x.com", "NEW-ACCESS")
    imap_client.login.assert_not_called()
    with db_module.SessionLocal() as s:
        row = s.get(MailAccount, acc.id)
        assert decrypt(row.oauth_access_enc) == "NEW-ACCESS"
        assert decrypt(row.oauth_refresh_enc) == "NEW-REFRESH"
        assert row.oauth_expires_at > datetime.now(timezone.utc) + timedelta(minutes=55)


def test_refresh_keeps_refresh_token_when_not_rotated(db, oauth_env, tokens, imap_client):
    from app.mail.imap import open_session

    acc = _oauth_account(db, expires_in=timedelta(minutes=-5))
    tokens.push(access_token="NEW-ACCESS", expires_in=3600)
    open_session(acc)
    with db_module.SessionLocal() as s:
        assert decrypt(s.get(MailAccount, acc.id).oauth_refresh_enc) == "OLD-REFRESH"


@pytest.mark.parametrize("provider,name", [("gmail", "Google"), ("outlook", "Microsoft")])
def test_invalid_grant_marks_account_error(db, oauth_env, tokens, imap_client, provider, name):
    acc = _oauth_account(db, provider=provider, expires_in=timedelta(minutes=1))
    tokens.push(400, error="invalid_grant", error_description="Token has been expired or revoked.")
    sync_all(db)
    db.refresh(acc)
    assert (acc.status, acc.status_message) == ("error", f"Reconnexion à {name} nécessaire")
    imap_client.oauth2_login.assert_not_called()


def test_password_account_still_uses_login(db, settings, imap_client):
    from app.mail.imap import open_session

    acc = MailAccount(provider="icloud", label="i", email="a@icloud.com", imap_host="imap.mail.me.com",
                      username="a@icloud.com", secret_enc=encrypt("pw"))
    db.add(acc)
    db.commit()
    open_session(acc)
    imap_client.login.assert_called_once_with("a@icloud.com", "pw")
    imap_client.oauth2_login.assert_not_called()


# ---------- migration ----------

def test_init_db_adds_columns_to_existing_database(settings):
    path = settings.data_dir / "old.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE mail_accounts (id INTEGER PRIMARY KEY, provider VARCHAR NOT NULL, label VARCHAR NOT NULL,"
        " email VARCHAR NOT NULL, imap_host VARCHAR NOT NULL, imap_port INTEGER NOT NULL,"
        " username VARCHAR NOT NULL, secret_enc VARCHAR NOT NULL, enabled BOOLEAN NOT NULL,"
        " status VARCHAR NOT NULL, status_message VARCHAR, last_sync_at DATETIME, color VARCHAR)"
    )
    con.execute(
        "INSERT INTO mail_accounts VALUES (1, 'gmail', 'Gmail', 'a@gmail.com', 'imap.gmail.com', 993,"
        " 'a@gmail.com', 'x', 1, 'ok', NULL, NULL, '#D93025')"
    )
    con.commit()
    con.close()
    db_module.configure(f"sqlite:///{path}")
    try:
        db_module.init_db()
        db_module.init_db()  # idempotent
        with db_module.SessionLocal() as s:
            acc = s.get(MailAccount, 1)
            assert acc.auth_type == "password"
            assert acc.oauth_refresh_enc is None and acc.oauth_access_enc is None
            assert acc.oauth_expires_at is None
            assert s.query(OAuthState).count() == 0
    finally:
        db_module.dispose()
