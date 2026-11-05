import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.auth.deps import current_user
from app.claude import status
from app.claude.runner import TOKEN_FILE, ClaudeAuthError, ClaudeError, run_claude
from app.config import get_settings
from app.crypto import encrypt
from app.db import get_db
from app.settings_store import get_claude, set_claude

router = APIRouter(prefix="/api/claude", tags=["claude"], dependencies=[Depends(current_user)])

PONG_SCHEMA = {
    "type": "object",
    "properties": {"pong": {"type": "boolean"}},
    "required": ["pong"],
}


class TokenIn(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 4096:
            raise ValueError("jeton invalide")
        return v


def _detail(exc: Exception) -> str:
    if isinstance(exc, ClaudeAuthError):
        return "Jeton refusé : il est invalide ou expiré."
    return "Claude est injoignable ou a répondu une erreur. Réessaie plus tard."


async def _test_call() -> None:
    await run_claude(
        'Réponds avec {"pong": true}.',
        system="Tu réponds uniquement avec le JSON demandé.",
        schema=PONG_SCHEMA,
        model="haiku",
        timeout_s=60,
    )


def _write_private(path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.chmod(path, 0o600)


@router.get("/status")
def get_status(db: Session = Depends(get_db)) -> dict:
    return status.claude_status(db, datetime.now(timezone.utc))


@router.post("/check")
async def check(db: Session = Depends(get_db)) -> dict:
    try:
        await _test_call()
    except ClaudeError as e:
        await status.record_claude_failure(db, e)
        return {"ok": False, "detail": _detail(e)}
    status.record_claude_success(db)
    return {"ok": True, "detail": "Claude répond."}


@router.post("/token")
async def set_token(body: TokenIn, db: Session = Depends(get_db)) -> dict:
    path = get_settings().data_dir / TOKEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text() if path.exists() else None
    _write_private(path, encrypt(body.token))
    try:
        await _test_call()
    except ClaudeError as e:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            _write_private(path, previous)
        return {"ok": False, "detail": _detail(e)}
    except BaseException:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            _write_private(path, previous)
        raise
    cfg = get_claude(db)
    cfg.token_set_at = datetime.now(timezone.utc)
    set_claude(db, cfg)
    status.forget_expiry(db)  # l'ancienne échéance ne vaut plus pour le nouveau jeton
    status.record_claude_success(db)
    return {"ok": True, "detail": "Jeton enregistré, Claude répond."}
