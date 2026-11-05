"""OAuth2 Google / Microsoft pour l'IMAP (XOAUTH2) : URL d'autorisation (PKCE S256), échange du code,
lecture de l'id_token, renouvellement de l'access token. Aucun jeton n'est journalisé ni renvoyé."""
import base64
import hashlib
import json
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.mail.imap import MailAuthError, MailConnectError, OAuthReconnectError

HTTP_TIMEOUT = 15
REFRESH_MARGIN = timedelta(minutes=5)
STATE_TTL = timedelta(minutes=10)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# injectable par les tests (httpx.MockTransport) ; None = réseau réel
_transport: httpx.BaseTransport | None = None


@dataclass(frozen=True)
class Provider:
    name: str  # google | microsoft
    display: str  # Google | Microsoft
    account_provider: str  # gmail | outlook
    authorize_url: str
    token_url: str
    scope: str
    extra_params: dict
    client_id: str
    client_secret: str
    tenant: str = ""

    @property
    def redirect_uri(self) -> str:
        # uniquement depuis MP_PUBLIC_ORIGIN, jamais depuis la requête
        return f"{get_settings().public_origin.rstrip('/')}/api/oauth/{self.name}/callback"


class OAuthError(Exception):
    """Échec d'un échange de jetons ; `code` est l'erreur OAuth (jamais un jeton)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def get_provider(name: str) -> Provider | None:
    """Fournisseur configuré (identifiants + MP_PUBLIC_ORIGIN), sinon None."""
    s = get_settings()
    if not s.public_origin:
        return None
    if name == "google" and s.google_client_id and s.google_client_secret:
        return Provider(
            name="google", display="Google", account_provider="gmail",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scope="openid email https://mail.google.com/",
            extra_params={"access_type": "offline", "prompt": "consent"},
            client_id=s.google_client_id, client_secret=s.google_client_secret,
        )
    if name == "microsoft" and s.ms_client_id and s.ms_client_secret:
        tenant = s.ms_tenant or "common"
        base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
        return Provider(
            name="microsoft", display="Microsoft", account_provider="outlook",
            authorize_url=f"{base}/authorize", token_url=f"{base}/token",
            scope="openid email offline_access https://outlook.office.com/IMAP.AccessAsUser.All",
            extra_params={"response_mode": "query"},
            client_id=s.ms_client_id, client_secret=s.ms_client_secret, tenant=tenant,
        )
    return None


PROVIDER_OF_ACCOUNT = {"gmail": "google", "outlook": "microsoft"}
DISPLAY_OF_ACCOUNT = {"gmail": "Google", "outlook": "Microsoft"}


def reconnect_error(account) -> OAuthReconnectError:
    return OAuthReconnectError(f"Reconnexion à {DISPLAY_OF_ACCOUNT.get(account.provider, 'votre fournisseur')} nécessaire")


# ---------- PKCE / URL ----------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_verifier() -> str:
    return secrets.token_urlsafe(64)  # 86 caractères (RFC 7636 : 43 à 128)


def challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode()).digest())


def state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def authorize_url(p: Provider, state: str, verifier: str, login_hint: str | None = None) -> str:
    params = {
        "client_id": p.client_id,
        "redirect_uri": p.redirect_uri,
        "response_type": "code",
        "scope": p.scope,
        "state": state,
        "code_challenge": challenge(verifier),
        "code_challenge_method": "S256",
        **p.extra_params,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{p.authorize_url}?{urlencode(params)}"


# ---------- endpoint de jetons ----------

@dataclass
class Tokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    id_token: str | None
    scope: str | None = None  # droits réellement accordés (Google : l'utilisateur peut décocher)


def _token_request(p: Provider, data: dict) -> Tokens:
    form = {**data, "client_id": p.client_id, "client_secret": p.client_secret}
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, transport=_transport) as c:
            r = c.post(p.token_url, data=form, headers={"Accept": "application/json"})
    except httpx.HTTPError:
        raise OAuthError("network") from None
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if r.status_code != 200:
        raise OAuthError(str(body.get("error") or f"http_{r.status_code}")[:64])
    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        raise OAuthError("no_access_token")
    try:
        expires_in = int(body.get("expires_in", 3600))
    except (TypeError, ValueError):
        expires_in = 3600
    refresh = body.get("refresh_token")
    return Tokens(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=max(expires_in, 0)),
        id_token=body.get("id_token") if isinstance(body.get("id_token"), str) else None,
        scope=body.get("scope") if isinstance(body.get("scope"), str) else None,
    )


GOOGLE_MAIL_SCOPE = "https://mail.google.com/"


def mail_scope_missing(p: Provider, tokens: Tokens) -> bool:
    """Google laisse décocher l'accès Gmail sur l'écran de consentement : sans lui, IMAP refuse."""
    if p.name != "google" or tokens.scope is None:
        return False
    return GOOGLE_MAIL_SCOPE not in tokens.scope.split()


def exchange_code(p: Provider, code: str, verifier: str) -> Tokens:
    data = {
        "grant_type": "authorization_code", "code": code, "redirect_uri": p.redirect_uri,
        "code_verifier": verifier,
    }
    if p.name == "microsoft":
        data["scope"] = p.scope
    tokens = _token_request(p, data)
    if not tokens.refresh_token or not tokens.id_token:
        raise OAuthError("incomplete")
    return tokens


def refresh(p: Provider, refresh_token: str) -> Tokens:
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    if p.name == "microsoft":
        # v2.0 : sans scope, l'access token renouvelé peut ne pas viser outlook.office.com (IMAP)
        data["scope"] = p.scope
    return _token_request(p, data)


def email_from_id_token(p: Provider, id_token: str) -> str:
    """id_token reçu directement de l'endpoint de jetons en TLS : signature non vérifiée, mais aud/iss oui."""
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise OAuthError("id_token") from None
    if not isinstance(claims, dict):
        raise OAuthError("id_token")
    aud = claims.get("aud")
    if aud != p.client_id and not (isinstance(aud, list) and p.client_id in aud):
        raise OAuthError("id_token_aud")
    iss = claims.get("iss")
    if p.name == "google":
        if iss not in ("https://accounts.google.com", "accounts.google.com"):
            raise OAuthError("id_token_iss")
        verified = claims.get("email_verified")
        if verified is False or (isinstance(verified, str) and verified.strip().lower() == "false"):
            raise OAuthError("id_token_email")
        email = claims.get("email")
    else:
        tid = claims.get("tid")
        if not isinstance(tid, str) or iss != f"https://login.microsoftonline.com/{tid}/v2.0":
            raise OAuthError("id_token_iss")
        if GUID_RE.match(p.tenant) and tid.lower() != p.tenant.lower():
            raise OAuthError("id_token_iss")
        email = claims.get("email") or claims.get("preferred_username")
    if not isinstance(email, str):
        raise OAuthError("id_token_email")
    email = email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise OAuthError("id_token_email")
    return email


# ---------- access token d'un compte (session IMAP) ----------

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(account_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(account_id, threading.Lock())


def access_token_for(account) -> str:
    """Access token valide pour la boîte ; renouvelé (et stocké) s'il expire dans moins de 5 min."""
    from app import db as db_module
    from app.crypto import decrypt, encrypt
    from app.models import MailAccount

    p = get_provider(PROVIDER_OF_ACCOUNT.get(account.provider, ""))
    with _lock_for(account.id):
        with db_module.SessionLocal() as s:
            row = s.get(MailAccount, account.id)
            if row is None or not row.oauth_refresh_enc:
                raise reconnect_error(account)
            now = datetime.now(timezone.utc)
            if row.oauth_access_enc and row.oauth_expires_at and row.oauth_expires_at - now > REFRESH_MARGIN:
                token = decrypt(row.oauth_access_enc)
            else:
                if p is None:
                    raise MailAuthError("Connexion OAuth non configurée sur le serveur")
                try:
                    fresh = refresh(p, decrypt(row.oauth_refresh_enc))
                except OAuthError as e:
                    if e.code == "invalid_grant":
                        raise reconnect_error(account) from None
                    if e.code == "network" or e.code.startswith("http_5"):
                        raise MailConnectError("Serveur d'authentification injoignable") from None
                    raise MailAuthError("Jeton refusé par le fournisseur") from None
                token = fresh.access_token
                row.oauth_access_enc = encrypt(token)
                row.oauth_expires_at = fresh.expires_at
                if fresh.refresh_token:  # rotation du refresh token
                    row.oauth_refresh_enc = encrypt(fresh.refresh_token)
                s.commit()
            values = {
                "oauth_access_enc": row.oauth_access_enc,
                "oauth_refresh_enc": row.oauth_refresh_enc,
                "oauth_expires_at": row.oauth_expires_at,
            }
    for k, v in values.items():  # garde l'objet appelant cohérent (copie détachée ou attachée)
        if getattr(account, k, None) != v:
            setattr(account, k, v)
    return token
