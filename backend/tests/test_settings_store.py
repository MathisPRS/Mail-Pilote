from datetime import datetime, timezone

from app.models import KV, MailAccount
from app.settings_store import (
    AlertSettings,
    ClaudeSettings,
    ScheduleSettings,
    get_alerts,
    get_claude,
    get_schedule,
    set_alerts,
    set_claude,
    set_schedule,
)


def test_schedule_defaults(db):
    s = get_schedule(db)
    assert s.full_times == ["08:00", "12:00", "16:00", "20:00"]
    assert s.light_interval_min == 30
    assert s.light_start == "07:00"
    assert s.light_end == "23:00"
    assert s.days == [0, 1, 2, 3, 4, 5, 6]


def test_alert_defaults(db):
    a = get_alerts(db)
    assert a == AlertSettings()
    assert a.webpush is True
    assert a.gotify is False
    assert a.gotify_url is None
    assert (a.notify_tt, a.notify_important, a.notify_action, a.notify_summary) == (True, True, True, False)
    assert (a.quiet_enabled, a.quiet_from, a.quiet_to, a.quiet_tt_bypass) == (True, "22:00", "07:00", True)


def test_schedule_roundtrip(db):
    set_schedule(db, ScheduleSettings(full_times=["09:00"], light_interval_min=15,
                                      light_start="08:00", light_end="22:00", days=[0, 1]))
    db.expire_all()
    s = get_schedule(db)
    assert s.full_times == ["09:00"] and s.light_interval_min == 15 and s.days == [0, 1]
    assert db.get(KV, "schedule") is not None


def test_claude_roundtrip_and_alerts(db):
    assert get_claude(db) == ClaudeSettings()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    set_claude(db, ClaudeSettings(token_set_at=now))
    assert get_claude(db).token_set_at == now
    set_alerts(db, AlertSettings(gotify=True, gotify_url="http://g"))
    assert get_alerts(db).gotify_url == "http://g"


def test_model_defaults_and_utc(db):
    acc = MailAccount(provider="imap", label="L", email="a@b.c", imap_host="h",
                      imap_port=993, username="u", secret_enc="x")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    assert acc.enabled is True and acc.status == "ok"


def test_datetimes_are_utc_aware(db):
    from app.models import PushSubscription

    sub = PushSubscription(endpoint="e", p256dh="p", auth="a")
    db.add(sub)
    db.commit()
    db.expire_all()
    got = db.get(PushSubscription, sub.id)
    assert got.created_at.tzinfo is not None
    assert got.created_at.utcoffset().total_seconds() == 0
