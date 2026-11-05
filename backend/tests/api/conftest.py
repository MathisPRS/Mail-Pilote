from datetime import datetime, timedelta, timezone

import pytest

from app.api import common
from app.models import Folder, MailAccount, Message
from fakes import FakeMailSession

BASE = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def world(db, monkeypatch):
    """2 comptes (gmail avec Corbeille+Archives+dossier custom, icloud sans Archives) + sessions factices."""
    def acc(provider, email, color):
        a = MailAccount(provider=provider, label=provider.title(), email=email, imap_host="h",
                        username=email, secret_enc="x", color=color)
        db.add(a)
        db.flush()
        return a

    g, i = acc("gmail", "g@gmail.com", "#D93025"), acc("icloud", "i@icloud.com", "#0A84FF")
    folders = {}
    for a, defs in ((g, [("INBOX", "inbox"), ("Trash", "trash"), ("Archive", "archive"), ("Projets", "custom"),
                         ("Spam", "junk")]),
                    (i, [("INBOX", "inbox"), ("Deleted", "trash")])):
        for path, role in defs:
            f = Folder(account_id=a.id, path=path, role=role, display_name=path)
            db.add(f)
            db.flush()
            folders[(a.id, path)] = f
    db.commit()
    fakes = {
        g.id: FakeMailSession({"INBOX": [], "Trash": ["\\Trash"], "Archive": ["\\Archive"], "Projets": [], "Spam": []}),
        i.id: FakeMailSession({"INBOX": [], "Deleted": ["\\Trash"]}),
    }
    monkeypatch.setattr(common, "open_session", lambda account: fakes[account.id])

    class W:
        pass

    w = W()
    w.db, w.g, w.i, w.folders, w.fakes = db, g, i, folders, fakes

    def add(account, path="INBOX", minutes=0, **kw):
        fake = fakes[account.id]
        subject, from_name = kw.pop("subject", "s"), kw.pop("from_name", "")
        text, html = kw.pop("text", None), kw.pop("html", None)
        uid = fake.add_message(path, subject=subject, from_name=from_name, text=text, html=html,
                               seen=kw.get("seen", False))
        m = Message(account_id=account.id, folder_id=folders[(account.id, path)].id, uid=uid,
                    sent_at=BASE + timedelta(minutes=minutes), subject=subject, from_name=from_name,
                    from_addr="x@y.z",
                    message_id_header=fake.messages[path][uid]["message_id"], **kw)
        db.add(m)
        db.commit()
        return m

    w.add = add
    return w
