"""Повторяющиеся напоминания: когда наступит следующий раз.

Запрос владельца: «каждый понедельник», «раз в месяц оплатить» —
приходилось заводить заново каждый раз, потому что все напоминания были
одноразовыми.

ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ, а не три строки в диспетчере. Арифметика дат
обманчиво простая: «через месяц» от 31 января — это не 31 февраля, а
«через год» от 29 февраля бывает раз в четыре года. Такие вещи надо
считать в одном месте и проверять тестами, а не в середине обработчика
доставки.

ЧЕГО ЗДЕСЬ НЕТ. Ни RRULE, ни «каждый второй вторник», ни «по будням» —
четыре периода покрывают всё, ради чего это просили, а полноценный
календарный язык стоит дороже, чем даёт. Когда понадобится пятый —
добавить строку в _ADVANCE.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

# Машинные имена. Строками не разбрасываемся: опечатка в правиле — это
# напоминание, которое молча перестаёт повторяться.
DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
YEARLY = "yearly"

RULES = (DAILY, WEEKLY, MONTHLY, YEARLY)

HUMAN: dict[str, str] = {
    DAILY: "каждый день",
    WEEKLY: "каждую неделю",
    MONTHLY: "каждый месяц",
    YEARLY: "каждый год",
}


def _add_months(moment: datetime, months: int) -> datetime:
    """Через N месяцев, с переносом на последний день короткого месяца.

    31 января + месяц = 28 (или 29) февраля, а не ошибка и не 3 марта.
    Человек, поставивший напоминание на 31-е, имел в виду «в конце
    месяца», и уехать за его границу было бы неверно.
    """
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


_ADVANCE = {
    DAILY: lambda m: m + timedelta(days=1),
    WEEKLY: lambda m: m + timedelta(weeks=1),
    MONTHLY: lambda m: _add_months(m, 1),
    YEARLY: lambda m: _add_months(m, 12),
}


def next_occurrence(previous: datetime, rule: str, *, now: datetime | None = None) -> datetime | None:
    """Когда повторить. None — правило неизвестно, повторять нечего.

    Если предыдущий срок давно прошёл (сервер лежал, человек был в
    отпуске), шагаем вперёд, пока не окажемся в будущем, — а не шлём
    пачку пропущенных. Напоминание «полить цветы» за две недели простоя
    не нужно четырнадцать раз, нужно один, на сегодня.
    """
    advance = _ADVANCE.get(rule)
    if advance is None:
        return None

    now = now or datetime.now(previous.tzinfo)
    moment = advance(previous)
    # Потолок на случай совсем далёкого прошлого: шаг в день на десять
    # лет — это 3650 итераций, считать их незачем.
    for _ in range(4000):
        if moment > now:
            return moment
        moment = advance(moment)
    return None
