import hashlib
import secrets
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
# Hash factice : verify sur identifiant inconnu coûte autant (anti-énumération par timing).
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


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
