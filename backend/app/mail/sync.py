"""Synchronisation IMAP incrémentale vers SQLite (bloquante : à appeler dans un thread)."""
import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.mail.folders import detect_role
from app.mail.imap import MailAuthError, MailConnectError, MailError, MailSession, open_session
from app.models import Folder, MailAccount, Message, utcnow

log = logging.getLogger(__name__)

FIRST_SYNC_DAYS = 30
REFRESH_LAST = 500


def _utc(dt):
    from datetime import timezone

    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _sync_folders(db: Session, account: MailAccount, session: MailSession) -> list[Folder]:
    db.commit()  # aucune transaction ouverte pendant l'appel réseau
    wanted: dict[str, str] = {}
    for path, flags in session.list_folders():
        role = detect_role(path, flags)
        if role is not None:  # None = \Noselect : ignoré
            wanted[path] = role
    existing = {f.path: f for f in db.scalars(select(Folder).where(Folder.account_id == account.id))}
    for path, f in list(existing.items()):
        if path not in wanted:  # dossier disparu du serveur
            db.execute(delete(Message).where(Message.folder_id == f.id))
            db.delete(f)
            del existing[path]
    for path, role in wanted.items():
        f = existing.get(path)
        if f is None:
            f = Folder(account_id=account.id, path=path, role=role,
                       display_name=path.rsplit("/", 1)[-1].rsplit(".", 1)[-1] or path)
            db.add(f)
            existing[path] = f
        else:
            f.role = role
    db.commit()
    return [existing[p] for p in wanted]


def _sync_folder(db: Session, account: MailAccount, folder: Folder, session: MailSession) -> list[int]:
    """Tous les appels IMAP d'abord, puis les écritures en une transaction courte (commit par dossier).

    Une transaction d'écriture ouverte pendant le réseau bloquerait toute autre écriture SQLite
    (session glissante, actions…) jusqu'à « database is locked ».
    """
    # 1) lectures locales, puis réseau sans aucune transaction ouverte
    known_validity, last_uid = folder.uidvalidity, folder.last_uid or 0
    recent_uids = [u for u in db.scalars(
        select(Message.uid).where(Message.folder_id == folder.id)
        .order_by(Message.uid.desc()).limit(REFRESH_LAST)
    ) if u > 0]
    db.commit()
    uidvalidity = session.select(folder.path)
    reset = known_validity is not None and known_validity != uidvalidity
    if reset:  # UID réattribués : tout le dossier est rechargé
        last_uid, recent_uids = 0, []
    first = not last_uid
    since = (utcnow() - timedelta(days=FIRST_SYNC_DAYS)) if first else None
    headers = session.fetch_headers(folder.path, last_uid, since.date() if since else None)
    flags = session.fetch_flags(folder.path, recent_uids) if recent_uids else {}

    # 2) écritures
    if reset:
        db.execute(delete(Message).where(Message.folder_id == folder.id))
    folder.uidvalidity = uidvalidity
    known = set(db.scalars(select(Message.uid).where(Message.folder_id == folder.id)))
    placeholders = {  # lignes déplacées dont l'UID est encore inconnu (uid < 0)
        m.message_id_header: m for m in db.scalars(
            select(Message).where(Message.folder_id == folder.id, Message.uid < 0,
                                  Message.message_id_header.is_not(None)))
    }
    new_rows: list[Message] = []
    max_uid = last_uid
    for h in headers:
        max_uid = max(max_uid, h.uid)
        if h.uid in known:
            continue
        ph = placeholders.pop(h.message_id, None) if h.message_id else None
        if ph is not None:  # réconciliation : même mail, vrai UID
            ph.uid = h.uid
            continue
        if first and h.sent_at is not None and _utc(h.sent_at) < since:
            continue
        row = Message(
            account_id=account.id, folder_id=folder.id, uid=h.uid,
            message_id_header=h.message_id, from_name=h.from_name, from_addr=h.from_addr,
            subject=h.subject, sent_at=h.sent_at, preview=h.preview, seen=h.seen,
            flagged=h.flagged, has_attachments=h.has_attachments, classified_level="none",
        )
        db.add(row)
        new_rows.append(row)
    folder.last_uid = max_uid

    # rafraîchit seen/flagged des 500 derniers messages déjà connus
    if flags:
        for m in db.scalars(select(Message).where(Message.folder_id == folder.id,
                                                  Message.uid.in_(list(flags)))):
            m.seen, m.flagged = flags[m.uid]
    db.commit()
    return [m.id for m in new_rows] if folder.role == "inbox" else []


def sync_account(db: Session, account: MailAccount, session: MailSession) -> list[int]:
    """Synchronise un compte ; retourne les ids des nouveaux messages de la boîte de réception.

    Commit après chaque dossier : un dossier en échec ne remet pas en cause les précédents.
    """
    new_ids: list[int] = []
    for folder in _sync_folders(db, account, session):
        new_ids += _sync_folder(db, account, folder, session)
    return new_ids


def _error_message(exc: Exception) -> str:
    if isinstance(exc, MailAuthError):
        return "Identifiants refusés par le serveur"
    if isinstance(exc, MailConnectError):
        return "Serveur injoignable"
    if isinstance(exc, MailError):
        return "Erreur du serveur mail"
    return "Erreur de synchronisation"


def sync_all(db: Session, open_session=open_session) -> list[int]:
    """Synchronise tous les comptes actifs ; un compte en erreur n'arrête pas les autres."""
    new_ids: list[int] = []
    for account_id in list(db.scalars(select(MailAccount.id).where(MailAccount.enabled.is_(True)))):
        account = db.get(MailAccount, account_id)
        session = None
        try:
            session = open_session(account)
            ids = sync_account(db, account, session)
            account.status, account.status_message, account.last_sync_at = "ok", None, utcnow()
            db.commit()
            new_ids += ids
        except Exception as exc:  # noqa: BLE001 - isolation par compte
            db.rollback()
            if not isinstance(exc, MailError):
                log.exception("Synchronisation du compte %s en échec", account_id)
            account = db.get(MailAccount, account_id)
            account.status, account.status_message = "error", _error_message(exc)
            db.commit()
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:  # noqa: BLE001
                    pass
    return new_ids
