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
