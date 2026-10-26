import re
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleIn(BaseModel):
    """Расписание (app/routine_schedule.py): «по часам» или «по интервалу»."""

    mode: Literal["times", "interval"] = "times"
    times: list[str] = Field(default_factory=list)
    every_minutes: int | None = Field(default=None, ge=5, le=60 * 24 * 30)
    # Минимальный зазор от реального приёма (только «по часам»).
    min_gap_minutes: int = Field(default=0, ge=0, le=60 * 24 * 7)
    # Первый приём «по интервалу» — во сколько; пусто — через пять минут.
    first_at: str | None = None

    @field_validator("times")
    @classmethod
    def _times_format(cls, value: list[str]) -> list[str]:
        cleaned = sorted({v.strip() for v in value if v.strip()})
        for v in cleaned:
            if not _HHMM.match(v):
                raise ValueError(f"Время «{v}» — нужно ЧЧ:ММ")
        return cleaned

    @field_validator("first_at")
    @classmethod
    def _first_at_format(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if not _HHMM.match(value.strip()):
            raise ValueError("first_at — ЧЧ:ММ")
        return value.strip()

    @model_validator(mode="after")
    def _mode_fields(self) -> "ScheduleIn":
        if self.mode == "times" and not self.times:
            raise ValueError("Укажи хотя бы одно время")
        if self.mode == "interval" and not self.every_minutes:
            raise ValueError("Укажи интервал в минутах")
        return self


class RoutineCreate(BaseModel):
    space_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    title: str = Field(default="", max_length=500)
    subject: str = Field(default="", max_length=200)
    dose: str = Field(default="", max_length=500)
    schedule: ScheduleIn
    starts_on: date | None = None
    ends_on: date | None = None
    notify: Literal["space", "self"] = "space"
    nag_minutes: int = Field(default=30, ge=0, le=720)
    timezone: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _course(self) -> "RoutineCreate":
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("Конец курса раньше начала")
        return self


class RoutineUpdate(BaseModel):
    """Поля применяются, только если явно присутствуют (как ItemUpdate)."""

    title: str | None = Field(default=None, max_length=500)
    subject: str | None = Field(default=None, max_length=200)
    dose: str | None = Field(default=None, max_length=500)
    schedule: ScheduleIn | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    notify: Literal["space", "self"] | None = None
    nag_minutes: int | None = Field(default=None, ge=0, le=720)
    timezone: str | None = Field(default=None, max_length=64)
    paused: bool | None = None


class DoseOut(BaseModel):
    id: str
    planned_at: datetime
    status: str
    done_at: datetime | None = None
    done_by: str | None = None
    done_by_name: str | None = None
    deferred_by: list[dict] = []
    snoozed_until: datetime | None = None
    nag_until: datetime | None = None
    late: bool = False


class RoutineStats(BaseModel):
    done: int = 0
    late: int = 0
    missed: int = 0
    skipped: int = 0


class RoutineOut(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    folder_id: uuid.UUID | None
    author_id: uuid.UUID
    title: str
    subject: str
    dose: str
    schedule: dict
    schedule_text: str
    starts_on: date | None
    ends_on: date | None
    notify: str
    nag_minutes: int
    timezone: str
    paused: bool
    status: str
    doses: list[DoseOut]
    next_at: datetime | None
    stats: RoutineStats
    created_at: datetime
    updated_at: datetime


class DoseDoneIn(BaseModel):
    at: datetime | None = None
    by: uuid.UUID | None = None


class DoseSnoozeIn(BaseModel):
    minutes: int = Field(ge=5, le=720)
