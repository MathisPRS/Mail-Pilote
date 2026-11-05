import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db as db_module
from app.analysis import jobs, scheduler
from app.api.common import iso
from app.auth.deps import current_user
from app.db import get_db
from app.models import AnalysisRun

router = APIRouter(prefix="/api", tags=["runs"], dependencies=[Depends(current_user)])

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()


class RunIn(BaseModel):
    kind: Literal["light", "full"]


def run_dict(r: AnalysisRun | None) -> dict | None:
    if r is None:
        return None
    return {
        "id": r.id, "kind": r.kind, "trigger": r.trigger, "status": r.status,
        "started_at": iso(r.started_at), "finished_at": iso(r.finished_at),
        "mails_count": r.mails_count, "error": r.error,
    }


async def _background(kind: str) -> None:
    try:
        with db_module.SessionLocal() as s:
            runner = jobs.run_light if kind == "light" else jobs.run_full
            await runner(s, trigger="manual")
    except Exception:  # noqa: BLE001 - tâche de fond : journalisée, sans données sensibles
        log.exception("run %s manuel en échec", kind)


def start_background(kind: str) -> asyncio.Task:
    """Lance une session d'analyse manuelle en tâche de fond (la requête n'attend pas)."""
    task = asyncio.create_task(_background(kind))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _running(db: Session) -> AnalysisRun | None:
    db.expire_all()
    return db.scalar(select(AnalysisRun).where(AnalysisRun.status == "running").order_by(AnalysisRun.id.desc()))


@router.post("/runs", status_code=202)
async def start_run(body: RunIn, db: Session = Depends(get_db)) -> dict:
    running = _running(db)
    if running is not None:  # une session est déjà en cours : on renvoie celle-là
        return run_dict(running)
    before = db.scalar(select(AnalysisRun.id).order_by(AnalysisRun.id.desc()).limit(1)) or 0
    task = start_background(body.kind)
    for _ in range(100):  # la ligne du run est créée dès le démarrage de la tâche
        await asyncio.sleep(0.02)
        db.expire_all()
        run = db.scalar(select(AnalysisRun).where(AnalysisRun.id > before).order_by(AnalysisRun.id).limit(1))
        if run is not None:
            return run_dict(run)
        if task.done():
            break
    return JSONResponse(  # démarrage non confirmé : le front relira /api/runs/latest
        status_code=202,
        content={"id": None, "kind": body.kind, "trigger": "manual", "status": "running",
                 "started_at": None, "finished_at": None, "mails_count": 0, "error": None},
    )


@router.get("/runs/latest")
def latest(db: Session = Depends(get_db)) -> dict:
    def last(kind: str):
        return db.scalar(select(AnalysisRun).where(AnalysisRun.kind == kind).order_by(AnalysisRun.id.desc()).limit(1))

    nxt = scheduler.next_runs()
    return {
        "light": run_dict(last("light")),
        "full": run_dict(last("full")),
        "next_full_at": iso(nxt["next_full_at"]),
        "next_light_at": iso(nxt["next_light_at"]),
    }
