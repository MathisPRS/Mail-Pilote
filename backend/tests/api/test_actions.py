from sqlalchemy import select

from app.models import ActionLog, Folder, Message


def _act(c, ids, action, **kw):
    return c.post("/api/messages/actions", json={"ids": ids, "action": action, **kw})


def test_trash_moves_to_trash_role_and_logs(auth_client, world):
    a, b = world.add(world.g), world.add(world.i)
    r = _act(auth_client, [a.id, b.id], "trash")
    assert r.status_code == 200 and r.json()["count"] == 2
    world.db.refresh(a)
    world.db.refresh(b)
    assert a.folder_id == world.folders[(world.g.id, "Trash")].id
    assert b.folder_id == world.folders[(world.i.id, "Deleted")].id
    assert world.fakes[world.g.id].moves[0][:3] == ("INBOX", 1, "Trash")
    assert world.fakes[world.g.id].calls["close"] == 1  # une session par compte
    logs = list(world.db.scalars(select(ActionLog).where(ActionLog.batch_id == r.json()["batch_id"])))
    assert len(logs) == 2 and all(l.source == "user" and l.prev_state_json for l in logs)


def test_undo_restores_folder(auth_client, world):
    a = world.add(world.g)
    inbox = a.folder_id
    batch = _act(auth_client, [a.id], "trash").json()["batch_id"]
    r = auth_client.post(f"/api/actions/{batch}/undo")
    assert r.status_code == 200 and r.json()["count"] == 1
    world.db.refresh(a)
    assert a.folder_id == inbox
    assert a.uid in world.fakes[world.g.id].messages["INBOX"]


def test_undo_twice_409(auth_client, world):
    batch = _act(auth_client, [world.add(world.g).id], "trash").json()["batch_id"]
    assert auth_client.post(f"/api/actions/{batch}/undo").status_code == 200
    assert auth_client.post(f"/api/actions/{batch}/undo").status_code == 409
    assert auth_client.post("/api/actions/nope/undo").status_code == 404


def test_cleanup_only_pub_spam_inbox(auth_client, world):
    pub, spam = world.add(world.g, category="pub"), world.add(world.i, category="spam")
    keep = world.add(world.g, category="info")
    old = world.add(world.g, path="Archive", category="pub")
    r = auth_client.post("/api/cleanup")
    assert r.json()["count"] == 2
    for m in (pub, spam, keep, old):
        world.db.refresh(m)
    trash = {world.folders[(world.g.id, "Trash")].id, world.folders[(world.i.id, "Deleted")].id}
    assert pub.folder_id in trash and spam.folder_id in trash
    assert keep.folder_id != pub.folder_id and old.folder_id == world.folders[(world.g.id, "Archive")].id
    assert auth_client.post(f"/api/cleanup?account={world.g.id}").json()["count"] == 0


def test_archive_without_archive_folder_400(auth_client, world):
    m = world.add(world.i)
    r = _act(auth_client, [m.id], "archive")
    assert r.status_code == 400 and r.json()["detail"] == "Ce compte n'a pas de dossier Archives"
    assert world.db.scalars(select(ActionLog)).first() is None


def test_move_same_account_only(auth_client, world):
    m = world.add(world.g)
    custom = world.folders[(world.g.id, "Projets")].id
    assert _act(auth_client, [m.id], "move", target_folder=f"f{custom}").json()["count"] == 1
    other = world.add(world.i)
    assert _act(auth_client, [other.id], "move", target_folder=f"f{custom}").status_code == 400
    assert _act(auth_client, [m.id], "move", target_folder="f99999").status_code == 404
    assert _act(auth_client, [m.id], "move").status_code == 400


def test_provider_failure_skips_and_all_fail_502(auth_client, world):
    a, b = world.add(world.g), world.add(world.g)
    fake = world.fakes[world.g.id]
    orig = fake.move
    fake.move = lambda p, u, d: (_ for _ in ()).throw(RuntimeError("no")) if u == a.uid else orig(p, u, d)
    r = _act(auth_client, [a.id, b.id], "trash")
    assert r.json()["count"] == 1
    assert len(list(world.db.scalars(select(ActionLog)))) == 1
    fake.fail_on["move"] = RuntimeError("no")
    fake.move = orig
    r = _act(auth_client, [a.id], "trash")
    assert r.status_code == 502 and r.json()["detail"] == "Le serveur mail a refusé l'opération"
    world.db.refresh(a)
    assert a.folder_id == world.folders[(world.g.id, "INBOX")].id


def test_read_unread_important_and_undo(auth_client, world):
    m = world.add(world.g, category="info", priority=False)
    assert _act(auth_client, [m.id], "read").json()["count"] == 1
    world.db.refresh(m)
    assert m.seen is True
    b = _act(auth_client, [m.id], "important").json()["batch_id"]
    world.db.refresh(m)
    assert (m.category, m.priority, m.flagged) == ("important", True, True)
    assert world.fakes[world.g.id].flag_changes == [("INBOX", m.uid, True)]
    auth_client.post(f"/api/actions/{b}/undo")
    world.db.refresh(m)
    assert (m.category, m.priority, m.flagged) == ("info", False, False)
    u = _act(auth_client, [m.id], "unread").json()["batch_id"]
    world.db.refresh(m)
    assert m.seen is False
    auth_client.post(f"/api/actions/{u}/undo")
    world.db.refresh(m)
    assert m.seen is True


def test_move_without_copyuid_trash_then_undo_restores(auth_client, world):
    fake = world.fakes[world.g.id]
    fake.move_returns_uid = False  # serveur MOVE : pas de COPYUID
    m = world.add(world.g)
    inbox, trash = world.folders[(world.g.id, "INBOX")].id, world.folders[(world.g.id, "Trash")].id
    batch = _act(auth_client, [m.id], "trash").json()["batch_id"]
    world.db.refresh(m)
    assert m.folder_id == trash and m.uid > 0 and m.uid in fake.messages["Trash"]
    r = auth_client.post(f"/api/actions/{batch}/undo")
    assert r.status_code == 200 and r.json()["count"] == 1
    world.db.refresh(m)
    assert m.folder_id == inbox and m.uid in fake.messages["INBOX"] and not fake.messages["Trash"]


def test_placeholder_uid_undo_via_message_id(auth_client, world):
    fake = world.fakes[world.g.id]
    fake.move_returns_uid = False
    fake.find_uid = lambda p, mid: None if p == "Trash" else type(fake).find_uid(fake, p, mid)
    m = world.add(world.g)
    batch = _act(auth_client, [m.id], "trash").json()["batch_id"]
    world.db.refresh(m)
    assert m.folder_id == world.folders[(world.g.id, "Trash")].id and m.uid == -m.id
    del fake.find_uid  # le serveur retrouve de nouveau le mail
    assert auth_client.post(f"/api/actions/{batch}/undo").json()["count"] == 1
    world.db.refresh(m)
    assert m.folder_id == world.folders[(world.g.id, "INBOX")].id and m.uid > 0


def test_undo_when_mail_vanished_409_and_not_marked(auth_client, world):
    fake = world.fakes[world.g.id]
    m = world.add(world.g)
    batch = _act(auth_client, [m.id], "trash").json()["batch_id"]
    fake.messages["Trash"].clear()  # supprimé côté serveur entre-temps
    world.db.refresh(m)
    r = auth_client.post(f"/api/actions/{batch}/undo")
    assert r.status_code == 409 and r.json()["detail"] == "Ce mail ne peut plus être restauré"
    world.db.expire_all()
    assert all(l.undone_at is None for l in world.db.scalars(select(ActionLog)))


async def test_action_commit_locked_reverts_provider_move_and_reports(world, settings):
    """Le déplacement a réussi chez le fournisseur mais la base est verrouillée : on annule chez le
    fournisseur et on renvoie une erreur claire (jamais un mail déplacé sans ActionLog)."""
    import pytest
    from fastapi import HTTPException
    from sqlalchemy.orm import Session as DbSession

    from app.api.actions import run_batch
    from app.db import make_engine
    from test_db_lock import hold_write_lock

    m = world.add(world.g)
    fake = world.fakes[world.g.id]
    with DbSession(make_engine(f"sqlite:///{settings.data_dir / 'test.db'}", timeout=0.2)) as s:
        msg = s.get(Message, m.id)
        blocker = None
        real_execute = __import__("app.api.actions", fromlist=["_execute"])._execute

        async def execute_then_lock(db, ops):
            nonlocal blocker
            res = await real_execute(db, ops)
            if blocker is None:
                blocker = hold_write_lock(settings)  # une synchro écrit pendant ce temps
            return res

        import app.api.actions as actions_mod
        actions_mod._execute, saved = execute_then_lock, actions_mod._execute
        try:
            with pytest.raises(HTTPException) as exc:
                await run_batch(s, [msg], "trash")
        finally:
            actions_mod._execute = saved
            if blocker is not None:
                blocker.rollback()
                blocker.close()
    assert exc.value.status_code == 503
    assert "annulée" in exc.value.detail
    assert m.uid not in fake.messages["Trash"].values() and len(fake.messages["INBOX"]) == 1
    assert [mv[:3] for mv in fake.moves] == [("INBOX", m.uid, "Trash"), ("Trash", fake.moves[0][3], "INBOX")]
    world.db.expire_all()
    assert world.db.get(Message, m.id).folder_id == world.folders[(world.g.id, "INBOX")].id
    assert world.db.scalars(select(ActionLog)).first() is None
