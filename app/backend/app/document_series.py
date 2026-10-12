"""Серии документов: «ZUS DRA 06 → 07 → 08» одной линией.

ЗАЧЕМ. Запрос владельца: «всё раскидано… или ещё какие-то умные вещи
давай помыслим». Разбор его базы 12.10 показал, что документы приходят не
штуками, а СЕРИЯМИ — бухгалтер присылает один и тот же набор каждый
месяц:

    ZUS DRA MM-2026.pdf                       06, 07, 08
    UPO ZUS DRA MM-2026.pdf                   06, 07, 08
    EP MM-2026.pdf                            07, 08
    Zal_na_podatek_PIT_(ryczałt)_<месяц>_2026  Lipiec, Sierpień
    Podstawa_składki_zdrowotnej_<месяц>_2026   Lipiec, Sierpień
    upo_YYYY.pdf                              2024, 2025

Пока они лежат отдельными файлами в разных папках, человек не видит ни
линии, ни ПРОПУСКА. А пропуск — самое ценное: на 12.10 сентябрьского
пакета ZUS нет, хотя июльский пришёл 19.08, а августовский 02.09.

КАК ОПОЗНАЁТСЯ СЕРИЯ. По имени файла с вырезанным обозначением периода:
«ZUS DRA 07-2026.pdf» и «ZUS DRA 08-2026.pdf» дают один и тот же ключ
«ZUS DRA {}.pdf». Серией считаем только то, где периодов НЕ МЕНЬШЕ ДВУХ:
один файл с датой в имени — это просто файл с датой в имени.

ЧЕГО ЗДЕСЬ НЕТ. Разбора содержимого: по тексту внутри PDF можно было бы
опознать и переименованный документ, но это уже догадка, а имя — факт.
И нет никаких «похожих» имён: только точное совпадение после вырезания
периода. Склеить «EP 07-2026» с «EP 07-2026 NARASTAJĄCO» было бы ошибкой
— это два разных документа бухгалтера.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# Польские месяцы — бухгалтер присылает часть файлов с ними вместо цифр.
_POLISH_MONTHS = {
    "styczeń": 1, "stycznia": 1, "luty": 2, "lutego": 2, "marzec": 3, "marca": 3,
    "kwiecień": 4, "kwietnia": 4, "maj": 5, "maja": 5, "czerwiec": 6, "czerwca": 6,
    "lipiec": 7, "lipca": 7, "sierpień": 8, "sierpnia": 8, "wrzesień": 9, "września": 9,
    "październik": 10, "października": 10, "listopad": 11, "listopada": 11,
    "grudzień": 12, "grudnia": 12,
}
_MONTH_NAMES_RU = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь",
    7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}

_PLACEHOLDER = "{}"

# Порядок проверки важен: «08-2026» должно сработать раньше, чем одинокий
# «2026», иначе месячная серия выродится в годовую.
# Отрицательный просмотр назад на «день перед месяцем» — чтобы не принять
# ПОЛНУЮ ДАТУ за период. Поймано на живых именах: «CamScanner 29.05.2025
# 07.31.pdf» разбиралось как «май 2025», хотя 29.05.2025 — это момент
# сканирования, а не период документа. Тот же случай с
# «faktura-21-08-2026»: 21-08-2026 — дата счёта.
#
# Признак надёжный: период в имени документа пишут как «08-2026», а дату —
# как «21-08-2026»; день перед месяцем означает, что это дата.
_MONTH_NUMERIC_RE = re.compile(r"(?<!\d)(?<![\d][-_. ])(0[1-9]|1[0-2])[-_. ](20\d{2})(?!\d)")
_MONTH_NAMED_RE = re.compile(
    r"(?<![a-zа-яё])(" + "|".join(sorted(_POLISH_MONTHS, key=len, reverse=True)) + r")[-_. ]?(20\d{2})(?!\d)",
    re.IGNORECASE,
)
# Тот же запрет, что у месяца: год, стоящий после дня или месяца, — часть
# полной даты, а не период. Без этого «CamScanner 29.05.2025 07.31.pdf»
# и «faktura-21-08-2026.pdf» попадали в годовые серии 2025 и 2026.
_YEAR_RE = re.compile(r"(?<!\d)(?<![\d][-_. ])(20\d{2})(?!\d)")


@dataclass(frozen=True)
class Period:
    """Период выпуска. month=None — годовая серия."""

    year: int
    month: int | None = None

    @property
    def monthly(self) -> bool:
        return self.month is not None

    def label(self) -> str:
        if self.month is None:
            return str(self.year)
        return f"{_MONTH_NAMES_RU[self.month]} {self.year}"

    def sort_key(self) -> tuple[int, int]:
        return (self.year, self.month or 0)

    def next(self) -> "Period":
        if self.month is None:
            return Period(self.year + 1)
        return Period(self.year + 1, 1) if self.month == 12 else Period(self.year, self.month + 1)

    def ends_on(self) -> date:
        """Последний день периода — от него считается ожидаемый приход."""
        if self.month is None:
            return date(self.year, 12, 31)
        return (date(self.year + (self.month == 12), self.month % 12 + 1, 1)) - timedelta(days=1)


def parse_period(filename: str) -> tuple[str, Period] | None:
    """Ключ серии и период из имени файла, или None.

    Ключ — имя с вырезанным периодом, поэтому файлы одной серии дают
    одинаковый ключ, а разные документы (даже похожие) — разные.
    """
    for pattern, named in ((_MONTH_NUMERIC_RE, False), (_MONTH_NAMED_RE, True)):
        found = pattern.search(filename)
        if found is None:
            continue
        month = _POLISH_MONTHS[found.group(1).lower()] if named else int(found.group(1))
        key = filename[: found.start()] + _PLACEHOLDER + filename[found.end():]
        return key, Period(int(found.group(2)), month)

    found = _YEAR_RE.search(filename)
    if found is not None:
        key = filename[: found.start()] + _PLACEHOLDER + filename[found.end():]
        return key, Period(int(found.group(1)))
    return None


def series_title(key: str) -> str:
    """Человеческое название серии из ключа: убираем расширение и
    placeholder, чистим разделители."""
    without_ext = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", key)
    cleaned = without_ext.replace(_PLACEHOLDER, " ").replace("_", " ")
    return " ".join(cleaned.split()).strip(" -–—,") or "Без названия"


@dataclass
class Instalment:
    """Один выпуск серии."""

    period: Period
    upload_id: str
    filename: str
    space_name: str
    received_on: date


@dataclass
class Series:
    key: str
    title: str
    monthly: bool
    instalments: list[Instalment]
    gaps: list[Period]
    expected_next: Period | None
    expected_by: date | None
    status: str  # "ок" | "ожидается" | "задерживается"


# Сколько дней запаса даём сверх обычного срока прихода, прежде чем
# сказать «задерживается». Неделя: бухгалтер присылает не по часам, и
# тревога на следующий же день после обычного срока была бы ложной чаще,
# чем верной.
_GRACE_DAYS = 7

# Минимум выпусков, чтобы говорить о ритме. На двух точках «обычный срок
# прихода» — это просто разница между ними, но уже лучше, чем ничего; на
# одной говорить не о чем вовсе.
_MIN_FOR_RHYTHM = 2

# Выше этого «обычный срок прихода» означает не ритм, а то, что файлы
# заливали задним числом (см. комментарий в build_series). Два месяца:
# месячный пакет, пришедший позже чем через два месяца, уже не месячный.
_MAX_MEANINGFUL_LAG_DAYS = 60


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def _gaps_between(periods: list[Period]) -> list[Period]:
    """Пропущенные периоды между первым и последним выпуском.

    Только ВНУТРИ наблюдаемого диапазона: что было до того, как человек
    начал складывать документы сюда, нас не касается.
    """
    missing: list[Period] = []
    cursor = periods[0]
    while cursor.sort_key() < periods[-1].sort_key():
        cursor = cursor.next()
        if cursor.sort_key() < periods[-1].sort_key() and cursor not in periods:
            missing.append(cursor)
    return missing


def build_series(items: list[Instalment], *, today: date) -> Series | None:
    """Серия из выпусков с одним ключом, или None, если серии нет.

    Серией считаем только то, где периодов не меньше двух: один файл с
    датой в имени — просто файл с датой в имени.
    """
    by_period: dict[Period, Instalment] = {}
    for item in items:
        # Один период мог прийти несколькими копиями (дедуп это теперь
        # ловит на приёме, но в истории копии остались) — берём самую
        # раннюю, она и есть «когда пришло».
        current = by_period.get(item.period)
        if current is None or item.received_on < current.received_on:
            by_period[item.period] = item
    if len(by_period) < 2:
        return None

    ordered = sorted(by_period.values(), key=lambda i: i.period.sort_key())
    periods = [i.period for i in ordered]
    monthly = periods[-1].monthly

    # Обычный срок прихода: сколько дней проходит от конца периода до
    # появления файла. Медиана, а не среднее: один файл, донесённый через
    # три месяца, не должен сдвигать ожидание для всей серии.
    lags = [max((i.received_on - i.period.ends_on()).days, 0) for i in ordered]
    typical_lag = _median(lags) if len(lags) >= _MIN_FOR_RHYTHM else None

    expected_next = periods[-1].next()
    # Предсказываем приход ТОЛЬКО для месячных серий, и только если
    # обычный срок прихода правдоподобен.
    #
    # Проверено на живой базе: у годовых серий («upo_2024», «upo_2025»)
    # файлы залиты задним числом, при разборе документов за прошлые годы,
    # поэтому «срок прихода» выходил в 400+ дней и предсказание читалось
    # как «2027 ожидается к 2028-05-01» — бессмыслица, которой нельзя
    # верить и по которой нельзя действовать. У месячной серии от
    # бухгалтера срок прихода настоящий: июльский пакет пришёл через 19
    # дней после конца июля, августовский — через 2.
    #
    # Молчать честнее, чем назвать дату, которую сами же считаем мусором.
    predictable = monthly and typical_lag is not None and typical_lag <= _MAX_MEANINGFUL_LAG_DAYS
    expected_by = expected_next.ends_on() + timedelta(days=typical_lag) if predictable else None

    if expected_by is None:
        status = "ок"
    elif today > expected_by + timedelta(days=_GRACE_DAYS):
        status = "задерживается"
    elif today > expected_next.ends_on():
        status = "ожидается"
    else:
        status = "ок"

    return Series(
        # key и title ставит detect_series: здесь их просто неоткуда взять,
        # а тащить ключ в каждый выпуск — дублировать его N раз.
        key="",
        title="",
        monthly=monthly,
        instalments=ordered,
        gaps=_gaps_between(periods),
        expected_next=expected_next,
        expected_by=expected_by,
        status=status,
    )


def detect_series(
    files: list[tuple[str, str, str, date]], *, today: date
) -> tuple[list[Series], list[str]]:
    """Серии и upload_id файлов, которые ни в одну серию не попали.

    files — (upload_id, filename, space_name, created_on).
    """
    grouped: dict[str, list[Instalment]] = {}
    standalone: list[str] = []
    for upload_id, filename, space_name, created_on in files:
        parsed = parse_period(filename)
        if parsed is None:
            standalone.append(upload_id)
            continue
        key, period = parsed
        grouped.setdefault(key, []).append(
            Instalment(period=period, upload_id=upload_id, filename=filename,
                       space_name=space_name, received_on=created_on)
        )

    series: list[Series] = []
    for key, items in grouped.items():
        built = build_series(items, today=today)
        if built is None:
            standalone.extend(i.upload_id for i in items)
            continue
        built.key = key
        built.title = series_title(key)
        series.append(built)

    # Сначала проблемные, внутри — по свежести последнего выпуска.
    order = {"задерживается": 0, "ожидается": 1, "ок": 2}
    series.sort(key=lambda s: (order[s.status], -s.instalments[-1].period.sort_key()[0],
                               -s.instalments[-1].period.sort_key()[1]))
    return series, standalone
