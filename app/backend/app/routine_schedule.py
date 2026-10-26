"""Расписание рутины: когда следующий приём и до какого момента его
имеет смысл напоминать.

Запрос владельца 26.10: таблетки коту и себе несколько раз в день, с
отметкой «дал» и учётом сдвига — если вечернюю дали поздно, утреннюю
нельзя давать раньше положенного зазора; а приём «раз в 24 часа»
считается от реального приёма, не от плана.

ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ, как и recurrence.py: арифметика «следующий слот
после 23:40 с зазором 10 часов» обманчиво простая и ломается на границе
суток, на переходе летнего времени и на последнем дне курса. Считается в
одном месте, без базы, и проверяется тестами.

ДВА РЕЖИМА И НИКАКИХ RRULE:
- «по часам» (times): фиксированные времена дня в поясе рутины, плюс
  минимальный зазор от ПОСЛЕДНЕГО РЕАЛЬНОГО приёма — он только сдвигает
  слот позже, никогда раньше;
- «по интервалу» (interval): каждые N минут от последнего реального
  приёма; пропущенный или отменённый приём отсчитывается от своего плана,
  иначе цепочка «раз в сутки» съехала бы на часы ожидания.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MODE_TIMES = "times"
MODE_INTERVAL = "interval"
MODES = (MODE_TIMES, MODE_INTERVAL)

STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_MISSED = "missed"

# Дольше этого один приём не напоминает ни в каком режиме: сутки без
# отметки — это уже не «забыли нажать», а пропуск, и следующий приём важнее.
MAX_NAG_WINDOW = timedelta(hours=12)


def parse_hhmm(value: str) -> time:
    hours, minutes = value.strip().split(":")
    return time(int(hours), int(minutes))


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _local_day_start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=tz).astimezone(timezone.utc)


def _slots(schedule: dict) -> list[time]:
    slots = sorted({parse_hhmm(t) for t in schedule.get("times") or []})
    if not slots:
        raise ValueError("Режим «по часам» без единого времени")
    return slots


def _first_slot_after(moment: datetime, slots: list[time], tz: ZoneInfo) -> datetime:
    """Ближайший слот СТРОГО ПОЗЖЕ moment. Перебор по дням, а не арифметика
    с timedelta: так переход на зимнее/летнее время не сдвигает 08:00."""
    local = moment.astimezone(tz)
    day = local.date()
    for _ in range(3):
        for slot in slots:
            candidate = datetime.combine(day, slot, tzinfo=tz)
            if candidate > local:
                return candidate.astimezone(timezone.utc)
        day += timedelta(days=1)
    raise AssertionError("слот не найден за три дня — невозможно")


def next_planned(
    schedule: dict,
    *,
    tz: ZoneInfo,
    now: datetime,
    previous: dict | None,
    starts_on: date | None = None,
    ends_on: date | None = None,
) -> datetime | None:
    """Когда следующий приём. None — курс закончился.

    previous — последний приём рутины (словарь из properties.doses) или
    None, если приёмов ещё не было. Для «по часам» отсчёт идёт от плана
    предыдущего приёма (слоты не плывут), а зазор — от реального
    done_at. Для «по интервалу» — от реального приёма, если он был.
    """
    mode = schedule.get("mode", MODE_TIMES)
    floor = now
    if starts_on is not None:
        floor = max(floor, _local_day_start(starts_on, tz))

    if mode == MODE_INTERVAL:
        every = timedelta(minutes=int(schedule.get("every_minutes") or 0))
        if every <= timedelta(0):
            raise ValueError("Интервал должен быть положительным")
        if previous is None:
            planned = _first_interval_dose(schedule, floor, tz)
        else:
            base_raw = previous.get("done_at") if previous.get("status") == STATUS_DONE else None
            base = _parse_dt(base_raw or previous["planned_at"])
            planned = base + every
            # План ещё не наступил, а предыдущий уже закрыли (дали раньше
            # времени): следующий всё равно не раньше интервала от факта.
            if planned < floor and previous.get("status") != STATUS_DONE:
                planned = _first_interval_dose(schedule, floor, tz)
    else:
        slots = _slots(schedule)
        if previous is None:
            # Минус секунда: слот ровно в момент старта тоже считается.
            reference = floor - timedelta(seconds=1)
        else:
            # Слоты не плывут: отталкиваемся от плана предыдущего, а не от
            # момента, когда его закрыли. Но и в прошлое не заглядываем:
            # рутина, которую не трогали неделю, продолжает с ближайшего
            # будущего слота, а не догоняет пропущенные.
            reference = max(_parse_dt(previous["planned_at"]), now - timedelta(minutes=1))
        planned = _first_slot_after(reference, slots, tz)
        gap = timedelta(minutes=int(schedule.get("min_gap_minutes") or 0))
        if previous is not None and previous.get("status") == STATUS_DONE and previous.get("done_at") and gap > timedelta(0):
            earliest = _parse_dt(previous["done_at"]) + gap
            if earliest > planned:
                planned = earliest

    if ends_on is not None and planned.astimezone(tz).date() > ends_on:
        return None
    return planned


def _first_interval_dose(schedule: dict, floor: datetime, tz: ZoneInfo) -> datetime:
    """Первый приём в режиме «по интервалу»: в указанное время (first_at)
    сегодня или завтра, а без него — через пять минут, округлённо."""
    first_at = schedule.get("first_at")
    if first_at:
        return _first_slot_after(floor - timedelta(seconds=1), [parse_hhmm(first_at)], tz)
    rounded = floor + timedelta(minutes=5)
    return rounded.replace(second=0, microsecond=0)


def nag_until(schedule: dict, planned: datetime, *, tz: ZoneInfo) -> datetime:
    """До какого момента напоминать об этом приёме, если его не отмечают.

    До следующего слота (минус пять минут, чтобы два пинга не наложились)
    или до половины интервала — но не дольше MAX_NAG_WINDOW.
    """
    if schedule.get("mode", MODE_TIMES) == MODE_INTERVAL:
        every = timedelta(minutes=int(schedule.get("every_minutes") or 0))
        limit = planned + every / 2
    else:
        limit = _first_slot_after(planned, _slots(schedule), tz) - timedelta(minutes=5)
    return min(limit, planned + MAX_NAG_WINDOW)


def describe(schedule: dict) -> str:
    """«в 08:00 и 20:00» / «каждые 24 ч» — для подписи и текста заметки."""
    if schedule.get("mode", MODE_TIMES) == MODE_INTERVAL:
        minutes = int(schedule.get("every_minutes") or 0)
        if minutes % 1440 == 0:
            days = minutes // 1440
            return "каждый день" if days == 1 else f"каждые {days} дн."
        if minutes % 60 == 0:
            return f"каждые {minutes // 60} ч"
        return f"каждые {minutes} мин"
    times = [t.strftime("%H:%M") for t in _slots(schedule)]
    if len(times) == 1:
        return f"в {times[0]}"
    return "в " + ", ".join(times[:-1]) + f" и {times[-1]}"
