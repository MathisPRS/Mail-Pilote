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


def test_move_without_new_uid_deletes_local_row(auth_client, world):
    m = world.add(world.g)
    fake = world.fakes[world.g.id]
    orig = fake.move
    fake.move = lambda p, u, d: (orig(p, u, d), None)[1]
    mid = m.id
    assert _act(auth_client, [m.id], "trash").json()["count"] == 1
    world.db.expire_all()
    assert world.db.get(Message, mid) is None
