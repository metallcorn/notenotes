"""Эхо create_reminder/list_reminders — в местном времени пользователя.

Реальный баг, пойманный замером 2026-09-05 (сценарий воскресного ужина,
проваливался во ВСЕХ замерах подряд): тул отдавал trigger_at в UTC, модель
читала своё же значение на два часа меньше запрошенного, решала что
ошиблась, и создавала ВТОРОЕ напоминание на два часа раньше. Дубль на
09:30 вместо верного 13:30.

Чинится форматом ответа, а не промптом: эхо обязано подтверждать ввод.
"""

from datetime import datetime, timezone

from app.tools.reminders import _echo_times


def test_echo_returns_local_time_matching_what_model_asked():
    # Модель просила 13:30 по Варшаве — в базе это 11:30 UTC.
    stored_utc = datetime(2026, 9, 6, 11, 30, tzinfo=timezone.utc)
    echo = _echo_times(stored_utc, "Europe/Warsaw")

    # Главное: в trigger_at модель видит ровно то, что просила.
    assert echo["trigger_at"].startswith("2026-09-06T13:30")
    # UTC остаётся доступен отдельным полем — для хранения он и есть правда.
    assert echo["trigger_at_utc"].startswith("2026-09-06T11:30")


def test_echo_follows_the_users_own_timezone():
    stored_utc = datetime(2026, 9, 6, 11, 30, tzinfo=timezone.utc)
    assert _echo_times(stored_utc, "Europe/Moscow")["trigger_at"].startswith("2026-09-06T14:30")
    assert _echo_times(stored_utc, "UTC")["trigger_at"].startswith("2026-09-06T11:30")


def test_echo_falls_back_to_default_timezone():
    # Без пояса от браузера берётся домашний по умолчанию (Europe/Warsaw).
    stored_utc = datetime(2026, 9, 6, 11, 30, tzinfo=timezone.utc)
    assert _echo_times(stored_utc, None)["trigger_at"].startswith("2026-09-06T13:30")
