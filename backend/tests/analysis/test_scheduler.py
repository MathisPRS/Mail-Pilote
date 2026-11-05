import pytest

from app.analysis import scheduler
from app.settings_store import ScheduleSettings, get_schedule, set_schedule


def by_kind(specs, kind):
    return [s for s in specs if s.kind == kind]


def test_build_jobs_defaults():
    specs = scheduler.build_jobs(ScheduleSettings())
    full = by_kind(specs, "full")
    assert [s.cron["hour"] for s in full] == [8, 12, 16, 20]
    assert all(s.cron["minute"] == 0 for s in full)
    (light,) = by_kind(specs, "light")
    assert light.cron["minute"] == "*/30"
    assert light.cron["hour"] == "7-22"
    (exp,) = by_kind(specs, "claude_expiry")
    assert exp.cron["hour"] == 9 and exp.cron["minute"] == 0


def test_build_jobs_respects_days():
    specs = scheduler.build_jobs(ScheduleSettings(days=[0, 2, 4]))
    for s in by_kind(specs, "full") + by_kind(specs, "light"):
        assert s.cron["day_of_week"] == "0,2,4"
    assert "day_of_week" not in by_kind(specs, "claude_expiry")[0].cron


def test_build_jobs_no_days_means_no_jobs_but_expiry():
    specs = scheduler.build_jobs(ScheduleSettings(days=[]))
    assert [s.kind for s in specs] == ["claude_expiry"]


async def test_start_reload_and_next_runs(db, monkeypatch):
    monkeypatch.delenv("MP_DISABLE_SCHEDULER", raising=False)
    scheduler.start_scheduler(None)
    try:
        ids = {j.id for j in scheduler._scheduler.get_jobs()}
        assert ids == {"light", "full-0", "full-1", "full-2", "full-3", "claude_expiry"}
        nxt = scheduler.next_runs()
        assert nxt["next_light_at"] is not None and nxt["next_full_at"] is not None
        s = get_schedule(db)
        s.full_times = ["10:00"]
        set_schedule(db, s)
        scheduler.reload_scheduler()
        assert {j.id for j in scheduler._scheduler.get_jobs()} == {"light", "full-0", "claude_expiry"}
    finally:
        scheduler.stop_scheduler()
    assert scheduler.next_runs() == {"next_light_at": None, "next_full_at": None}


async def test_disabled_by_env(db):
    scheduler.start_scheduler(None)  # MP_DISABLE_SCHEDULER=1 via conftest
    assert scheduler._scheduler is None
    scheduler.reload_scheduler()  # no-op
