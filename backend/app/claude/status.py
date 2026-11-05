import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.claude import runner
from app.claude.runner import ClaudeAuthError
from app.models import KV
from app.notify import dispatcher
from app.settings_store import get_claude

DEFAULT_VALIDITY = timedelta(days=365)  # setup-token : ~1 an
EXPIRES_KEY = "claude_credential_expires_at"


def _kv_get(db: Session, key: str) -> str | None:
    row = db.get(KV, key)
    return json.loads(row.value_json) if row else None


def _kv_set(db: Session, key: str, value: str) -> None:
    payload = json.dumps(value)
    row = db.get(KV, key)
    if row:
        row.value_json = payload
    else:
        db.add(KV(key=key, value_json=payload))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def forget_expiry(db: Session) -> None:
    row = db.get(KV, EXPIRES_KEY)
    if row:
        db.delete(row)
        db.commit()


def record_claude_success(db: Session) -> None:
    _kv_set(db, "claude_last_ok_at", datetime.now(timezone.utc).isoformat())
    exp = _parse(runner.last_meta.get("credential_expires_at"))
    if exp:
        _kv_set(db, EXPIRES_KEY, exp.isoformat())
    db.commit()


async def record_claude_failure(db: Session, exc: Exception) -> None:
    _kv_set(db, "claude_last_error", str(exc)[:500])
    _kv_set(db, "claude_last_error_at", datetime.now(timezone.utc).isoformat())
    db.commit()
    if isinstance(exc, ClaudeAuthError):
        await dispatcher.send_system_alert(
            db,
            title="Claude déconnecté",
            body="Le jeton Claude est invalide ou expiré. Reconnecte-le dans les réglages.",
            key="claude-auth",
        )


def _expires_at(db: Session) -> datetime | None:
    exp = _parse(_kv_get(db, EXPIRES_KEY))
    if exp:
        return exp
    set_at = get_claude(db).token_set_at
    return _aware(set_at) + DEFAULT_VALIDITY if set_at else None


def claude_status(db: Session, now: datetime) -> dict:
    ok = _parse(_kv_get(db, "claude_last_ok_at"))
    err_at = _parse(_kv_get(db, "claude_last_error_at"))
    connected = ok is not None and (err_at is None or ok > err_at)
    expires = _expires_at(db)
    set_at = get_claude(db).token_set_at
    return {
        "connected": connected,
        "last_ok_at": ok.isoformat() if ok else None,
        "last_error": None if connected else _kv_get(db, "claude_last_error"),
        "token_set_at": _aware(set_at).isoformat() if set_at else None,
        "expires_at": expires.isoformat() if expires else None,
        "days_left": (expires - _aware(now)) // timedelta(days=1) if expires else None,
    }


async def check_expiry(db: Session, now: datetime) -> bool:
    st = claude_status(db, now)
    if st["days_left"] is None or st["days_left"] > get_claude(db).warn_days:
        return False
    day = st["expires_at"][:10]
    n = st["days_left"]
    return await dispatcher.send_system_alert(
        db,
        title="Jeton Claude bientôt expiré",
        body=f"Le jeton Claude expire dans {max(n, 0)} jour(s). Colle un nouveau jeton dans les réglages.",
        key=f"claude-expiry-{day}",
    )
