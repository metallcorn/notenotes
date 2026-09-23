"""Утренняя сводка: «что у меня сегодня» — в Telegram с кнопками и в push.

Запрос владельца: в установленное время (по умолчанию 9 утра) получать
напоминания и события на сегодня — включая те, что распознаны в письмах
и билетах автоматически, — и прямо из Telegram отмечать сделанное или
неактуальное.

ТРИ РЕШЕНИЯ.

1. Содержимое собирает тот же код, что отвечает ассистенту на «что у
   меня сегодня» (tools/agenda.collect_agenda). Иначе утром человек
   получал бы одно, а на вопрос — другое.

2. Пустую сводку не шлём. «На сегодня ничего» каждое утро — это
   уведомление, которое учат смахивать не глядя; а потом смахнут и то,
   в котором что-то было.

3. Кнопки — только в Telegram, и только два действия: «сделано» для
   напоминания (resolve) и «не актуально» для распознанного события
   (dismiss, как в ActivityView). В push кнопок нет — там сводка просто
   текстом, а действия в приложении.

Воркер проверяет раз в минуту, у кого локальное время совпало с
digest_time и сводка за сегодня ещё не уходила (digest_sent_on). Отметка
в БД, а не в памяти: после перезапуска в 09:00:30 иначе ушло бы второй
раз.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import async_session
from app.models import Item, Notification, PushSubscription, TelegramLink, User
from app.tools.agenda import collect_agenda

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60

# Префикс callback_data кнопок сводки. «sr:» занят вариантами ответа
# ассистента (telegram_bot.py), пересекаться нельзя.
CALLBACK_PREFIX = "dg:"


def event_key(at: str, title: str) -> str:
    """Короткий ключ распознанного события для callback_data.

    Telegram даёт 64 байта на callback_data. uuid заметки — 36, префикс и
    разделители — ещё 6, на само событие остаётся мало. Индекс в массиве
    брать нельзя: события переупорядочиваются при переиндексации заметки,
    и кнопка «не актуально» закрыла бы соседнее. Хэш от (дата, название)
    — то же, чем событие опознаёт dismiss в routers/items.py.
    """
    return hashlib.sha256(f"{at}|{title}".encode()).hexdigest()[:8]


def _local_now(tz_name: str | None) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name or "UTC"))
    except Exception:
        return datetime.now(ZoneInfo("UTC"))


def _entry_time(e: dict) -> datetime | None:
    try:
        at = datetime.fromisoformat(e["at"])
    except (ValueError, KeyError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _format(agenda: dict, tz_name: str | None, *, now: datetime | None = None) -> tuple[str, list[list[dict]]]:
    """Текст сводки и клавиатура.

    Сегодняшнее, ЕЩЁ НЕ ПРОШЕДШЕЕ, плюс завтрашнее раннее — то, о чём
    завтрашняя сводка сообщит уже поздно.
    """
    tz = ZoneInfo(tz_name or "UTC")
    now = now or datetime.now(timezone.utc)
    today = agenda["today"]
    lines: list[str] = []
    keyboard: list[list[dict]] = []
    for e in agenda["entries"]:
        if not e["at"].startswith(today):
            continue
        at = _entry_time(e)
        # Прошедшее не показываем. Живой случай 23.09: запись на приём в
        # 08:00 попала в сводку, ушедшую в 09:00 — через час после. Для
        # уведомления «сегодня в 08:00» в 09:00 нет никакого смысла, а
        # доверие к сводке оно подрывает сразу.
        if at is not None and at <= now:
            continue
        try:
            when = at.astimezone(tz).strftime("%H:%M") if at else ""
        except Exception:
            when = ""
        if e["kind"] == "напоминание":
            lines.append(f"⏰ {when} {e['title']}".strip())
            keyboard.append([{
                "text": f"✓ Сделано: {e['title'][:30]}",
                "callback_data": f"{CALLBACK_PREFIX}r:{e['reminder_id']}",
            }])
        else:
            src = f" — {e['source_note']}" if e.get("source_note") else ""
            lines.append(f"📌 {when} {e['title']}{src}".strip())
            keyboard.append([{
                "text": f"✗ Не актуально: {e['title'][:26]}",
                "callback_data": f"{CALLBACK_PREFIX}e:{e['item_id']}:{event_key(e['at'], e['title'])}",
            }])
    return "\n".join(lines), keyboard


def _early_tomorrow(agenda: dict, user: User, now: datetime) -> list[str]:
    """Завтрашнее ДО времени сводки — про это завтра узнавать поздно.

    Вторая половина того же случая: сводка в 09:00 физически не может
    вовремя сообщить о приёме в 08:00. Раз она приходит раз в сутки,
    про раннее завтрашнее надо говорить сегодня.
    """
    if not user.digest_time:
        return []
    tz = ZoneInfo(user.timezone or "UTC")
    tomorrow = (now.astimezone(tz).date() + timedelta(days=1)).isoformat()
    lines: list[str] = []
    for e in agenda["entries"]:
        if not e["at"].startswith(tomorrow):
            continue
        at = _entry_time(e)
        if at is None:
            continue
        local = at.astimezone(tz)
        if local.strftime("%H:%M") >= user.digest_time:
            continue
        mark = "⏰" if e["kind"] == "напоминание" else "📌"
        lines.append(f"{mark} {local:%H:%M} {e['title']}")
    return lines


async def build_digest(db, user: User) -> tuple[str, list[list[dict]]] | None:
    """Готовая сводка или None, если сказать нечего."""
    now = datetime.now(timezone.utc)
    # days=2: нужен и завтрашний день — ради раннего завтрашнего.
    agenda = await collect_agenda(db, user.id, days=2, tz_name=user.timezone)
    text, keyboard = _format(agenda, user.timezone, now=now)

    early = _early_tomorrow(agenda, user, now)
    parts = []
    if text:
        parts.append(f"Сегодня, {agenda['today']}:\n\n{text}")
    if early:
        # Кнопок к завтрашнему намеренно нет: закрывать то, что ещё не
        # наступило, незачем, а лишние кнопки делают сводку нечитаемой.
        parts.append("Завтра рано утром (сводка придёт позже):\n\n" + "\n".join(early))
    if not parts:
        return None
    return "\n\n".join(parts), keyboard


async def _send_for(db, user: User) -> bool:
    """Отправить сводку одному человеку. True — что-то ушло."""
    from app import telegram_bot

    built = await build_digest(db, user)
    if built is None:
        return False
    text, keyboard = built

    sent = False
    link = (await db.execute(select(TelegramLink).where(TelegramLink.user_id == user.id))).scalar_one_or_none()
    if link is not None:
        await telegram_bot.send_message(link.chat_id, text, reply_markup={"inline_keyboard": keyboard})
        sent = True

    # Push и колокольчик — через обычное уведомление, без кнопок: его
    # доставит notification_dispatch. Если Telegram есть, туда уже ушло
    # с кнопками, и дублировать в Telegram не надо — поэтому type другой,
    # и dispatch его в Telegram не отправит (см. там).
    has_push = (
        await db.execute(select(PushSubscription.id).where(PushSubscription.user_id == user.id).limit(1))
    ).scalar_one_or_none()
    if has_push is not None and link is None:
        db.add(Notification(user_id=user.id, type="digest", title="Что сегодня", body=text))
        sent = True
    return sent


async def _tick() -> None:
    async with async_session() as db:
        users = (
            await db.execute(select(User).where(User.digest_time.isnot(None), User.digest_time != ""))
        ).scalars().all()
        for user in users:
            now = _local_now(user.timezone)
            today = now.date().isoformat()
            if user.digest_sent_on == today or now.strftime("%H:%M") != user.digest_time:
                continue
            # Отметку ставим ДО отправки: упавшая отправка лучше, чем
            # отправка дважды. Повторить руками можно, отозвать — нет.
            user.digest_sent_on = today
            await db.commit()
            try:
                if await _send_for(db, user):
                    await db.commit()
                    logger.info("Утренняя сводка отправлена пользователю %s", user.id)
            except Exception:
                logger.exception("Не удалось отправить сводку пользователю %s", user.id)


async def run_worker() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("Ошибка воркера утренней сводки")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)


# --- кнопки ---------------------------------------------------------------


async def handle_callback(db, user_id: uuid.UUID, data: str) -> str | None:
    """Нажатие кнопки в сводке. Возвращает текст подтверждения или None,
    если данные не наши.

    user_id — владелец Telegram-чата, из которого пришло нажатие. Всё, что
    здесь меняется, сверяется с ним: чужое напоминание или чужую заметку
    кнопкой закрыть нельзя, даже если угадать id.
    """
    if not data.startswith(CALLBACK_PREFIX):
        return None
    payload = data[len(CALLBACK_PREFIX):]

    if payload.startswith("r:"):
        try:
            reminder_id = uuid.UUID(payload[2:])
        except ValueError:
            return None
        n = await db.get(Notification, reminder_id)
        if n is None or n.user_id != user_id:
            return "Напоминание не найдено"
        if n.resolved_at is None:
            from datetime import timezone

            n.resolved_at = datetime.now(timezone.utc)
            await db.commit()
        return f"Сделано: {n.title}"

    if payload.startswith("e:"):
        try:
            item_part, key = payload[2:].rsplit(":", 1)
            item_id = uuid.UUID(item_part)
        except ValueError:
            return None
        item = await db.get(Item, item_id)
        if item is None or item.deleted_at is not None:
            return "Заметка не найдена"
        from app.deps import ensure_space_access

        try:
            await ensure_space_access(db, item.space_id, user_id)
        except Exception:
            return "Заметка не найдена"
        events = item.properties.get("detected_events") or []
        remaining = [e for e in events if event_key(e.get("at", ""), e.get("title", "")) != key]
        if len(remaining) == len(events):
            return "Событие уже убрано"
        title = next(e["title"] for e in events if event_key(e.get("at", ""), e.get("title", "")) == key)
        item.properties = (
            {**item.properties, "detected_events": remaining}
            if remaining
            else {k: v for k, v in item.properties.items() if k != "detected_events"}
        )
        await db.commit()
        return f"Убрано: {title}"

    return None
