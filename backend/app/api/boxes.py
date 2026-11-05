from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import ALL_COLOR, ROLE_LABELS, ROLE_ORDER, parse_account
from app.auth.deps import current_user
from app.db import get_db
from app.models import Folder, MailAccount, Message

router = APIRouter(prefix="/api", tags=["boxes"], dependencies=[Depends(current_user)])


def _unread(db: Session, account_id: int | None) -> int:
    stmt = (
        select(func.count(Message.id))
        .join(Folder, Folder.id == Message.folder_id)
        .where(Folder.role == "inbox", Message.seen.is_(False))
    )
    if account_id is not None:
        stmt = stmt.where(Message.account_id == account_id)
    return db.scalar(stmt) or 0


def _priority(db: Session, account_id: int | None) -> list[dict]:
    stmt = (
        select(Message)
        .join(Folder, Folder.id == Message.folder_id)
        .where(Folder.role == "inbox", Message.priority.is_(True))
        .order_by(Message.sent_at.desc(), Message.id.desc())
        .limit(2)
    )
    if account_id is not None:
        stmt = stmt.where(Message.account_id == account_id)
    return [
        {
            "id": m.id,
            "label": "TT+" if m.category == "tt" else (m.from_name or m.from_addr or ""),
            "subject": m.subject,
            "category": m.category,
        }
        for m in db.scalars(stmt)
    ]


@router.get("/boxes/summary")
def summary(db: Session = Depends(get_db)) -> list[dict]:
    accounts = list(db.scalars(select(MailAccount).order_by(MailAccount.id)))
    n = len(accounts)
    out = [
        {
            "id": "all",
            "label": "Toutes les boîtes",
            "email": f"Vue unifiée de {n} boîte{'s' if n > 1 else ''}",
            "color": ALL_COLOR,
            "unread": _unread(db, None),
            "priority": _priority(db, None),
        }
    ]
    for a in accounts:
        out.append(
            {
                "id": a.id,
                "label": a.label,
                "email": a.email,
                "color": a.color,
                "unread": _unread(db, a.id),
                "priority": _priority(db, a.id),
            }
        )
    return out


@router.get("/folders")
def folders(account: str = "all", db: Session = Depends(get_db)) -> list[dict]:
    account_id = parse_account(db, account)
    stmt = select(Folder).order_by(Folder.id)
    if account_id is not None:
        stmt = stmt.where(Folder.account_id == account_id)
    rows = list(db.scalars(stmt))
    unread = dict(
        db.execute(
            select(Message.folder_id, func.count(Message.id))
            .where(Message.seen.is_(False))
            .group_by(Message.folder_id)
        ).all()
    )
    out: list[dict] = []
    for role in ROLE_ORDER:
        matching = [f for f in rows if f.role == role]
        if matching:
            out.append(
                {
                    "key": role,
                    "role": role,
                    "label": ROLE_LABELS[role],
                    "unread": sum(unread.get(f.id, 0) for f in matching),
                }
            )
    if account_id is not None:
        out += [
            {"key": f"f{f.id}", "role": "custom", "label": f.display_name, "unread": unread.get(f.id, 0)}
            for f in rows
            if f.role == "custom"
        ]
    return out
