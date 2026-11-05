import hashlib
import hmac
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import Session, User, utcnow

COOKIE_NAME = "mp_session"
SESSION_TTL = timedelta(days=30)
MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()
# argon2 coûte ~64 Mio par calcul : au plus HASH_CONCURRENCY en parallèle (anti-DoS mémoire
# sur /login et /setup) ; au-delà, attente brève puis HashBusy (-> 429).
HASH_CONCURRENCY = 2
HASH_WAIT_SECONDS = 5.0
_hash_slots = threading.BoundedSemaphore(HASH_CONCURRENCY)
# sérialise le premier lancement (vérification + création) : jamais deux comptes
setup_lock = threading.Lock()


class HashBusy(Exception):
    """Trop de calculs de mot de passe simultanés."""


@contextmanager
def _hash_slot():
    if not _hash_slots.acquire(timeout=HASH_WAIT_SECONDS):
        raise HashBusy
    try:
        yield
    finally:
        _hash_slots.release()
# Hash factice : verify sur identifiant inconnu coûte autant (anti-énumération par timing).
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def hash_password(password: str) -> str:
    with _hash_slot():
        return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    with _hash_slot():
        try:
            return _hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False


def setup_token_ok(expected: str, given: str | None) -> bool:
    """Comparaison en temps constant du jeton d'installation (MP_SETUP_TOKEN)."""
    return hmac.compare_digest(expected.encode(), (given or "").encode())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def user_exists(db: DbSession) -> bool:
    return (db.scalar(select(func.count()).select_from(User)) or 0) > 0


def create_user(db: DbSession, username: str, password: str, display_name: str) -> User:
    user = User(username=username, password_hash=hash_password(password), display_name=display_name)
    db.add(user)
    db.commit()
    return user


def authenticate(db: DbSession, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        verify_password(_DUMMY_HASH, password)
        return None
    return user if verify_password(user.password_hash, password) else None


def create_session(db: DbSession, user: User, user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)  # 32 octets aléatoires
    now = utcnow()
    db.add(
        Session(
            token_hash=hash_token(token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_TTL,
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    db.commit()
    return token


def resolve_session(db: DbSession, token: str | None) -> tuple[User, Session] | None:
    """Renvoie (user, session) si valide et prolonge la session (30 jours glissants)."""
    if not token:
        return None
    session = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if session is None:
        return None
    now = utcnow()
    if session.expires_at <= now:
        db.delete(session)
        db.commit()
        return None
    user = db.get(User, session.user_id)
    if user is None:
        return None
    if now - session.last_seen_at > timedelta(minutes=1):
        session.last_seen_at = now
        session.expires_at = now + SESSION_TTL
        db.commit()
    return user, session


def delete_session(db: DbSession, token: str | None) -> None:
    if not token:
        return
    session = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if session is not None:
        db.delete(session)
        db.commit()


def purge_expired(db: DbSession, now: datetime | None = None) -> None:
    now = now or utcnow()
    for s in db.scalars(select(Session).where(Session.expires_at <= now)):
        db.delete(s)
    db.commit()
