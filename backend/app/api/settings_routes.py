import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.analysis.scheduler import reload_scheduler
from app.auth.deps import current_user
from app.crypto import encrypt
from app.db import get_db
from app.settings_store import (
    AlertSettings, ScheduleSettings, get_alerts, get_schedule, set_alerts, set_schedule,
)

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(current_user)])

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _hhmm(v: str) -> str:
    if not _HHMM.match(v):
        raise ValueError("heure attendue au format HH:MM")
    return v


class ScheduleIn(BaseModel):
    full_times: list[str] = Field(min_length=1, max_length=8)
    light_interval_min: int
    light_start: str
    light_end: str
    days: list[int]

    @field_validator("full_times")
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        return sorted({_hhmm(t) for t in v})

    @field_validator("light_start", "light_end")
    @classmethod
    def _bounds(cls, v: str) -> str:
        return _hhmm(v)

    @field_validator("light_interval_min")
    @classmethod
    def _interval(cls, v: int) -> int:
        if v not in (15, 30, 60):
            raise ValueError("intervalle attendu : 15, 30 ou 60")
        return v

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("jour attendu entre 0 (lundi) et 6 (dimanche)")
        return sorted(set(v))

    @model_validator(mode="after")
    def _order(self):
        if self.light_start >= self.light_end:
            raise ValueError("light_start doit précéder light_end")
        return self


@router.get("/schedule")
def read_schedule(db: Session = Depends(get_db)) -> dict:
    return get_schedule(db).model_dump()


@router.put("/schedule")
def write_schedule(body: ScheduleIn, db: Session = Depends(get_db)) -> dict:
    saved = set_schedule(db, ScheduleSettings(**body.model_dump()))
    reload_scheduler()
    return saved.model_dump()


class AlertsIn(BaseModel):
    webpush: bool
    gotify: bool
    gotify_url: str | None = None
    gotify_token: str | None = Field(default=None, max_length=512)  # écriture seule
    notify_tt: bool
    notify_important: bool
    notify_action: bool
    notify_summary: bool
    quiet_enabled: bool
    quiet_from: str
    quiet_to: str
    quiet_tt_bypass: bool

    @field_validator("quiet_from", "quiet_to")
    @classmethod
    def _times(cls, v: str) -> str:
        return _hhmm(v)

    @field_validator("gotify_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        u = urlparse(v)
        if u.scheme not in ("http", "https") or not u.hostname or len(v) > 2048:
            raise ValueError("URL http(s) attendue")
        return v.rstrip("/")


def _alerts_out(a: AlertSettings) -> dict:
    out = a.model_dump(exclude={"gotify_token_enc"})
    out["gotify_token_set"] = bool(a.gotify_token_enc)
    return out


@router.get("/alerts")
def read_alerts(db: Session = Depends(get_db)) -> dict:
    return _alerts_out(get_alerts(db))


@router.put("/alerts")
def write_alerts(body: AlertsIn, db: Session = Depends(get_db)) -> dict:
    current = get_alerts(db)
    data = body.model_dump(exclude={"gotify_token"})
    token_enc = current.gotify_token_enc  # absent/null : on garde ; "" : on efface
    if body.gotify_token is not None:
        token_enc = encrypt(body.gotify_token) if body.gotify_token else None
    return _alerts_out(set_alerts(db, AlertSettings(**data, gotify_token_enc=token_enc)))
