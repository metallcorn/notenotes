from app.autotag import _parse_events


# Реальная жалоба: письмо про встречу "17:30" в Познани (Fwd: Przedłużenie
# umowy najmu) показывалось в "Активности" как 19:30 — LLM отдал наивное
# время без пояса, оно трактовалось как UTC вместо местного (Польша летом
# на 2 часа впереди UTC).

def test_parse_events_naive_time_treated_as_warsaw_not_utc():
    events = _parse_events([{"title": "Встреча по аренде", "at": "2026-09-09T17:30:00"}])
    assert len(events) == 1
    assert events[0]["at"] == "2026-09-09T15:30:00+00:00"


def test_parse_events_naive_time_uses_passed_home_timezone():
    # Домашний пояс автора заметки (tz_name), не хардкод Варшавы — Дубай
    # (UTC+4 круглый год) проще проверять, чем Варшаву с летним/зимним
    # переходом.
    events = _parse_events([{"title": "Встреча", "at": "2026-09-09T17:30:00"}], "Asia/Dubai")
    assert events[0]["at"] == "2026-09-09T13:30:00+00:00"


def test_parse_events_already_aware_time_untouched():
    events = _parse_events([{"title": "Встреча", "at": "2026-09-09T15:30:00+00:00"}])
    assert events[0]["at"] == "2026-09-09T15:30:00+00:00"


def test_parse_events_skips_missing_title_or_at():
    assert _parse_events([{"title": "", "at": "2026-09-09T17:30:00"}]) == []
    assert _parse_events([{"title": "Встреча"}]) == []


def test_parse_events_skips_invalid_date():
    assert _parse_events([{"title": "Встреча", "at": "не дата"}]) == []


def test_parse_events_not_a_list_returns_empty():
    assert _parse_events("не список") == []
    assert _parse_events(None) == []


# Пересланное из Telegram «завтра» написано не сегодня: вчерашнее «у нас
# завтра консультация» ложилось на послезавтра. Дата оригинала —
# properties.source.written_at, распознавателю она уходит отдельной
# инструкцией в промпте.

def test_source_written_at_reads_forward_date():
    from datetime import datetime, timezone

    from app.autotag import source_written_at

    props = {"source": {"kind": "telegram_forward", "written_at": "2026-03-09T19:15:00+00:00"}}
    assert source_written_at(props) == datetime(2026, 3, 9, 19, 15, tzinfo=timezone.utc)
    assert source_written_at({"source": {"written_at": "2026-03-09T19:15:00"}}).tzinfo is timezone.utc
    assert source_written_at({}) is None and source_written_at(None) is None
    assert source_written_at({"source": {"written_at": "вчера"}}) is None


def test_prompt_mentions_written_date_only_when_given():
    from app.autotag import _build_prompt

    plain = _build_prompt([], "2026-03-10, Tuesday")
    assert "текст написан" not in plain
    dated = _build_prompt([], "2026-03-10, Tuesday", "2026-03-09, Monday")
    assert "написан 2026-03-09, Monday" in dated and "от дня написания" in dated
