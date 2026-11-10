"""« Pendant ton absence » : ce que l'appli a fait depuis la dernière visite."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import iso, message_dict
from app.api.runs import run_dict
from app.auth.deps import current_user
from app.db import get_db
from app.models import ActionLog, AnalysisRun, MailAccount, Message, User, utcnow

router = APIRouter(prefix="/api", tags=["activity"])

DEFAULT_WINDOW = timedelta(hours=24)
LIMIT = 100


def _messages(db: Session, *conds):
    """(compteur exact, 100 plus récents) des mails des boîtes actives qui vérifient `conds`."""
    base = (
        select(Message, MailAccount.color)
        .join(MailAccount, MailAccount.id == Message.account_id)
        .where(MailAccount.enabled.is_(True), *conds)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    key = func.coalesce(Message.sent_at, Message.created_at)
    rows = db.execute(base.order_by(key.desc(), Message.id.desc()).limit(LIMIT)).all()
    return total, [message_dict(m, color) for m, color in rows]


def _actions(db: Session, since) -> tuple[int, list[dict]]:
    rows = db.execute(
        select(ActionLog, Message, MailAccount.color)
        .join(Message, Message.id == ActionLog.message_id)
        .join(MailAccount, MailAccount.id == Message.account_id)
        .where(MailAccount.enabled.is_(True), ActionLog.created_at >= since)
        .order_by(ActionLog.id.desc())
    ).all()
    batches: dict[str, dict] = {}
    done_mails: set[int] = set()
    for log, m, color in rows:
        b = batches.setdefault(log.batch_id, {
            "batch_id": log.batch_id, "action": log.action, "source": log.source,
            "at": iso(log.created_at), "count": 0, "undone": True, "messages": [],
        })
        b["count"] += 1
        if log.undone_at is None:
            b["undone"] = False
            done_mails.add(m.id)
        if len(b["messages"]) < LIMIT:
            b["messages"].append(message_dict(m, color))
    return len(done_mails), list(batches.values())[:LIMIT]


@router.get("/activity")
def activity(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    since = user.activity_seen_at or (utcnow() - DEFAULT_WINDOW)
    classified = Message.classified_at >= since
    analysed, _ = _messages(db, classified)
    n_imp, important = _messages(db, classified, Message.priority.is_(True), or_(Message.category.is_(None), Message.category != "tt"))
    n_tt, tt = _messages(db, classified, Message.category == "tt")
    n_ads, ads = _messages(db, classified, Message.category.in_(("pub", "spam")))
    # « Important » posé par l'utilisateur renseigne alerted_at sans qu'aucune alerte ne parte
    by_user = (
        select(ActionLog.message_id)
        .where(ActionLog.action == "important", ActionLog.source == "user", ActionLog.undone_at.is_(None))
    )
    n_alerts, alerts = _messages(db, Message.alerted_at >= since, Message.id.not_in(by_user))
    n_actions, actions = _actions(db, since)
    runs = list(db.scalars(
        select(AnalysisRun).where(AnalysisRun.started_at >= since).order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
    ))
    return {
        "since": iso(since),
        "summary": {
            "runs": len(runs), "analysed": analysed, "important": n_imp, "tt": n_tt, "ads": n_ads,
            "alerts": n_alerts, "actions": n_actions,
        },
        "runs": [run_dict(r) for r in runs[:LIMIT]],
        "important": important,
        "tt": tt,
        "ads": ads,
        "alerts": alerts,
        "actions": actions,
    }


@router.post("/activity/seen", status_code=204)
def seen(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    user.activity_seen_at = utcnow()
    db.commit()
    return Response(status_code=204)
