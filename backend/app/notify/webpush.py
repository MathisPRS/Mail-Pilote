import base64
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush

from app.config import get_settings
from app.models import PushSubscription


class SubscriptionGone(Exception):
    """L'abonnement a expiré côté service push (404/410) : à supprimer."""


ALLOWED_PUSH_HOSTS = (
    "push.apple.com",
    "fcm.googleapis.com",
    "android.googleapis.com",
    "push.services.mozilla.com",
    "notify.windows.com",
)


# Forme stricte avant tout parsing : hôte en [a-z0-9.-] seulement, puis un chemin sans
# espace, contrôle, antislash ni « # ». Sans cela, urlsplit et urllib3/requests ne voient
# pas le même hôte (ex. « https://evil.com\.fcm.googleapis.com » -> requests contacte evil.com).
_ENDPOINT_RE = re.compile(r"https://[A-Za-z0-9.-]+(?::443)?(?:/[A-Za-z0-9\-._~!$&'()*+,;=:@%/?]*)?", re.I | re.ASCII)


def is_allowed_push_endpoint(url: str) -> bool:
    """Liste blanche anti-SSRF : https, sans identifiants, port 443, hôte d'un service push connu."""
    if not _ENDPOINT_RE.fullmatch(url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme.lower() != "https" or parts.username is not None or parts.password is not None:
        return False
    if port not in (None, 443):
        return False
    host = (parts.hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_PUSH_HOSTS)


def _vapid_dir() -> Path:
    return get_settings().data_dir / "vapid"


def _vapid_private_path() -> str:
    return str(_vapid_dir() / "private_key.pem")


def _public_path() -> Path:
    return _vapid_dir() / "public_key.txt"


def ensure_vapid_keys() -> str:
    """Génère (une fois) la paire VAPID et renvoie la clé publique en base64url (applicationServerKey)."""
    directory = _vapid_dir()
    priv, pub = Path(_vapid_private_path()), _public_path()
    if priv.exists() and pub.exists():
        return pub.read_text().strip()
    directory.mkdir(parents=True, exist_ok=True)
    vapid = Vapid01()
    vapid.generate_keys()
    fd = os.open(priv, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(vapid.private_pem())
    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    fd = os.open(pub, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    return key


def _sub() -> str:
    origin = get_settings().public_origin
    return origin if origin.startswith("https://") else "mailto:admin@localhost"


def send_webpush(sub: PushSubscription, payload: dict) -> None:
    """Envoi bloquant (à appeler dans un thread). Lève SubscriptionGone sur 404/410."""
    if not is_allowed_push_endpoint(sub.endpoint):
        raise SubscriptionGone  # abonnement hors liste blanche : supprimé, aucun appel réseau
    ensure_vapid_keys()
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=_vapid_private_path(),
            vapid_claims={"sub": _sub()},
            ttl=3600,
        )
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            raise SubscriptionGone from e
        raise
