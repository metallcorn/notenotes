from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app import telegram_bot
from app.db import async_session
from app.models import Notification, TelegramLink

logger = logging.getLogger(__name__)

# Раньше уведомление "проявлялось" только фильтром trigger_at<=now() в
# GET /api/notifications — то есть только если пользователь в этот момент
# сам открыл приложение. Для "напомни за 2 часа до вылета" это не
# работает: приложение обычно закрыто в момент срабатывания. Диспетчер —
# отдельный воркер (тот же принцип, что run_periodic_sweep в cleanup.py),
# который реально толкает уведомление наружу, когда наступает время.
#
# 20с, не 60с (интервал опроса фронтенда, useNotifications) — сам
# диспетчер не привязан к открытой вкладке, и пустая выборка почти
# ничего не стоит, дешевле проверять чаще ради меньшей задержки доставки.
_DISPATCH_INTERVAL_SECONDS = 20


async def _dispatch_one(notification: Notification, db) -> None:
    text = notification.title
    if notification.body:
        text = f"{notification.title}\n{notification.body}"

    link = (
        await db.execute(select(TelegramLink.chat_id).where(TelegramLink.user_id == notification.user_id))
    ).scalar_one_or_none()
    if link is not None:
        await telegram_bot.send_message(link, text)

    notification.dispatched_at = datetime.now(timezone.utc)


async def _dispatch_due() -> None:
    async with async_session() as db:
        result = await db.execute(
            select(Notification).where(
                Notification.dispatched_at.is_(None),
                (Notification.trigger_at.is_(None)) | (Notification.trigger_at <= datetime.now(timezone.utc)),
            )
        )
        due = result.scalars().all()
        for notification in due:
            try:
                await _dispatch_one(notification, db)
            except Exception:
                logger.exception("Ошибка доставки уведомления %s", notification.id)
        if due:
            await db.commit()


async def run_dispatch_worker() -> None:
    while True:
        try:
            await _dispatch_due()
        except Exception:
            logger.exception("Ошибка при обходе неотправленных уведомлений")
        await asyncio.sleep(_DISPATCH_INTERVAL_SECONDS)
