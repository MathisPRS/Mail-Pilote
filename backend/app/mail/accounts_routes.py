import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api import runs as runs_api
from app.auth.deps import current_user
from app.crypto import encrypt
from app.db import get_db
from app.mail.imap import MailAuthError, MailConnectError, test_connection
from app.mail.providers import PRESETS
from app.models import Folder, MailAccount, Message

router = APIRouter(prefix="/api/accounts", tags=["accounts"], dependencies=[Depends(current_user)])

COLORS = {"gmail": "#D93025", "icloud": "#3A9BDC", "imap": "#B88A00"}
LABELS = {"gmail": "Gmail", "icloud": "iCloud", "imap": "IMAP"}


class AccountOut(BaseModel):
    id: int
    provider: str
    label: str
    email: str
    enabled: bool
    status: str
    status_message: str | None
    last_sync_at: str | None
    color: str | None

    @classmethod
    def of(cls, a: MailAccount) -> "AccountOut":
        return cls(
            id=a.id, provider=a.provider, label=a.label, email=a.email, enabled=a.enabled,
            status=a.status, status_message=a.status_message,
            last_sync_at=a.last_sync_at.isoformat() if a.last_sync_at else None, color=a.color,
        )


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_label(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        raise ValueError("label vide")
    return v


class AccountCreate(BaseModel):
    provider: Literal["gmail", "icloud", "imap"]
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=1024)
    imap_host: str | None = Field(default=None, max_length=253)
    imap_port: int = Field(default=993, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=254)
    label: str | None = Field(default=None, max_length=60)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("adresse e-mail invalide")
        return v

    @field_validator("imap_host", "username")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None

    _label = field_validator("label")(lambda cls, v: _clean_label(v))


class AccountPatch(BaseModel):
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    label: str | None = Field(default=None, max_length=60)

    _label = field_validator("label")(lambda cls, v: _clean_label(v))


async def _check(host: str, port: int, username: str, password: str) -> None:
    try:
        await run_in_threadpool(test_connection, host, port, username, password)
    except MailAuthError:
        raise HTTPException(400, "Identifiants refusés par le serveur")
    except MailConnectError:
        raise HTTPException(400, "Serveur injoignable")


@router.get("")
def list_accounts(db: Session = Depends(get_db)) -> list[AccountOut]:
    rows = db.scalars(select(MailAccount).order_by(MailAccount.id)).all()
    return [AccountOut.of(a) for a in rows]


def start_first_analysis() -> None:
    """Nouvelle boîte : synchro + vérification légère tout de suite, en tâche de fond."""
    runs_api.start_background("light")


@router.post("", status_code=201)
async def create_account(body: AccountCreate, db: Session = Depends(get_db)) -> AccountOut:
    if body.provider == "imap":
        if not body.imap_host:
            raise HTTPException(422, "imap_host requis pour un compte IMAP")
        host, port = body.imap_host, body.imap_port
        username = body.username or body.email
    else:
        host, port = PRESETS[body.provider]
        username = body.email
    dup = db.scalar(
        select(MailAccount).where(
            MailAccount.provider == body.provider, MailAccount.email == body.email
        )
    )
    if dup:
        raise HTTPException(409, "Cette boîte est déjà configurée")
    await _check(host, port, username, body.password)
    acc = MailAccount(
        provider=body.provider, label=body.label or LABELS[body.provider], email=body.email,
        imap_host=host, imap_port=port, username=username, secret_enc=encrypt(body.password),
        color=COLORS[body.provider],
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    start_first_analysis()
    return AccountOut.of(acc)


def _get(db: Session, account_id: int) -> MailAccount:
    acc = db.get(MailAccount, account_id)
    if acc is None:
        raise HTTPException(404, "Compte introuvable")
    return acc


@router.patch("/{account_id}")
async def patch_account(
    account_id: int, body: AccountPatch, db: Session = Depends(get_db)
) -> AccountOut:
    acc = _get(db, account_id)
    if body.password is not None:
        await _check(acc.imap_host, acc.imap_port, acc.username, body.password)
        acc.secret_enc = encrypt(body.password)
        acc.status, acc.status_message = "ok", None
    if body.enabled is not None:
        acc.enabled = body.enabled
    if body.label is not None:
        acc.label = body.label
    db.commit()
    db.refresh(acc)
    return AccountOut.of(acc)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db)) -> Response:
    acc = _get(db, account_id)
    db.execute(delete(Message).where(Message.account_id == acc.id))
    db.execute(delete(Folder).where(Folder.account_id == acc.id))
    db.delete(acc)
    db.commit()
    return Response(status_code=204)
