from datetime import datetime, timedelta, timezone

from fakes import FakeMailSession
from sqlalchemy import select

from app.mail.imap import MailAuthError
from app.mail.sync import sync_account, sync_all
from app.models import Folder, MailAccount, Message

FOLDERS = {"INBOX": [], "[Gmail]/Corbeille": ["\\Trash"], "[Gmail]": ["\\Noselect"]}


def ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


def make_account(db, label="A", enabled=True):
    a = MailAccount(provider="imap", label=label, email=f"{label}@x.fr", imap_host="h",
                    username="u", secret_enc="s", enabled=enabled)
    db.add(a)
    db.commit()
    return a


def msgs(db, account, path="INBOX"):
    return list(db.scalars(
        select(Message).join(Folder, Message.folder_id == Folder.id)
        .where(Message.account_id == account.id, Folder.path == path).order_by(Message.uid)))


def test_first_sync_creates_folders_with_roles(db):
    a = make_account(db)
    s = FakeMailSession(folders=FOLDERS, uidvalidity=5)
    sync_account(db, a, s)
    roles = {f.path: (f.role, f.uidvalidity) for f in db.scalars(select(Folder))}
    assert roles == {"INBOX": ("inbox", 5), "[Gmail]/Corbeille": ("trash", 5)}


def test_first_sync_limited_to_30_days(db):
    a = make_account(db)
    s = FakeMailSession(folders={"INBOX": []})
    s.add_message("INBOX", subject="older", sent_at=ago(90))
    s.add_message("INBOX", subject="old", sent_at=ago(60))
    s.add_message("INBOX", subject="recent", sent_at=ago(5), seen=True, flagged=True,
                  has_attachments=True, preview="p", from_name="N")
    sync_account(db, a, s)
    rows = msgs(db, a)
    assert [m.subject for m in rows] == ["recent"]
    m = rows[0]
    assert (m.seen, m.flagged, m.has_attachments, m.preview, m.from_name, m.classified_level) == (
        True, True, True, "p", "N", "none")
    assert db.scalar(select(Folder.last_uid)) == 3  # incrémental ensuite


def test_second_sync_only_fetches_new_uids(db):
    a = make_account(db)
    s = FakeMailSession(folders={"INBOX": []})
    s.add_message("INBOX", subject="1", sent_at=ago(1))
    sync_account(db, a, s)
    s.add_message("INBOX", subject="2", sent_at=ago(1))
    ids = sync_account(db, a, s)
    assert s.header_requests[1] == ("INBOX", 1, None)
    assert len(ids) == 1
    assert [m.subject for m in msgs(db, a)] == ["1", "2"]


def test_uidvalidity_change_resets_folder(db):
    a = make_account(db)
    s = FakeMailSession(folders={"INBOX": []}, uidvalidity=1)
    s.add_message("INBOX", subject="old", sent_at=ago(1))
    sync_account(db, a, s)
    s2 = FakeMailSession(folders={"INBOX": []}, uidvalidity=2)
    s2.add_message("INBOX", subject="new", sent_at=ago(1))
    ids = sync_account(db, a, s2)
    assert [m.subject for m in msgs(db, a)] == ["new"]
    assert len(ids) == 1
    assert db.scalar(select(Folder.uidvalidity)) == 2


def test_returns_only_new_inbox_ids(db):
    a = make_account(db)
    s = FakeMailSession(folders=FOLDERS)
    s.add_message("INBOX", subject="i", sent_at=ago(1))
    s.add_message("[Gmail]/Corbeille", subject="t", sent_at=ago(1))
    ids = sync_account(db, a, s)
    assert [db.get(Message, i).subject for i in ids] == ["i"]
    assert sync_account(db, a, s) == []


def test_vanished_folder_is_removed(db):
    a = make_account(db)
    s = FakeMailSession(folders=FOLDERS)
    s.add_message("[Gmail]/Corbeille", subject="t", sent_at=ago(1))
    sync_account(db, a, s)
    del s.folders["[Gmail]/Corbeille"]
    sync_account(db, a, s)
    assert [f.path for f in db.scalars(select(Folder))] == ["INBOX"]
    assert db.scalars(select(Message)).all() == []


def test_seen_flag_refreshed(db):
    a = make_account(db)
    s = FakeMailSession(folders={"INBOX": []})
    uid = s.add_message("INBOX", sent_at=ago(1))
    sync_account(db, a, s)
    assert msgs(db, a)[0].seen is False
    s.messages["INBOX"][uid].update(seen=True, flagged=True)
    sync_account(db, a, s)
    db.expire_all()
    m = msgs(db, a)[0]
    assert (m.seen, m.flagged) == (True, True)


def test_failing_account_does_not_stop_others(db):
    bad, good = make_account(db, "bad"), make_account(db, "good")
    make_account(db, "off", enabled=False)
    sessions = {}

    def opener(account):
        s = FakeMailSession(folders={"INBOX": []})
        if account.label == "bad":
            s.fail_on["list_folders"] = MailAuthError("mot de passe secret123")
        else:
            s.add_message("INBOX", sent_at=ago(1))
        sessions[account.label] = s
        return s

    ids = sync_all(db, open_session=opener)
    db.expire_all()
    assert len(ids) == 1 and set(sessions) == {"bad", "good"}
    assert all(s.closed for s in sessions.values())
    assert (bad.status, bad.status_message) == ("error", "Identifiants refusés par le serveur")
    assert "secret123" not in bad.status_message
    assert good.status == "ok" and good.last_sync_at is not None


def test_unexpected_error_is_generic(db):
    a = make_account(db)

    def opener(account):
        raise RuntimeError("boom pass=hunter2")

    assert sync_all(db, open_session=opener) == []
    db.expire_all()
    assert (a.status, a.status_message) == ("error", "Erreur de synchronisation")


def test_sync_reconciles_placeholder_row_without_duplicate(db):
    a = make_account(db)
    s = FakeMailSession(folders=FOLDERS)
    uid = s.add_message("INBOX", subject="x", sent_at=ago(1))
    sync_account(db, a, s)
    db.commit()
    m = msgs(db, a)[0]
    trash = db.scalar(select(Folder).where(Folder.path == "[Gmail]/Corbeille"))
    s.move("INBOX", uid, "[Gmail]/Corbeille")  # UID de destination inconnu côté appli
    m.folder_id, m.uid = trash.id, -m.id
    db.commit()
    sync_account(db, a, s)
    rows = msgs(db, a, "[Gmail]/Corbeille")
    assert len(rows) == 1 and rows[0].id == m.id and rows[0].uid > 0
    assert rows[0].uid in s.messages["[Gmail]/Corbeille"]
