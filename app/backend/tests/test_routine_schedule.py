from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.routine_schedule import STATUS_DONE, STATUS_MISSED, describe, nag_until, next_planned

TZ = ZoneInfo("Europe/Warsaw")
TIMES = {"mode": "times", "times": ["08:00", "20:00"], "min_gap_minutes": 600}
DAILY = {"mode": "interval", "every_minutes": 1440}


def _local(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def _utc(dt):
    return dt.astimezone(timezone.utc)


def test_first_dose_is_next_slot_after_now():
    now = _local(2026, 10, 26, 9, 30)
    planned = next_planned(TIMES, tz=TZ, now=now, previous=None)
    assert planned == _utc(_local(2026, 10, 26, 20, 0))


def test_first_dose_respects_start_date():
    now = _local(2026, 10, 26, 9, 30)
    planned = next_planned(TIMES, tz=TZ, now=now, previous=None, starts_on=date(2026, 10, 28))
    assert planned == _utc(_local(2026, 10, 28, 8, 0))


def test_slots_do_not_drift_after_early_dose():
    # Вечернюю дали в 19:00 вместо 20:00 — утренняя всё равно в 08:00.
    previous = {
        "planned_at": _utc(_local(2026, 10, 26, 20, 0)).isoformat(),
        "status": STATUS_DONE,
        "done_at": _utc(_local(2026, 10, 26, 19, 0)).isoformat(),
    }
    planned = next_planned(TIMES, tz=TZ, now=_local(2026, 10, 26, 19, 1), previous=previous)
    assert planned == _utc(_local(2026, 10, 27, 8, 0))


def test_min_gap_pushes_next_slot_later_never_earlier():
    # Вечернюю дали в 23:30 — зазор 10 ч: утренняя не раньше 09:30.
    previous = {
        "planned_at": _utc(_local(2026, 10, 26, 20, 0)).isoformat(),
        "status": STATUS_DONE,
        "done_at": _utc(_local(2026, 10, 26, 23, 30)).isoformat(),
    }
    planned = next_planned(TIMES, tz=TZ, now=_local(2026, 10, 26, 23, 31), previous=previous)
    assert planned == _utc(_local(2026, 10, 27, 9, 30))


def test_missed_dose_does_not_shift_slots():
    previous = {"planned_at": _utc(_local(2026, 10, 26, 8, 0)).isoformat(), "status": STATUS_MISSED}
    planned = next_planned(TIMES, tz=TZ, now=_local(2026, 10, 26, 19, 55), previous=previous)
    assert planned == _utc(_local(2026, 10, 26, 20, 0))


def test_stale_routine_continues_from_now_not_from_backlog():
    # Неделю не трогали: продолжает с ближайшего будущего слота.
    previous = {"planned_at": _utc(_local(2026, 10, 19, 8, 0)).isoformat(), "status": STATUS_MISSED}
    planned = next_planned(TIMES, tz=TZ, now=_local(2026, 10, 26, 12, 0), previous=previous)
    assert planned == _utc(_local(2026, 10, 26, 20, 0))


def test_course_end_returns_none():
    previous = {"planned_at": _utc(_local(2026, 11, 8, 20, 0)).isoformat(), "status": STATUS_DONE,
                "done_at": _utc(_local(2026, 11, 8, 20, 5)).isoformat()}
    planned = next_planned(TIMES, tz=TZ, now=_local(2026, 11, 8, 20, 6), previous=previous, ends_on=date(2026, 11, 8))
    assert planned is None


def test_interval_counts_from_actual_dose():
    previous = {
        "planned_at": _utc(_local(2026, 10, 26, 20, 0)).isoformat(),
        "status": STATUS_DONE,
        "done_at": _utc(_local(2026, 10, 26, 22, 15)).isoformat(),
    }
    planned = next_planned(DAILY, tz=TZ, now=_local(2026, 10, 26, 22, 16), previous=previous)
    assert planned == _utc(_local(2026, 10, 27, 22, 15))


def test_interval_missed_counts_from_plan():
    previous = {"planned_at": _utc(_local(2026, 10, 26, 20, 0)).isoformat(), "status": STATUS_MISSED}
    planned = next_planned(DAILY, tz=TZ, now=_local(2026, 10, 27, 8, 0), previous=previous)
    assert planned == _utc(_local(2026, 10, 27, 20, 0))


def test_interval_first_dose_at_given_time():
    schedule = {**DAILY, "first_at": "21:00"}
    planned = next_planned(schedule, tz=TZ, now=_local(2026, 10, 26, 9, 0), previous=None)
    assert planned == _utc(_local(2026, 10, 26, 21, 0))


def test_interval_first_dose_without_time_is_soon():
    now = _local(2026, 10, 26, 9, 0)
    planned = next_planned(DAILY, tz=TZ, now=now, previous=None)
    assert planned == _utc(now + timedelta(minutes=5))


def test_dst_transition_keeps_wall_clock_time():
    # Ночь 25.10.2026 — переход на зимнее время в Европе: 08:00 остаётся 08:00.
    previous = {"planned_at": _utc(_local(2026, 10, 24, 20, 0)).isoformat(), "status": STATUS_MISSED}
    planned = next_planned(TIMES, tz=TZ, now=_local(2026, 10, 24, 20, 1), previous=previous)
    assert planned.astimezone(TZ).strftime("%d %H:%M") == "25 08:00"


def test_nag_until_stops_before_next_slot_and_within_window():
    planned = _utc(_local(2026, 10, 26, 8, 0))
    assert nag_until(TIMES, planned, tz=TZ) == _utc(_local(2026, 10, 26, 19, 55))
    single = {"mode": "times", "times": ["08:00"]}
    assert nag_until(single, planned, tz=TZ) == planned + timedelta(hours=12)
    assert nag_until(DAILY, planned, tz=TZ) == planned + timedelta(hours=12)


def test_describe():
    assert describe(TIMES) == "в 08:00 и 20:00"
    assert describe({"mode": "times", "times": ["09:00"]}) == "в 09:00"
    assert describe(DAILY) == "каждый день"
    assert describe({"mode": "interval", "every_minutes": 480}) == "каждые 8 ч"


def test_times_mode_requires_a_time():
    with pytest.raises(ValueError):
        next_planned({"mode": "times", "times": []}, tz=TZ, now=_local(2026, 10, 26, 9, 0), previous=None)
