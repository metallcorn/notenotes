"""«Сделано» и «отложить» для напоминания — из веба, из Telegram, из сводки.

Жалоба владельца 18.10: одно из напоминаний сработало в
августе, его открыли — и оно два месяца висело в «Активности», ни разу
больше о себе не напомнив. В Telegram у сообщения была одна кнопка —
«Открыть»: ни закрыть, ни отложить оттуда было нельзя, а в утреннюю
сводку попадает только то, что ещё впереди сегодня.

ОТЛОЖИТЬ — значит сработать заново, а не просто сдвинуть дату. Поэтому
вместе с trigger_at сбрасываются dispatched_at (иначе диспетчер не
пришлёт его второй раз) и read_at (иначе колокольчик не подсветит).

ПРЕСЕТЫ, а не произвольное время. Кнопке в Telegram время не ввести, а
«завтра утром» должно значить одно и то же в боте и в вебе — поэтому оно
считается здесь, в поясе человека, а не в браузере.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models import Notification, User

# Порядок — порядок кнопок в вебе.
PRESETS: dict[str, str] = {
    "1h": "через час",
    "3h": "через 3 часа",
    "tomorrow": "завтра утром",
    "week": "через неделю",
}

# Типы, у которых есть смысл «сделано»: остальное (приглашение в спейс,
# сводка) — просто сообщение.
ACTIONABLE_TYPES = {"reminder", "document_expiry", "ticket_event"}

# Префикс callback_data кнопок под самим напоминанием. «dg:» — сводка,
# «sr:» — варианты ответа ассистента; пересекаться нельзя.
CALLBACK_PREFIX = "nt:"

_DEFAULT_MORNING = "09:00"


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def snooze_until(preset: str, user: User, now: datetime | None = None) -> datetime:
    """Момент, до которого откладываем. ValueError — неизвестный пресет."""
    if preset not in PRESETS:
        raise ValueError(preset)
    now = now or datetime.now(timezone.utc)
    if preset == "1h":
        return now + timedelta(hours=1)
    if preset == "3h":
        return now + timedelta(hours=3)
    # «Утро» — время сводки человека: напоминание придёт тогда же, когда он
    # и так смотрит в Telegram. Сводка выключена — 09:00.
    try:
        hour, minute = (int(p) for p in (user.digest_time or _DEFAULT_MORNING).split(":"))
    except ValueError:
        hour, minute = 9, 0
    days = 1 if preset == "tomorrow" else 7
    local = now.astimezone(_tz(user.timezone))
    target = (local + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target.astimezone(timezone.utc)


def snooze(db, notification: Notification, until: datetime) -> None:
    """Перенести напоминание так, чтобы оно сработало заново в until."""
    # Повторяющееся, ещё не отправленное: правило живёт на нём самом
    # (recurrence.py), и следующая копия считалась бы от НОВОГО времени —
    # «каждый понедельник 9:00», отложенный на час, стал бы «каждый
    # понедельник 10:00». Заводим следующую копию от исходного времени
    # сейчас, а эту переносим уже одноразовой.
    if notification.repeat_rule and notification.dispatched_at is None:
        from app.notification_dispatch import _schedule_next

        _schedule_next(notification, db)
    notification.trigger_at = until
    notification.dispatched_at = None
    notification.read_at = None
    notification.resolved_at = None


def resolve(notification: Notification) -> None:
    if notification.resolved_at is None:
        notification.resolved_at = datetime.now(timezone.utc)


def telegram_buttons(notification: Notification) -> list[dict]:
    """Ряд кнопок под сообщением напоминания. Пусто — если закрывать нечего."""
    if notification.type not in ACTIONABLE_TYPES:
        return []
    nid = notification.id
    return [
        {"text": "✓ Сделано", "callback_data": f"{CALLBACK_PREFIX}d:{nid}"},
        {"text": "⏰ +1 ч", "callback_data": f"{CALLBACK_PREFIX}s:1h:{nid}"},
        {"text": "⏰ Завтра", "callback_data": f"{CALLBACK_PREFIX}s:tomorrow:{nid}"},
    ]


def _format_local(at: datetime, user: User) -> str:
    return at.astimezone(_tz(user.timezone)).strftime("%d.%m %H:%M")


async def handle_callback(db, user_id: uuid.UUID, data: str) -> str | None:
    """Нажатие кнопки под напоминанием. Строка для подписи под сообщением
    или None, если данные не наши.

    user_id — владелец чата: чужое напоминание кнопкой не закрыть, даже
    угадав id (то же правило, что в daily_digest.handle_callback).
    """
    if not data.startswith(CALLBACK_PREFIX):
        return None
    parts = data[len(CALLBACK_PREFIX):].split(":")
    try:
        notification_id = uuid.UUID(parts[-1])
    except ValueError:
        return None
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user_id:
        return "Напоминание не найдено"

    if parts[0] == "d" and len(parts) == 2:
        resolve(n)
        await db.commit()
        return "✓ Сделано"

    if parts[0] == "s" and len(parts) == 3 and parts[1] in PRESETS:
        user = await db.get(User, user_id)
        until = snooze_until(parts[1], user)
        snooze(db, n, until)
        await db.commit()
        return f"⏰ Отложено до {_format_local(until, user)}"

    return None
