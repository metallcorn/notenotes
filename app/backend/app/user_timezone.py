from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones

# Крайний фолбэк, когда ни домашний (User.timezone), ни живой (заголовок
# X-Client-Timezone из браузера) пояс не известны — например, только что
# созданный пользователь до первого захода в Настройки, или Telegram-линк
# без привязанного веб-аккаунта.
# Реальный найденный баг: дату/время без явного пояса — как их извлекает
# LLM из текста письма/билета, так и то, что модель сама формирует по
# просьбе "напомни в 9 утра" — раньше везде трактовали как UTC. Для
# пользователя в Польше (CEST, UTC+2 летом) это систематически сдвигало
# показанное время на 2 часа: письмо про встречу "17:30" в Познани
# превращалось в заметке в 19:30 на экране пользователя. ZoneInfo сам
# учитывает переход на летнее/зимнее время (CET/CEST) — не фиксированный
# сдвиг в часах.
DEFAULT_TZ_NAME = "Europe/Warsaw"
DEFAULT_TZ = ZoneInfo(DEFAULT_TZ_NAME)

VALID_TIMEZONE_NAMES = available_timezones()


def resolve_timezone(tz_name: str | None) -> ZoneInfo:
    """tz_name — обычно либо домашний пояс автора заметки (User.timezone,
    для фоновых воркеров без живого запроса), либо живой пояс из браузера
    (заголовок X-Client-Timezone, для прямых действий пользователя). Пустое
    или некорректное имя — фолбэк на DEFAULT_TZ, не исключение: часовой
    пояс никогда не должен ронять обработку письма/тикета/напоминания."""
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    return DEFAULT_TZ


def assume_default_timezone(dt: datetime, tz_name: str | None = None) -> datetime:
    """Дата/время БЕЗ явного часового пояса — трактуем как местное время в
    tz_name (или DEFAULT_TZ, если не передан/некорректен), не UTC, и
    переводим в UTC для хранения. Уже tz-aware дату не трогаем — явный
    пояс всегда достовернее угадывания."""
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=resolve_timezone(tz_name)).astimezone(timezone.utc)


def today_in_default_timezone(tz_name: str | None = None) -> str:
    """Для промпта ассистента (Сегодняшняя дата: ...) — календарная дата по
    местному времени пользователя (tz_name, обычно живой пояс из браузера),
    не по UTC. Имеет значение у границы полуночи: в 00:30 по Варшаве уже
    наступил новый день локально, а по UTC (Варшава летом на 2 часа
    впереди) это ещё 22:30 предыдущего — "завтра"/"сегодня" в относительных
    формулировках резолвились бы не в тот день."""
    return datetime.now(resolve_timezone(tz_name)).strftime("%Y-%m-%d")
