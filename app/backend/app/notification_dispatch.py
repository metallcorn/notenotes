from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy import delete, select

from app.telegram_bot import open_button
from app import realtime, reminder_actions, routines, telegram_bot
from app.core.config import get_settings
from app.db import async_session
from app.models import Notification, PushSubscription, TelegramLink
from app.push import send_push
from app.recurrence import next_occurrence

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
    push_title, push_body = notification.title, notification.body
    if notification.type == routines.NOTIFICATION_TYPE:
        # Пинг приёма рутины: свой текст (сколько ждёт, кто передал) и
        # свои кнопки; в Telegram — одно живое сообщение на приём.
        delivered = await routines.deliver(db, notification, link, datetime.now(timezone.utc))
        if delivered is None:
            # Приём закрыли, пока пинг ждал очереди, — слать нечего.
            notification.dispatched_at = datetime.now(timezone.utc)
            return
        push_title, push_body = delivered
    # Утренняя сводка в Telegram уходит отдельно и с кнопками
    # (daily_digest.py); здесь она только для push и колокольчика — иначе
    # человек получал бы её дважды, второй раз без кнопок.
    elif link is not None and notification.type != "digest":
        # Та же кнопка "Открыть", что веб рисует у себя в центре уведомлений
        # (клик — чисто клиентская навигация, AppShell.tsx::openReminder) —
        # тут ссылка холодная (?item=), без подсветки конкретного пункта
        # списка/якоря в заметке, но открывает нужную заметку/список сразу.
        rows: list[list[dict]] = []
        payload = notification.payload or {}
        item_id = payload.get("item_id")
        if item_id:
            base_url = get_settings().public_base_url.rstrip("/")
            url = f"{base_url}/?item={item_id}"
            # find — куда прокрутить внутри заметки (см. document_expiry.py).
            # quote обязателен: дата с точками безопасна, но параметр
            # общий, и однажды сюда попадёт текст с пробелами.
            find = payload.get("find")
            if find:
                url += f"&find={quote(str(find))}"
            rows.append([open_button("Открыть", url)])
        # «Сделано» и «отложить» прямо под сообщением (reminder_actions.py):
        # без них напоминание, открытое и не закрытое, висело месяцами и
        # больше ни разу не напоминало о себе.
        actions = reminder_actions.telegram_buttons(notification)
        if actions:
            rows.append(actions)
        reply_markup = {"inline_keyboard": rows} if rows else None
        await telegram_bot.send_message(link, text, reply_markup=reply_markup)

    subscriptions = (
        await db.execute(select(PushSubscription).where(PushSubscription.user_id == notification.user_id))
    ).scalars().all()
    for subscription in subscriptions:
        alive = await send_push(subscription, push_title, push_body)
        if not alive:
            # 404/410 от push-сервиса — браузер отозвал подписку (снял
            # разрешение, деинсталлировал), больше слать сюда нельзя.
            await db.execute(delete(PushSubscription).where(PushSubscription.id == subscription.id))

    await realtime.notify_user(notification.user_id)

    notification.dispatched_at = datetime.now(timezone.utc)


async def _dispatch_due() -> None:
    async with async_session() as db:
        result = await db.execute(
            select(Notification).where(
                Notification.dispatched_at.is_(None),
                # Уже отметили выполненным до наступления времени (сделали
                # заранее) — незачем слать пинг о том, что уже решено.
                # Исключение — повторяющееся: пинг не нужен, а вот цепочку
                # оборвать нельзя. «Полил цветы утром, галочку поставил» не
                # должно значить «больше не напоминать никогда».
                (Notification.resolved_at.is_(None)) | (Notification.repeat_rule.isnot(None)),
                (Notification.trigger_at.is_(None)) | (Notification.trigger_at <= datetime.now(timezone.utc)),
            )
        )
        due = result.scalars().all()
        for notification in due:
            if notification.resolved_at is None:
                try:
                    await _dispatch_one(notification, db)
                except Exception:
                    logger.exception("Ошибка доставки уведомления %s", notification.id)
            else:
                # Сделано заранее: доставлять нечего, но строку надо закрыть,
                # иначе следующий проход заведёт повтор второй раз.
                notification.dispatched_at = datetime.now(timezone.utc)
            # Следующий раз заводим ПОСЛЕ отправки, а не после отметки
            # «выполнено»: иначе цепочка «каждый понедельник» обрывалась
            # бы на первой же неделе, когда человек не нажал галочку.
            #
            # И именно здесь, а не внутри _dispatch_one: тот может упасть
            # (нет Telegram, протух push-ключ), а повторение от канала
            # доставки зависеть не должно.
            try:
                _schedule_next(notification, db)
            except Exception:
                logger.exception("Не удалось завести повтор для %s", notification.id)
            # Пинг приёма: та же строка взводится заново через nag_minutes,
            # пока приём не отметят или не истечёт его окно.
            if notification.type == routines.NOTIFICATION_TYPE and notification.resolved_at is None:
                routines.after_dispatch(notification, datetime.now(timezone.utc))
        if due:
            await db.commit()


def _schedule_next(notification: Notification, db) -> None:
    """Породить следующую копию повторяющегося напоминания."""
    if not notification.repeat_rule or notification.trigger_at is None:
        return
    following = next_occurrence(notification.trigger_at, notification.repeat_rule)
    if following is None:
        return

    db.add(
        Notification(
            user_id=notification.user_id,
            type=notification.type,
            title=notification.title,
            body=notification.body,
            payload=notification.payload,
            trigger_at=following,
            repeat_rule=notification.repeat_rule,
        )
    )
    # Правило снимаем с отправленной: иначе она породила бы следующую
    # копию ещё раз при любом повторном проходе.
    notification.repeat_rule = None
    logger.info("Повтор напоминания %s: следующий раз %s", notification.id, following)


async def run_dispatch_worker() -> None:
    while True:
        try:
            await _dispatch_due()
        except Exception:
            logger.exception("Ошибка при обходе неотправленных уведомлений")
        await asyncio.sleep(_DISPATCH_INTERVAL_SECONDS)
