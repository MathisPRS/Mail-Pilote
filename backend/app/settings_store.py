from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from app.models import KV


class ScheduleSettings(BaseModel):
    full_times: list[str] = Field(default_factory=lambda: ["08:00", "12:00", "16:00", "20:00"])
    light_interval_min: int = 30
    light_start: str = "07:00"
    light_end: str = "23:00"
    days: list[int] = Field(default_factory=lambda: list(range(7)))  # 0 = lundi


class AlertSettings(BaseModel):
    webpush: bool = True
    gotify: bool = False
    gotify_url: str | None = None
    gotify_token_enc: str | None = None
    notify_tt: bool = True
    notify_important: bool = True
    notify_action: bool = True
    notify_summary: bool = False
    quiet_enabled: bool = True
    quiet_from: str = "22:00"
    quiet_to: str = "07:00"
    quiet_tt_bypass: bool = True


class ClaudeSettings(BaseModel):
    token_set_at: datetime | None = None
    warn_days: int = 7


def _get[T: BaseModel](db: DbSession, key: str, model: type[T]) -> T:
    row = db.get(KV, key)
    return model.model_validate_json(row.value_json) if row else model()


def _set[T: BaseModel](db: DbSession, key: str, model: type[T], value: T) -> T:
    value = model.model_validate(value.model_dump())
    payload = value.model_dump_json()
    row = db.get(KV, key)
    if row:
        row.value_json = payload
    else:
        db.add(KV(key=key, value_json=payload))
    db.commit()
    return value


def get_schedule(db: DbSession) -> ScheduleSettings:
    return _get(db, "schedule", ScheduleSettings)


def set_schedule(db: DbSession, value: ScheduleSettings) -> ScheduleSettings:
    return _set(db, "schedule", ScheduleSettings, value)


def get_alerts(db: DbSession) -> AlertSettings:
    return _get(db, "alerts", AlertSettings)


def set_alerts(db: DbSession, value: AlertSettings) -> AlertSettings:
    return _set(db, "alerts", AlertSettings, value)


def get_claude(db: DbSession) -> ClaudeSettings:
    return _get(db, "claude", ClaudeSettings)


def set_claude(db: DbSession, value: ClaudeSettings) -> ClaudeSettings:
    return _set(db, "claude", ClaudeSettings, value)
