import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import common
from app.api.common import parse_account
from app.auth.deps import current_user
from app.db import get_db
from app.models import ActionLog, Folder, MailAccount, Message, utcnow

router = APIRouter(prefix="/api", tags=["actions"], dependencies=[Depends(current_user)])

MOVE_ACTIONS = {"archive": "archive", "trash": "trash"}
NO_FOLDER = {
    "archive": "Ce compte n'a pas de dossier Archives",
    "trash": "Ce compte n'a pas de dossier Corbeille",
}
REFUSED = "Le serveur mail a refusé l'opération"


class ActionIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    action: Literal["read", "unread", "archive", "trash", "move", "important"]
    target_folder: str | None = None


# --- exécution chez le fournisseur (bloquant : dans un thread, une session par compte) ---

def _provider_ops(account: MailAccount, ops: list[dict]) -> dict[int, dict]:
    """ops: [{id, kind, path, uid, dest?, value?}] -> {id: {"ok": bool, "new_uid": int|None}}"""
    results: dict[int, dict] = {}
    session = None
    try:
        session = common.open_session(account)
    except Exception:  # noqa: BLE001
        return {op["id"]: {"ok": False, "new_uid": None} for op in ops}
    try:
        for op in ops:
            try:
                new_uid = None
                if op["kind"] == "move":
                    uid = op["uid"]
                    if uid <= 0:  # UID inconnu (déplacement précédent) : retrouvé par Message-ID
                        uid = op["mid"] and session.find_uid(op["path"], op["mid"])
                        if not uid:
                            raise LookupError("mail introuvable")
                    new_uid = session.move(op["path"], uid, op["dest"])
                    if new_uid is None and op.get("mid"):  # serveur MOVE sans COPYUID
                        new_uid = session.find_uid(op["dest"], op["mid"])
                elif op["kind"] == "seen":
                    session.set_seen(op["path"], op["uid"], op["value"])
                elif op["kind"] == "flag":
                    session.set_flagged(op["path"], op["uid"], op["value"])
                results[op["id"]] = {"ok": True, "new_uid": new_uid}
            except Exception:  # noqa: BLE001 - ce mail est ignoré, les autres continuent
                results[op["id"]] = {"ok": False, "new_uid": None}
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass
    return results


async def _execute(db: Session, ops_by_account: dict[int, list[dict]]) -> dict[int, dict]:
    results: dict[int, dict] = {}
    for account_id, ops in ops_by_account.items():
        snap = common.snapshot(db.get(MailAccount, account_id))
        results.update(await run_in_threadpool(_provider_ops, snap, ops))
    return results


def _apply_move(m: Message, dest: Folder, new_uid: int | None, db: Session) -> None:
    """Après un déplacement réussi : la ligne locale suit le mail (nouveau dossier + nouvel UID).

    Le nouvel UID vient de COPYUID ou d'une recherche par Message-ID ; s'il reste inconnu, la ligne
    garde un UID provisoire négatif (-id) que la synchronisation remplace (sans doublon) et que
    l'annulation retrouve par Message-ID.
    """
    m.folder_id = dest.id
    m.uid = new_uid if new_uid is not None else -m.id


def _resolve_dest(db: Session, body_action: str, target: str | None, accounts: set[int]) -> dict[int, Folder]:
    dests: dict[int, Folder] = {}
    for acc in accounts:
        if body_action in MOVE_ACTIONS:
            f = db.scalar(select(Folder).where(Folder.account_id == acc, Folder.role == MOVE_ACTIONS[body_action]))
            if f is None:
                raise HTTPException(400, NO_FOLDER[body_action])
        else:
            if not target:
                raise HTTPException(400, "Dossier de destination manquant")
            if target.startswith("f") and target[1:].isdigit():
                f = db.get(Folder, int(target[1:]))
                if f is None:
                    raise HTTPException(404, "Dossier introuvable")
                if f.account_id != acc:
                    raise HTTPException(400, "Le dossier doit appartenir au même compte")
            else:
                f = db.scalar(select(Folder).where(Folder.account_id == acc, Folder.role == target))
                if f is None:
                    raise HTTPException(400, "Ce compte n'a pas ce dossier")
        dests[acc] = f
    return dests


async def run_batch(
    db: Session, messages: list[Message], action: str, target: str | None = None,
    source: str = "user", skip_missing_dest: bool = False,
) -> dict:
    folders = {f.id: f for f in db.scalars(select(Folder).where(Folder.id.in_({m.folder_id for m in messages})))}
    accounts = {m.account_id for m in messages}
    ops_by_account: dict[int, list[dict]] = {}
    prev: dict[int, dict] = {}
    dest_by_msg: dict[int, Folder] = {}
    is_move = action in MOVE_ACTIONS or action == "move"

    if is_move:
        if skip_missing_dest:
            dests = {}
            for acc in accounts:
                f = db.scalar(select(Folder).where(Folder.account_id == acc, Folder.role == MOVE_ACTIONS[action]))
                if f is not None:
                    dests[acc] = f
        else:
            dests = _resolve_dest(db, action, target, accounts)
    for m in messages:
        src = folders[m.folder_id]
        if is_move:
            dest = dests.get(m.account_id)
            if dest is None or dest.id == src.id:
                continue
            dest_by_msg[m.id] = dest
            op = {"id": m.id, "kind": "move", "path": src.path, "uid": m.uid, "dest": dest.path, "mid": m.message_id_header}
            prev[m.id] = {"uid": m.uid, "folder_id": src.id}
        elif action in ("read", "unread"):
            op = {"id": m.id, "kind": "seen", "path": src.path, "uid": m.uid, "value": action == "read"}
            prev[m.id] = {"seen": m.seen}
        else:  # important
            op = {"id": m.id, "kind": "flag", "path": src.path, "uid": m.uid, "value": True}
            prev[m.id] = {"category": m.category, "priority": m.priority, "flagged": m.flagged}
        ops_by_account.setdefault(m.account_id, []).append(op)

    if not ops_by_account:
        return {"batch_id": uuid.uuid4().hex, "count": 0}
    results = await _execute(db, ops_by_account)
    ok = [m for m in messages if results.get(m.id, {}).get("ok")]
    if not ok:
        raise HTTPException(502, REFUSED)

    batch_id = uuid.uuid4().hex
    for m in ok:
        log = ActionLog(
            batch_id=batch_id, message_id=m.id, action=action, source=source,
            prev_state_json=json.dumps(prev[m.id]),
        )
        if is_move:
            log.from_folder_id, log.to_folder_id = prev[m.id]["folder_id"], dest_by_msg[m.id].id
            _apply_move(m, dest_by_msg[m.id], results[m.id]["new_uid"], db)
        elif action in ("read", "unread"):
            m.seen = action == "read"
        else:
            m.category, m.priority, m.flagged = "important", True, True
        db.add(log)
    db.commit()
    return {"batch_id": batch_id, "count": len(ok)}


@router.post("/messages/actions")
async def message_action(body: ActionIn, db: Session = Depends(get_db)) -> dict:
    ids = list(dict.fromkeys(body.ids))
    messages = list(db.scalars(select(Message).where(Message.id.in_(ids)).order_by(Message.id)))
    if not messages:
        raise HTTPException(404, "Mail introuvable")
    return await run_batch(db, messages, body.action, body.target_folder)


@router.post("/cleanup")
async def cleanup(account: str = "all", db: Session = Depends(get_db)) -> dict:
    account_id = parse_account(db, account)
    stmt = (
        select(Message)
        .join(Folder, Folder.id == Message.folder_id)
        .where(Folder.role == "inbox", Message.category.in_(("pub", "spam")))
        .order_by(Message.id)
    )
    if account_id is not None:
        stmt = stmt.where(Message.account_id == account_id)
    messages = list(db.scalars(stmt))
    if not messages:
        return {"batch_id": uuid.uuid4().hex, "count": 0}
    return await run_batch(db, messages, "trash", skip_missing_dest=True)


# --- annulation ---

def _undo_ops(db: Session, logs: list[ActionLog]):
    """Prépare l'inverse de chaque ligne ; ignore les mails qui ont disparu ou bougé depuis."""
    items = []
    for log in logs:
        m = db.get(Message, log.message_id) if log.message_id else None
        if m is None:
            continue
        prev = json.loads(log.prev_state_json or "{}")
        if log.action in ("archive", "trash", "move"):
            cur, orig = db.get(Folder, m.folder_id), db.get(Folder, log.from_folder_id)
            if orig is None or m.folder_id != log.to_folder_id:
                continue
            op = {"id": m.id, "kind": "move", "path": cur.path, "uid": m.uid, "dest": orig.path, "mid": m.message_id_header}
        elif log.action in ("read", "unread"):
            f = db.get(Folder, m.folder_id)
            op = {"id": m.id, "kind": "seen", "path": f.path, "uid": m.uid, "value": prev.get("seen", m.seen)}
        else:
            f = db.get(Folder, m.folder_id)
            op = {"id": m.id, "kind": "flag", "path": f.path, "uid": m.uid, "value": prev.get("flagged", False)}
        items.append((log, m, prev, op))
    return items


@router.post("/actions/{batch_id}/undo")
async def undo(batch_id: str, db: Session = Depends(get_db)) -> dict:
    logs = list(db.scalars(select(ActionLog).where(ActionLog.batch_id == batch_id).order_by(ActionLog.id)))
    if not logs:
        raise HTTPException(404, "Action introuvable")
    pending = [l for l in logs if l.undone_at is None]
    if not pending:
        raise HTTPException(409, "Cette action a déjà été annulée")
    items = _undo_ops(db, pending)
    ops_by_account: dict[int, list[dict]] = {}
    for _, m, _, op in items:
        ops_by_account.setdefault(m.account_id, []).append(op)
    results = await _execute(db, ops_by_account) if ops_by_account else {}
    count, now = 0, utcnow()
    for log, m, prev, op in items:
        res = results.get(m.id)
        if not res or not res["ok"]:
            continue
        if op["kind"] == "move":
            _apply_move(m, db.get(Folder, log.from_folder_id), res["new_uid"], db)
        elif op["kind"] == "seen":
            m.seen = op["value"]
        else:
            m.category, m.priority = prev.get("category"), prev.get("priority", False)
            m.flagged = prev.get("flagged", False)
        log.undone_at = now
        count += 1
    if count == 0:
        db.rollback()
        raise HTTPException(409, "Ce mail ne peut plus être restauré")
    for log in pending:  # mails disparus : rien à restaurer, le lot est clos
        if log.undone_at is None and all(log is not i[0] for i in items):
            log.undone_at = now
    db.commit()
    return {"batch_id": batch_id, "count": count}
