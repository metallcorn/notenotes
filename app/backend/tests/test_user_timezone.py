from datetime import datetime, timezone

from app.user_timezone import DEFAULT_TZ, assume_default_timezone, resolve_timezone, today_in_default_timezone


# --- Реальная жалоба: письмо про встречу "17:30" в Познани показывалось в
# заметке как 19:30 — наивное время трактовалось как UTC вместо местного.

def test_assume_default_timezone_naive_summer_is_cest_utc_plus_2():
    naive = datetime(2026, 9, 9, 17, 30)
    result = assume_default_timezone(naive)
    assert result == datetime(2026, 9, 9, 15, 30, tzinfo=timezone.utc)


def test_assume_default_timezone_naive_winter_is_cet_utc_plus_1():
    # Зимой (без перехода на летнее время) сдвиг другой — ZoneInfo сам
    # учитывает переход, не фиксированный час, как было бы при
    # replace(tzinfo=timezone(timedelta(hours=2))).
    naive = datetime(2026, 1, 15, 17, 30)
    result = assume_default_timezone(naive)
    assert result == datetime(2026, 1, 15, 16, 30, tzinfo=timezone.utc)


def test_assume_default_timezone_already_aware_untouched():
    aware = datetime(2026, 9, 9, 17, 30, tzinfo=timezone.utc)
    assert assume_default_timezone(aware) == aware


def test_today_in_default_timezone_format():
    today = today_in_default_timezone()
    # Просто формат — сама дата зависит от текущего времени; полноценно её
    # не протестировать без монки-патча datetime.now, не стоит того здесь.
    datetime.strptime(today, "%Y-%m-%d")


def test_default_tz_is_warsaw():
    assert str(DEFAULT_TZ) == "Europe/Warsaw"


def test_resolve_timezone_valid_name():
    assert str(resolve_timezone("Asia/Dubai")) == "Asia/Dubai"


def test_resolve_timezone_invalid_name_falls_back_to_default():
    assert resolve_timezone("Mars/Olympus_Mons") is DEFAULT_TZ


def test_resolve_timezone_none_falls_back_to_default():
    assert resolve_timezone(None) is DEFAULT_TZ


def test_assume_default_timezone_uses_explicit_tz_name():
    # Дубай — UTC+4 круглый год, проще проверять, чем Варшаву с её
    # летним/зимним переходом.
    naive = datetime(2026, 9, 9, 17, 30)
    result = assume_default_timezone(naive, "Asia/Dubai")
    assert result == datetime(2026, 9, 9, 13, 30, tzinfo=timezone.utc)
