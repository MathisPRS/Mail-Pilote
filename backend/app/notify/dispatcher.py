import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt
from app.models import KV, Folder, Message, PushSubscription
from app.notify import gotify, webpush
from app.settings_store import AlertSettings, get_alerts

log = logging.getLogger(__name__)

# Mails alertables : stockés par nous dans les dernières 24 h (created_at, pour ne jamais
# diffuser un arriéré à la première synchro) ET, si la date d'envoi est connue, envoyés
# dans les dernières 48 h (un vieux mail découvert tard ne déclenche pas d'alerte).
RECENT = timedelta(hours=24)
MAX_SENT_AGE = timedelta(hours=48)
SYSTEM_DEDUP = timedelta(hours=24)

TYPE_FLAG = {"tt": "notify_tt", "important": "notify_important", "action": "notify_action"}


def _parse(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def is_quiet(now: time, quiet_from: str, quiet_to: str) -> bool:
    start, end = _parse(quiet_from), _parse(quiet_to)
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end  # passe minuit


def _title(m: Message) -> str:
    if m.category == "tt":
        return f"TT+ · {m.subject or ''}"
    label = "Important" if m.category == "important" else "À traiter"
    return f"{label} · {m.from_name or m.from_addr or ''}"


async def send_to_channels(
    db: Session, alerts: AlertSettings, title: str, body: str, url: str, priority: int
) -> tuple[int, int]:
    """Envoie sur chaque canal actif. Retourne (canaux tentés, canaux réussis)."""
    attempted = succeeded = 0
    if alerts.gotify and alerts.gotify_url and alerts.gotify_token_enc:
        attempted += 1
        try:
            await gotify.send_gotify(
                alerts.gotify_url, decrypt(alerts.gotify_token_enc), title, body, priority, url
            )
            succeeded += 1
        except Exception as e:  # noqa: BLE001 - jamais de secret dans le log
            log.warning("Échec Gotify : %s", type(e).__name__)
    if alerts.webpush:
        subs = list(db.scalars(select(PushSubscription)))
        if subs:
            attempted += 1
            # format lu par le service worker (sw.ts) : data.url = page ouverte au clic
            payload = {"title": title, "body": body, "data": {"url": url}}
            ok = False
            for sub in subs:
                try:
                    await asyncio.to_thread(webpush.send_webpush, sub, payload)
                    ok = True
                except webpush.SubscriptionGone:
                    db.delete(sub)
                    db.commit()
                except Exception as e:  # noqa: BLE001
                    log.warning("Échec Web Push : %s", type(e).__name__)
            succeeded += ok
    return attempted, succeeded


async def dispatch_alerts(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    alerts = get_alerts(db)
    local = now.astimezone(ZoneInfo(get_settings().tz)).time()
    quiet = alerts.quiet_enabled and is_quiet(local, alerts.quiet_from, alerts.quiet_to)
    pending = db.scalars(
        select(Message)
        .join(Folder, Folder.id == Message.folder_id)
        # seulement les mails encore non lus et encore dans la boîte de réception
        .where(Folder.role == "inbox", Message.seen.is_(False))
        .where(Message.priority.is_(True), Message.alerted_at.is_(None))
        .where(Message.category.in_(TYPE_FLAG), Message.created_at >= now - RECENT)
        .order_by(Message.created_at)
    ).all()
    sent = 0
    for m in pending:
        if m.sent_at is not None and m.sent_at < now - MAX_SENT_AGE:
            continue
        if not getattr(alerts, TYPE_FLAG[m.category]):
            continue
        if quiet and not (m.category == "tt" and alerts.quiet_tt_bypass):
            continue
        _, ok = await send_to_channels(
            db, alerts, _title(m), m.reason or "", f"/mail/{m.id}", 8 if m.category == "tt" else 5
        )
        if ok:
            m.alerted_at = now
            db.commit()
            sent += 1
    return sent


async def send_system_alert(db: Session, title: str, body: str, key: str) -> bool:
    """Alerte système (ex. Claude déconnecté), dédoublonnée par `key` sur 24 h."""
    now = datetime.now(timezone.utc)
    row = db.get(KV, f"sysalert:{key}")
    if row:
        last = datetime.fromisoformat(row.value_json)
        if now - last < SYSTEM_DEDUP:
            return False
    _, ok = await send_to_channels(db, get_alerts(db), title, body, "/", 8)
    if not ok:
        return False
    if row:
        row.value_json = now.isoformat()
    else:
        db.add(KV(key=f"sysalert:{key}", value_json=now.isoformat()))
    db.commit()
    return True
