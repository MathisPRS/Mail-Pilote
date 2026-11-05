import asyncio
import os
import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.auth.deps import current_user
from app.claude import login, status
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


class CodeIn(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 512:
            raise ValueError("code invalide")
        if any(c.isspace() or unicodedata.category(c).startswith("C") for c in v):
            raise ValueError("code invalide")
        return v


class ClaudeSettingsIn(BaseModel):
    warn_days: int = Field(ge=1, le=30)


def _detail(exc: Exception) -> str:
    if isinstance(exc, ClaudeAuthError):
        return "Claude refuse la connexion : elle est invalide ou expirée."
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
    return {**status.claude_status(db, datetime.now(timezone.utc)), "warn_days": get_claude(db).warn_days}


@router.put("/settings")
def put_settings(body: ClaudeSettingsIn, db: Session = Depends(get_db)) -> dict:
    cfg = get_claude(db)
    cfg.warn_days = body.warn_days
    return {"warn_days": set_claude(db, cfg).warn_days}


@router.post("/check")
async def check(db: Session = Depends(get_db)) -> dict:
    try:
        meta = await _test_call()
    except ClaudeError as e:
        await status.record_claude_failure(db, e)
        return {"ok": False, "detail": _detail(e)}
    status.record_claude_success(db, meta)
    return {"ok": True, "detail": "Claude répond."}


async def save_tested_token(db: Session, token: str) -> tuple[bool, str]:
    """Teste le jeton candidat sans toucher au fichier courant ; l'enregistre (chiffré, 0600) s'il fonctionne."""
    try:
        meta = await _test_call(token=token)
    except ClaudeError as e:
        return False, _detail(e)
    path = get_settings().data_dir / TOKEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(path, encrypt(token))
    cfg = get_claude(db)
    cfg.token_set_at = datetime.now(timezone.utc)
    set_claude(db, cfg)
    status.forget_expiry(db)  # l'ancienne échéance ne vaut plus pour le nouveau jeton
    status.record_claude_success(db, meta)
    return True, "Jeton enregistré, Claude répond."


@router.post("/token")
async def set_token(body: TokenIn, db: Session = Depends(get_db)) -> dict:
    ok, detail = await save_tested_token(db, body.token)
    return {"ok": ok, "detail": detail}


@router.post("/login/start")
async def login_start() -> dict:
    try:
        url = await asyncio.to_thread(login.start)
    except login.LoginError as e:
        raise HTTPException(status_code=502, detail="Impossible de démarrer la connexion à Claude") from e
    return {"url": url}


@router.post("/login/complete")
async def login_complete(body: CodeIn, db: Session = Depends(get_db)) -> dict:
    try:
        token = await asyncio.to_thread(login.complete, body.code)
    except login.NoSession as e:
        raise HTTPException(status_code=409, detail="Aucune connexion en cours, recommence") from e
    except login.LoginFailed as e:
        return {"ok": False, "detail": str(e)}
    ok, detail = await save_tested_token(db, token)
    del token  # jamais renvoyé ni gardé
    return {"ok": ok, "detail": "Claude est connecté." if ok else detail}


@router.post("/login/cancel", status_code=204)
async def login_cancel() -> Response:
    await asyncio.to_thread(login.cancel)
    return Response(status_code=204)
