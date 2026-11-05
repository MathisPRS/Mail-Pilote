"""Sessions d'analyse : vérification légère (en-têtes) et tri complet (corps si besoin)."""
import asyncio
import html as html_lib
import logging
import re
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app import db as db_module
from app.claude.classify import (
    FULL_BATCH,
    HEADERS_BATCH,
    Classification,
    FullItem,
    HeaderItem,
    classify_full,
    classify_headers,
)
from app.claude.runner import ClaudeAuthError, ClaudeBadOutput, ClaudeRateLimited
from app.claude.status import record_claude_failure, record_claude_success
from app.mail.imap import open_session
from app.mail.sync import sync_all
from app.models import AnalysisRun, Folder, MailAccount, Message, utcnow
from app.notify.dispatcher import dispatch_alerts, send_system_alert
from app.settings_store import get_alerts

log = logging.getLogger(__name__)

FULL_WINDOW_DAYS = 7

_lock = asyncio.Lock()
_current_run_id: int | None = None

_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]*>")


def html_to_text(html: str) -> str:
    text = _TAG.sub(" ", _SCRIPT_STYLE.sub(" ", html))
    return re.sub(r"[ \t\r\f\v\xa0]+", " ", html_lib.unescape(text)).strip()


def _body_text(body) -> str:
    if body.text and body.text.strip():
        return body.text
    return html_to_text(body.html) if body.html else ""


def _inbox_messages(db: Session, *conds) -> list[Message]:
    stmt = (
        select(Message)
        .join(Folder, Folder.id == Message.folder_id)
        .where(Folder.role == "inbox", *conds)
        .order_by(Message.id)
    )
    return list(db.scalars(stmt))


def _header_item(m: Message) -> HeaderItem:
    return HeaderItem(m.id, m.from_name or "", m.from_addr or "", m.subject or "", m.preview or "")


def _apply(m: Message, c: Classification, level: str) -> None:
    m.category = c.category
    m.priority = c.priority
    m.reason = c.reason
    m.summary = c.summary
    m.deadline = c.deadline.isoformat() if c.deadline else None
    m.tt_date = c.tt_date.isoformat() if c.tt_date else None
    m.needs_body = c.needs_body
    m.classified_level = level


def _sync_blocking() -> None:
    with db_module.SessionLocal() as s:
        sync_all(s, open_session=open_session)


def _fetch_bodies_blocking(targets: list[tuple[int, int, str, int]]) -> dict[int, str]:
    """targets: (message id, account id, chemin du dossier, uid). Échec d'un corps = absent du résultat."""
    out: dict[int, str] = {}
    by_account: dict[int, list[tuple[int, str, int]]] = {}
    for mid, acc_id, path, uid in targets:
        by_account.setdefault(acc_id, []).append((mid, path, uid))
    with db_module.SessionLocal() as s:
        for acc_id, items in by_account.items():
            account = s.get(MailAccount, acc_id)
            try:
                session = open_session(account)
            except Exception:
                log.warning("connexion impossible pour récupérer les corps (compte %s)", acc_id)
                continue
            try:
                for mid, path, uid in items:
                    try:
                        out[mid] = _body_text(session.fetch_body(path, uid))
                    except Exception:
                        log.warning("corps illisible (message %s)", mid)
            finally:
                try:
                    session.close()
                except Exception:
                    pass
    return out


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _classify_batches(db, run, items, classify, size, level, by_id) -> None:
    """Un appel Claude par lot ; incrémente run.mails_count ; peut lever Auth/RateLimited."""
    for batch in _chunks(items, size):
        try:
            results = await classify(batch)
        except ClaudeBadOutput as exc:
            log.warning("lot non classé (sortie invalide) : %s", exc)
            continue
        record_claude_success(db)
        for c in results:
            m = by_id.get(c.message_id)
            if m is not None:
                _apply(m, c, level)
                run.mails_count += 1
        db.commit()


async def _execute(db: Session, kind: str, run: AnalysisRun) -> None:
    await asyncio.to_thread(_sync_blocking)
    db.expire_all()
    if kind == "light":
        msgs = _inbox_messages(db, Message.classified_level == "none")
        by_id = {m.id: m for m in msgs}
        items = [_header_item(m) for m in msgs]
        if items:
            await _classify_batches(db, run, items, classify_headers, HEADERS_BATCH, "headers", by_id)
    else:
        cutoff = utcnow() - timedelta(days=FULL_WINDOW_DAYS)
        msgs = _inbox_messages(
            db,
            Message.classified_level != "full",
            or_(Message.sent_at.is_(None), Message.sent_at >= cutoff),
        )
        by_id = {m.id: m for m in msgs}
        folders = {f.id: f.path for f in db.scalars(select(Folder))}
        targets = [
            (m.id, m.account_id, folders[m.folder_id], m.uid)
            for m in msgs
            if m.needs_body or m.classified_level == "none"
        ]
        bodies = await asyncio.to_thread(_fetch_bodies_blocking, targets) if targets else {}
        db.expire_all()
        items = [
            FullItem(m.id, m.from_name or "", m.from_addr or "", m.subject or "",
                     m.preview or "", bodies.get(m.id) or m.preview or "")
            for m in msgs
        ]
        if items:
            await _classify_batches(db, run, items, classify_full, FULL_BATCH, "full", by_id)
    await dispatch_alerts(db)
    if kind == "full":
        alerts = get_alerts(db)
        if alerts.notify_summary and run.status == "running":
            prio = sum(1 for m in msgs if m.classified_level == "full" and m.priority)
            await send_system_alert(
                db,
                "Tri terminé",
                f"{run.mails_count} mail(s) analysé(s), {prio} prioritaire(s).",
                f"summary-{run.id}",
            )


async def _run(db: Session, kind: str, trigger: str) -> AnalysisRun:
    global _current_run_id
    if _lock.locked():
        db.expire_all()
        running = db.get(AnalysisRun, _current_run_id)
        if running is not None:
            return running
    async with _lock:
        run = AnalysisRun(kind=kind, trigger=trigger, status="running")
        db.add(run)
        db.commit()
        _current_run_id = run.id
        status, error = "ok", None
        try:
            await _execute(db, kind, run)
        except (ClaudeAuthError, ClaudeRateLimited) as exc:
            status, error = "queued", str(exc)[:500]
            db.rollback()
            await record_claude_failure(db, exc)
        except Exception as exc:  # une session ne doit jamais faire tomber le planificateur
            log.exception("session %s en échec", kind)
            status, error = "error", str(exc)[:500]
            db.rollback()
        finally:
            run = db.get(AnalysisRun, run.id)
            run.status, run.error, run.finished_at = status, error, utcnow()
            db.commit()
            _current_run_id = None
        return run


def close_interrupted_runs() -> int:
    """Au démarrage : un run resté « running » (arrêt brutal) est clos en erreur."""
    with db_module.SessionLocal() as s:
        res = s.execute(
            update(AnalysisRun).where(AnalysisRun.status == "running")
            .values(status="error", error="interrompue (redémarrage)", finished_at=utcnow())
        )
        s.commit()
        return res.rowcount


async def run_light(db: Session, trigger: str = "schedule") -> AnalysisRun:
    return await _run(db, "light", trigger)


async def run_full(db: Session, trigger: str = "schedule") -> AnalysisRun:
    return await _run(db, "full", trigger)
