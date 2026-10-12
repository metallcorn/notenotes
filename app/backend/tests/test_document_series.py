"""Серии документов: «ZUS DRA 06 → 07 → 08» одной линией.

Запрос владельца: «всё раскидано… или ещё какие-то умные вещи давай
помыслим». Разбор его базы 12.10 показал, что документы приходят не
штуками, а серией: бухгалтер присылает один набор каждый месяц. Пока они
лежат отдельными файлами в разных папках, не видно ни линии, ни ПРОПУСКА.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.document_series import (
    _MAX_MEANINGFUL_LAG_DAYS,
    Period,
    detect_series,
    parse_period,
    series_title,
)

TODAY = date(2026, 10, 12)


def _f(upload_id: str, filename: str, received: date, space: str = "Почта"):
    return (upload_id, filename, space, received)


class TestРазборИмени:
    @pytest.mark.parametrize("filename,year,month,title", [
        ("ZUS DRA 07-2026.pdf", 2026, 7, "ZUS DRA"),
        ("UPO ZUS DRA 08-2026.pdf", 2026, 8, "UPO ZUS DRA"),
        ("EP 07-2026 NARASTAJĄCO.pdf", 2026, 7, "EP NARASTAJĄCO"),
        # Бухгалтер присылает часть файлов с польскими месяцами.
        ("Zal_na_podatek_PIT_(ryczałt)_Lipiec_2026_X.pdf", 2026, 7, "Zal na podatek PIT (ryczałt) X"),
        ("Podstawa_składki_zdrowotnej_Sierpień_2026_X.pdf", 2026, 8, "Podstawa składki zdrowotnej X"),
    ])
    def test_месячные_настоящие_имена_из_базы(self, filename, year, month, title):
        key, period = parse_period(filename)

        assert (period.year, period.month) == (year, month)
        assert series_title(key) == title

    def test_годовая(self):
        key, period = parse_period("upo_2024.pdf")

        assert (period.year, period.month) == (2024, None)
        assert period.monthly is False

    @pytest.mark.parametrize("filename", [
        # Полная дата — это момент сканирования или дата счёта, а не
        # период документа. Поймано на живых именах.
        "CamScanner 29.05.2025 07.31.pdf",
        "faktura-21-08-2026.pdf",
        "bureau29. квартира Poznań. кп. 11.08.2026.pdf",
        # Цифры без разделителей — не дата и не период.
        "oświadczenie_Anna Nowak28092026.pdf",
        "j.kowalski_karta_pobytu.pdf",
        "Broszura.pdf",
    ])
    def test_не_период(self, filename):
        assert parse_period(filename) is None

    def test_разные_документы_не_склеиваются(self):
        """«EP 07-2026» и «EP 07-2026 NARASTAJĄCO» — два разных документа
        бухгалтера, и общий ключ был бы ошибкой."""
        first, _ = parse_period("EP 07-2026.pdf")
        second, _ = parse_period("EP 07-2026 NARASTAJĄCO.pdf")

        assert first != second


class TestПериод:
    def test_следующий_месяц_через_декабрь(self):
        assert Period(2026, 12).next() == Period(2027, 1)

    def test_конец_месяца(self):
        assert Period(2026, 2).ends_on() == date(2026, 2, 28)
        assert Period(2026, 7).ends_on() == date(2026, 7, 31)

    def test_конец_года(self):
        assert Period(2026).ends_on() == date(2026, 12, 31)
        assert Period(2026).next() == Period(2027)


class TestСборкаСерии:
    def test_три_выпуска_одной_линией(self):
        series, standalone = detect_series([
            _f("a", "ZUS DRA 06-2026.pdf", date(2026, 7, 20)),
            _f("b", "ZUS DRA 07-2026.pdf", date(2026, 8, 19)),
            _f("c", "ZUS DRA 08-2026.pdf", date(2026, 9, 2)),
        ], today=TODAY)

        assert len(series) == 1 and standalone == []
        assert [i.period.label() for i in series[0].instalments] == ["июнь 2026", "июль 2026", "август 2026"]

    def test_один_выпуск_не_серия(self):
        """Файл с датой в имени — просто файл с датой в имени."""
        series, standalone = detect_series([_f("a", "ZUS DRA 06-2026.pdf", date(2026, 7, 20))], today=TODAY)

        assert series == [] and standalone == ["a"]

    def test_пропуск_внутри_диапазона_виден(self):
        series, _ = detect_series([
            _f("a", "EP 06-2026.pdf", date(2026, 7, 10)),
            _f("c", "EP 08-2026.pdf", date(2026, 9, 2)),
        ], today=TODAY)

        assert [p.label() for p in series[0].gaps] == ["июль 2026"]

    def test_до_первого_выпуска_не_считается_пропуском(self):
        """Что было до того, как человек начал складывать документы сюда,
        нас не касается."""
        series, _ = detect_series([
            _f("a", "EP 07-2026.pdf", date(2026, 8, 19)),
            _f("b", "EP 08-2026.pdf", date(2026, 9, 2)),
        ], today=TODAY)

        assert series[0].gaps == []

    def test_копии_одного_периода_не_плодят_выпуски(self):
        """Дедуп ловит это на приёме, но в истории копии остались."""
        series, _ = detect_series([
            _f("a", "ZUS DRA 07-2026.pdf", date(2026, 8, 19)),
            _f("b", "ZUS DRA 07-2026.pdf", date(2026, 8, 25), space="Личное"),
            _f("c", "ZUS DRA 08-2026.pdf", date(2026, 9, 2)),
        ], today=TODAY)

        assert len(series[0].instalments) == 2
        # Берём самую раннюю копию — она и есть «когда пришло».
        assert series[0].instalments[0].received_on == date(2026, 8, 19)


class TestРитмИОжидание:
    def test_ожидается_когда_срок_ещё_не_вышел(self):
        """Живые числа: июльский пакет пришёл 19.08 (через 19 дней после
        конца июля), августовский 02.09 (через 2). Медиана 10 дней, значит
        сентябрьский ждём к 10.10 — на 12.10 это «ожидается», не «пропал»."""
        series, _ = detect_series([
            _f("a", "ZUS DRA 07-2026.pdf", date(2026, 8, 19)),
            _f("b", "ZUS DRA 08-2026.pdf", date(2026, 9, 2)),
        ], today=TODAY)

        assert series[0].expected_next.label() == "сентябрь 2026"
        assert series[0].status == "ожидается"

    def test_задерживается_после_запаса(self):
        series, _ = detect_series([
            _f("a", "ZUS DRA 07-2026.pdf", date(2026, 8, 19)),
            _f("b", "ZUS DRA 08-2026.pdf", date(2026, 9, 2)),
        ], today=date(2026, 11, 1))

        assert series[0].status == "задерживается"

    def test_пока_период_не_кончился_всё_в_порядке(self):
        series, _ = detect_series([
            _f("a", "ZUS DRA 07-2026.pdf", date(2026, 8, 19)),
            _f("b", "ZUS DRA 08-2026.pdf", date(2026, 9, 2)),
        ], today=date(2026, 9, 20))

        assert series[0].status == "ок"

    def test_годовым_сериям_дату_не_обещаем(self):
        """На живой базе файлы годовых серий залиты задним числом, и
        «срок прихода» выходил в 400+ дней: предсказание читалось как
        «2027 ожидается к 2028-05-01». Молчать честнее, чем назвать дату,
        которой сами не верим."""
        series, _ = detect_series([
            _f("a", "upo_2024.pdf", date(2026, 9, 25)),
            _f("b", "upo_2025.pdf", date(2026, 9, 25)),
        ], today=TODAY)

        assert series[0].expected_next.label() == "2026"
        assert series[0].expected_by is None
        assert series[0].status == "ок"

    def test_слишком_большая_задержка_не_считается_ритмом(self):
        series, _ = detect_series([
            _f("a", "ZUS DRA 01-2026.pdf", date(2026, 9, 1)),
            _f("b", "ZUS DRA 02-2026.pdf", date(2026, 9, 1)),
        ], today=TODAY)

        assert series[0].expected_by is None, f"задержка больше {_MAX_MEANINGFUL_LAG_DAYS} дней — не ритм"


class TestПорядок:
    def test_проблемные_первыми(self):
        series, _ = detect_series([
            _f("a", "upo_2024.pdf", date(2026, 9, 25)),
            _f("b", "upo_2025.pdf", date(2026, 9, 25)),
            _f("c", "ZUS DRA 07-2026.pdf", date(2026, 8, 19)),
            _f("d", "ZUS DRA 08-2026.pdf", date(2026, 9, 2)),
        ], today=date(2026, 11, 1))

        assert series[0].status == "задерживается"
        assert series[0].title == "ZUS DRA"
