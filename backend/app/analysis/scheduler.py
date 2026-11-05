"""Planificateur APScheduler : vérification légère, tri complet, contrôle d'expiration du jeton."""
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app import db as db_module
from app.analysis import jobs
from app.claude.status import check_expiry
from app.config import get_settings
from app.settings_store import ScheduleSettings, get_schedule

log = logging.getLogger(__name__)

JobKind = Literal["light", "full", "claude_expiry"]
MISFIRE_GRACE_S = 300

_scheduler: AsyncIOScheduler | None = None


@dataclass
class JobSpec:
    kind: JobKind
    cron: dict = field(default_factory=dict)


def _hm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def build_jobs(schedule: ScheduleSettings) -> list[JobSpec]:
    specs: list[JobSpec] = []
    days = sorted(set(schedule.days))
    dow = {"day_of_week": ",".join(str(d) for d in days)}
    if days:
        for t in schedule.full_times:
            h, m = _hm(t)
            specs.append(JobSpec("full", {"hour": h, "minute": m, **dow}))
        start_h, _ = _hm(schedule.light_start)
        end_h, end_m = _hm(schedule.light_end)
        last = end_h - 1 if end_m == 0 else end_h
        last = max(last, start_h)
        specs.append(JobSpec("light", {
            "minute": f"*/{schedule.light_interval_min}", "hour": f"{start_h}-{last}", **dow,
        }))
    specs.append(JobSpec("claude_expiry", {"hour": 9, "minute": 0}))
    return specs


async def job_light() -> None:
    with db_module.SessionLocal() as db:
        await jobs.run_light(db, "schedule")


async def job_full() -> None:
    with db_module.SessionLocal() as db:
        await jobs.run_full(db, "schedule")


async def job_claude_expiry() -> None:
    with db_module.SessionLocal() as db:
        await check_expiry(db, datetime.now(timezone.utc))


_FUNCS = {"light": job_light, "full": job_full, "claude_expiry": job_claude_expiry}


def _install_jobs() -> None:
    assert _scheduler is not None
    with db_module.SessionLocal() as db:
        schedule = get_schedule(db)
    for job in _scheduler.get_jobs():
        job.remove()
    counters: dict[str, int] = {}
    for spec in build_jobs(schedule):
        n = counters.get(spec.kind, 0)
        counters[spec.kind] = n + 1
        job_id = f"full-{n}" if spec.kind == "full" else spec.kind
        _scheduler.add_job(
            _FUNCS[spec.kind],
            CronTrigger(timezone=_scheduler.timezone, **spec.cron),
            id=job_id,
            misfire_grace_time=MISFIRE_GRACE_S,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )


def start_scheduler(app=None) -> None:
    global _scheduler
    if os.environ.get("MP_DISABLE_SCHEDULER") == "1" or _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone=get_settings().tz)
    _install_jobs()
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def reload_scheduler() -> None:
    """À appeler après modification du planning : remplace les jobs depuis la base."""
    if _scheduler is not None:
        _install_jobs()


def next_runs() -> dict[str, datetime | None]:
    out: dict[str, datetime | None] = {"next_light_at": None, "next_full_at": None}
    if _scheduler is None:
        return out
    for job in _scheduler.get_jobs():
        key = "next_light_at" if job.id == "light" else "next_full_at" if job.id.startswith("full") else None
        nxt = getattr(job, "next_run_time", None)
        if key and nxt and (out[key] is None or nxt < out[key]):
            out[key] = nxt
    return out
