from datetime import datetime, time, timedelta, timezone

import pytest

from app.crypto import encrypt
from app.models import KV, Folder, MailAccount, Message, PushSubscription
from app.notify import dispatcher, gotify, webpush
from app.notify.dispatcher import dispatch_alerts, is_quiet, send_system_alert
from app.settings_store import AlertSettings, get_alerts, set_alerts

# 2026-11-05 est en heure d'hiver : Paris = UTC+1
NOON = datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc)  # 12:00 Paris
NIGHT = datetime(2026, 11, 5, 22, 30, tzinfo=timezone.utc)  # 23:30 Paris


@pytest.mark.parametrize(
    "now,frm,to,expected",
    [
        (time(23, 30), "22:00", "07:00", True),
        (time(6, 59), "22:00", "07:00", True),
        (time(7, 0), "22:00", "07:00", False),
        (time(21, 59), "22:00", "07:00", False),
        (time(12, 0), "00:00", "00:00", False),
        (time(3, 0), "00:00", "00:00", False),
        (time(13, 0), "12:00", "14:00", True),
        (time(15, 0), "12:00", "14:00", False),
    ],
)
def test_is_quiet(now, frm, to, expected):
    assert is_quiet(now, frm, to) is expected


@pytest.fixture
def sent(monkeypatch):
    calls = {"gotify": [], "webpush": []}

    async def fake_gotify(url, token, title, message, priority, click_url=None):
        calls["gotify"].append((url, token, title, message, priority, click_url))

    def fake_webpush(sub, payload):
        calls["webpush"].append((sub.endpoint, payload))

    monkeypatch.setattr(gotify, "send_gotify", fake_gotify)
    monkeypatch.setattr(webpush, "send_webpush", fake_webpush)
    return calls


@pytest.fixture
def folder(db):
    acc = MailAccount(
        provider="imap", label="L", email="a@b.c", imap_host="h", username="u", secret_enc="x"
    )
    db.add(acc)
    db.flush()
    f = Folder(account_id=acc.id, path="INBOX", role="inbox", display_name="INBOX")
    db.add(f)
    db.commit()
    return f


_uid = [0]


def mk(db, folder, category="important", now=NOON, **kw):
    _uid[0] += 1
    fields = dict(
        account_id=folder.account_id, folder_id=folder.id, uid=_uid[0], from_name="Alice",
        subject="Sujet", category=category, priority=True, reason="Parce que",
        sent_at=now - timedelta(minutes=5), created_at=now - timedelta(minutes=5),
    )
    fields.update(kw)
    m = Message(**fields)
    db.add(m)
    db.commit()
    return m


def configure(db, **kw):
    s = AlertSettings(
        webpush=False, gotify=True, gotify_url="http://gotify.local/",
        gotify_token_enc=encrypt("tok"), **kw,
    )
    set_alerts(db, s)


async def test_sends_with_content_and_marks_alerted(db, folder, sent):
    configure(db)
    m = mk(db, folder, category="tt", subject="Jeudi TT+")
    assert await dispatch_alerts(db, now=NOON) == 1
    url, token, title, body, prio, click = sent["gotify"][0]
    assert (url, token, title, body, prio) == ("http://gotify.local/", "tok", "TT+ · Jeudi TT+", "Parce que", 8)
    assert click == f"/mail/{m.id}"
    db.refresh(m)
    assert m.alerted_at is not None


async def test_titles_and_priority(db, folder, sent):
    configure(db)
    mk(db, folder, category="tt", subject="Jeudi TT+")
    mk(db, folder, category="important")
    mk(db, folder, category="action")
    assert await dispatch_alerts(db, now=NOON) == 3
    got = {c[2]: c[4] for c in sent["gotify"]}
    assert got == {"TT+ · Jeudi TT+": 8, "Important · Alice": 5, "À traiter · Alice": 5}


async def test_no_double_alert(db, folder, sent):
    configure(db)
    mk(db, folder)
    assert await dispatch_alerts(db, now=NOON) == 1
    assert await dispatch_alerts(db, now=NOON) == 0
    assert len(sent["gotify"]) == 1


async def test_tt_bypasses_quiet(db, folder, sent):
    configure(db)
    mk(db, folder, category="tt", now=NIGHT)
    assert await dispatch_alerts(db, now=NIGHT) == 1


async def test_tt_does_not_bypass_when_option_off(db, folder, sent):
    configure(db, quiet_tt_bypass=False)
    mk(db, folder, category="tt", now=NIGHT)
    assert await dispatch_alerts(db, now=NIGHT) == 0


async def test_important_held_during_quiet_then_sent(db, folder, sent):
    configure(db)
    m = mk(db, folder, category="important", now=NIGHT)
    assert await dispatch_alerts(db, now=NIGHT) == 0
    db.refresh(m)
    assert m.alerted_at is None
    morning = datetime(2026, 11, 6, 6, 5, tzinfo=timezone.utc)  # 07:05 Paris
    assert await dispatch_alerts(db, now=morning) == 1


async def test_disabled_type_not_sent(db, folder, sent):
    configure(db, notify_important=False)
    mk(db, folder, category="important")
    assert await dispatch_alerts(db, now=NOON) == 0
    assert sent["gotify"] == []


async def test_old_messages_never_alerted(db, folder, sent):
    configure(db)
    mk(db, folder, created_at=NOON - timedelta(hours=25))
    mk(db, folder, sent_at=NOON - timedelta(days=5))  # vieux mail découvert tard
    assert await dispatch_alerts(db, now=NOON) == 0


async def test_no_channel_keeps_alerted_unset(db, folder, sent):
    set_alerts(db, AlertSettings(webpush=False, gotify=False))
    m = mk(db, folder)
    assert await dispatch_alerts(db, now=NOON) == 0
    db.refresh(m)
    assert m.alerted_at is None
    configure(db)
    assert await dispatch_alerts(db, now=NOON) == 1


async def test_all_channels_failing_leaves_unset_for_retry(db, folder, monkeypatch):
    configure(db)

    async def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(gotify, "send_gotify", boom)
    m = mk(db, folder)
    assert await dispatch_alerts(db, now=NOON) == 0
    db.refresh(m)
    assert m.alerted_at is None


async def test_webpush_channel(db, folder, sent):
    set_alerts(db, AlertSettings(webpush=True, gotify=False))
    db.add(PushSubscription(endpoint="https://push/1", p256dh="k", auth="a"))
    db.commit()
    m = mk(db, folder, category="action")
    assert await dispatch_alerts(db, now=NOON) == 1
    endpoint, payload = sent["webpush"][0]
    assert endpoint == "https://push/1"
    assert payload == {"title": "À traiter · Alice", "body": "Parce que", "url": f"/mail/{m.id}"}


async def test_system_alert_deduplicated_24h(db, sent):
    configure(db)
    assert await send_system_alert(db, "Claude déconnecté", "Reconnecte", "claude-down") is True
    assert await send_system_alert(db, "Claude déconnecté", "Reconnecte", "claude-down") is False
    assert len(sent["gotify"]) == 1
    row = db.get(KV, "sysalert:claude-down")
    assert row is not None
    row.value_json = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    db.commit()
    assert await send_system_alert(db, "Claude déconnecté", "Reconnecte", "claude-down") is True


async def test_expired_push_subscription_removed(db, monkeypatch):
    from pywebpush import WebPushException

    class Resp:
        status_code = 410

    def fake(**kw):
        raise WebPushException("gone", response=Resp())

    monkeypatch.setattr(webpush, "webpush", fake)
    monkeypatch.setattr(webpush, "ensure_vapid_keys", lambda: "pub")
    monkeypatch.setattr(webpush, "_vapid_private_path", lambda: "/nonexistent")
    sub = PushSubscription(endpoint="https://push/old", p256dh="k", auth="a")
    db.add(sub)
    db.commit()
    set_alerts(db, AlertSettings(webpush=True, gotify=False))
    await dispatcher.send_to_channels(db, get_alerts(db), "t", "b", "/", 5)
    assert db.query(PushSubscription).count() == 0
