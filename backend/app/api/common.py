"""Briques communes de l'API mails : portée compte/dossier, sérialisation, session IMAP injectable."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mail import imap
from app.models import Folder, MailAccount, Message

ALL_COLOR = "#111317"
ROLE_LABELS = {
    "inbox": "Réception",
    "drafts": "Brouillons",
    "sent": "Envoyés",
    "junk": "Indésirables",
    "archive": "Archives",
    "trash": "Corbeille",
}
ROLE_ORDER = list(ROLE_LABELS)


def open_session(account: MailAccount):
    """Point d'injection unique des sessions IMAP (les tests le remplacent)."""
    return imap.open_session(account)


def snapshot(account: MailAccount) -> MailAccount:
    """Copie détachée d'un compte, utilisable dans un thread sans toucher à la session SQLAlchemy."""
    cols = {c.name: getattr(account, c.name) for c in MailAccount.__table__.columns}
    return MailAccount(**cols)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_account(db: Session, account: str) -> int | None:
    """'all' -> None ; id inconnu ou invalide -> 404."""
    if account == "all":
        return None
    try:
        acc_id = int(account)
    except ValueError:
        raise HTTPException(404, "Boîte introuvable") from None
    if db.get(MailAccount, acc_id) is None:
        raise HTTPException(404, "Boîte introuvable")
    return acc_id


def resolve_folder_ids(db: Session, key: str, account_id: int | None) -> list[int]:
    """Clé de dossier ('inbox', ..., 'f{id}') -> ids de dossiers ; 404 si inconnu."""
    if key.startswith("f") and key[1:].isdigit():
        folder = db.get(Folder, int(key[1:]))
        if folder is None or (account_id is not None and folder.account_id != account_id):
            raise HTTPException(404, "Dossier introuvable")
        return [folder.id]
    if key not in ROLE_LABELS:
        raise HTTPException(404, "Dossier introuvable")
    stmt = select(Folder.id).where(Folder.role == key)
    if account_id is not None:
        stmt = stmt.where(Folder.account_id == account_id)
    return list(db.scalars(stmt))


def message_dict(m: Message, color: str | None) -> dict:
    return {
        "id": m.id,
        "account_id": m.account_id,
        "account_color": color,
        "from_name": m.from_name,
        "from_addr": m.from_addr,
        "subject": m.subject,
        "preview": m.preview,
        "sent_at": iso(m.sent_at),
        "seen": m.seen,
        "category": m.category,
        "priority": m.priority,
        "reason": m.reason,
        "summary": m.summary,
    }
