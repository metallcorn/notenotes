from datetime import datetime, timezone

from app.user_timezone import DEFAULT_TZ, assume_default_timezone, now_in_default_timezone, resolve_timezone


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


def test_now_in_default_timezone_includes_time_not_just_date():
    # Реальный найденный случай: в промпт клалась только дата, без часов —
    # и модель на вопрос "который час?" уверенно выдумывала время. Формат
    # обязан содержать ЧАСЫ И МИНУТЫ, не только календарную дату.
    now = now_in_default_timezone()
    parsed = datetime.strptime(now, "%Y-%m-%d %H:%M")
    assert parsed.year >= 2024


def test_now_in_default_timezone_respects_explicit_timezone():
    # Дубай (UTC+4) и UTC в один момент времени почти всегда дают разный
    # час — проверяем, что пояс реально применяется, а не игнорируется.
    dubai = datetime.strptime(now_in_default_timezone("Asia/Dubai"), "%Y-%m-%d %H:%M")
    utc = datetime.strptime(now_in_default_timezone("UTC"), "%Y-%m-%d %H:%M")
    diff_minutes = abs((dubai - utc).total_seconds()) / 60
    # 4 часа ± минута на время между двумя вызовами.
    assert 239 <= diff_minutes <= 241


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
