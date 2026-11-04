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


# --- бытовые дела: интервал в днях плюс дни недели (04.11) -----------------

# Ориентир: 7 ноября 2026 — суббота.
CHORE = {"mode": "interval", "every_minutes": 30 * 1440, "first_at": "10:00", "weekdays": [5]}


def test_chore_counts_from_actual_done_and_snaps_forward_to_weekday():
    previous = {
        "planned_at": _utc(_local(2026, 11, 7, 10, 0)).isoformat(),
        "status": STATUS_DONE,
        "done_at": _utc(_local(2026, 11, 7, 14, 37)).isoformat(),
    }
    planned = next_planned(CHORE, tz=TZ, now=_local(2026, 11, 7, 14, 38), previous=previous)
    # 7.12 — понедельник; ближайшая суббота — 12.12, время — first_at, не 14:37.
    assert planned == _utc(_local(2026, 12, 12, 10, 0))


def test_chore_allows_several_weekdays_and_keeps_same_day_if_it_fits():
    weekend = {**CHORE, "weekdays": [5, 6]}
    previous = {"planned_at": _utc(_local(2026, 11, 8, 10, 0)).isoformat(), "status": STATUS_DONE, "done_at": _utc(_local(2026, 11, 8, 11, 0)).isoformat()}
    # 8.12 — вторник → суббота 12.12.
    assert next_planned(weekend, tz=TZ, now=_local(2026, 11, 8, 11, 1), previous=previous) == _utc(_local(2026, 12, 12, 10, 0))
    # Сделали 12.11 (четверг): 12.12 — суббота, попадает сама.
    previous = {"planned_at": _utc(_local(2026, 11, 7, 10, 0)).isoformat(), "status": STATUS_DONE, "done_at": _utc(_local(2026, 11, 12, 9, 0)).isoformat()}
    assert next_planned(weekend, tz=TZ, now=_local(2026, 11, 12, 9, 1), previous=previous) == _utc(_local(2026, 12, 12, 10, 0))


def test_missed_chore_moves_to_next_allowed_day_not_next_cycle():
    previous = {"planned_at": _utc(_local(2026, 11, 7, 10, 0)).isoformat(), "status": STATUS_MISSED}
    # Пропустили субботу — следующая суббота, а не через месяц.
    assert next_planned(CHORE, tz=TZ, now=_local(2026, 11, 7, 22, 0), previous=previous) == _utc(_local(2026, 11, 14, 10, 0))
    weekend = {**CHORE, "weekdays": [5, 6]}
    assert next_planned(weekend, tz=TZ, now=_local(2026, 11, 7, 22, 0), previous=previous) == _utc(_local(2026, 11, 8, 10, 0))
    # Без дней недели, но интервал в месяц — завтра.
    plain = {"mode": "interval", "every_minutes": 30 * 1440, "first_at": "10:00"}
    assert next_planned(plain, tz=TZ, now=_local(2026, 11, 7, 22, 0), previous=previous) == _utc(_local(2026, 11, 8, 10, 0))
    # А ежедневная таблетка пропуск отсчитывает от плана, как и раньше.
    assert next_planned(DAILY, tz=TZ, now=_local(2026, 11, 7, 22, 0), previous=previous) == _utc(_local(2026, 11, 8, 10, 0))


def test_skipped_chore_counts_as_done_for_the_cycle():
    previous = {"planned_at": _utc(_local(2026, 11, 7, 10, 0)).isoformat(), "status": "skipped"}
    assert next_planned(CHORE, tz=TZ, now=_local(2026, 11, 7, 12, 0), previous=previous) == _utc(_local(2026, 12, 12, 10, 0))


def test_chore_first_dose_is_first_allowed_day_on_or_after_start():
    # Создали в среду 4.11 без даты старта — ближайшая суббота 7.11 в 10:00.
    assert next_planned(CHORE, tz=TZ, now=_local(2026, 11, 4, 15, 0), previous=None) == _utc(_local(2026, 11, 7, 10, 0))
    # «Сделал сегодня» → старт через 30 дней (4.12, пятница) → суббота 5.12.
    assert next_planned(CHORE, tz=TZ, now=_local(2026, 11, 4, 15, 0), previous=None, starts_on=date(2026, 12, 4)) == _utc(_local(2026, 12, 5, 10, 0))
    # В саму субботу после 10:00 — уже следующая.
    assert next_planned(CHORE, tz=TZ, now=_local(2026, 11, 7, 11, 0), previous=None) == _utc(_local(2026, 11, 14, 10, 0))


def test_describe_chore():
    assert describe(CHORE) == "каждые 30 дн., по сб в 10:00"
    assert describe({**CHORE, "weekdays": [5, 6], "first_at": None}) == "каждые 30 дн., по сб, вс"
    assert describe({"mode": "interval", "every_minutes": 60 * 1440, "first_at": "09:00"}) == "каждые 60 дн. в 09:00"
    assert describe({"mode": "interval", "every_minutes": 480, "first_at": "09:00"}) == "каждые 8 ч"
