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


async def _test_call(token: str | None = None) -> dict:
    meta: dict = {}
    await run_claude(
        'Réponds avec {"pong": true}.',
        system="Tu réponds uniquement avec le JSON demandé.",
        schema=PONG_SCHEMA,
        model="haiku",
        timeout_s=60,
        token=token,
        meta=meta,
    )
    return meta


def _write_private(path, content: str) -> None:
    """Écriture atomique, mode 0600 (fichier temporaire du même dossier + os.replace)."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/status")
def get_status(db: Session = Depends(get_db)) -> dict:
    return status.claude_status(db, datetime.now(timezone.utc))


@router.post("/check")
async def check(db: Session = Depends(get_db)) -> dict:
    try:
        meta = await _test_call()
    except ClaudeError as e:
        await status.record_claude_failure(db, e)
        return {"ok": False, "detail": _detail(e)}
    status.record_claude_success(db, meta)
    return {"ok": True, "detail": "Claude répond."}


@router.post("/token")
async def set_token(body: TokenIn, db: Session = Depends(get_db)) -> dict:
    # le candidat est testé sans toucher au fichier courant ; écrit seulement s'il fonctionne
    try:
        meta = await _test_call(token=body.token)
    except ClaudeError as e:
        return {"ok": False, "detail": _detail(e)}
    path = get_settings().data_dir / TOKEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(path, encrypt(body.token))
    cfg = get_claude(db)
    cfg.token_set_at = datetime.now(timezone.utc)
    set_claude(db, cfg)
    status.forget_expiry(db)  # l'ancienne échéance ne vaut plus pour le nouveau jeton
    status.record_claude_success(db, meta)
    return {"ok": True, "detail": "Jeton enregistré, Claude répond."}
