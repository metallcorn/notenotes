from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.llm.base import ToolDefinition
from app.models import Notification
from app.tools.notes import _get_item_cross_space
from app.tools.registry import ToolContext, ToolError

# Напоминания переиспользуют центр уведомлений (ТЗ §13), не отдельную
# таблицу — trigger_at в будущем просто не отдаётся списком, пока время не
# наступит (см. routers/notifications.py). Планировщика/воркера не нужно:
# "видимость" уведомления — это фильтр в выборке, не активное событие.

CREATE_REMINDER = ToolDefinition(
    name="create_reminder",
    description=(
        "Создать напоминание — появится в центре уведомлений в указанное время (не сразу, не "
        "прямо сейчас). ВСЕГДА сначала спроси пользователя, нужно ли напоминание и на какое время "
        "— никогда не создавай сам просто потому что в разговоре упомянута дата или дедлайн, только "
        "по явному согласию (как /remind в Slack — спрашивает, прежде чем поставить). Можно "
        "привязать к конкретной заметке/списку (item_id) и, если это список, к конкретному пункту "
        "(entry_id из get_list) — клик по уведомлению откроет ровно эту заметку или этот пункт, а "
        "не список целиком."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Короткий заголовок напоминания"},
            "body": {"type": "string", "description": "Необязательные подробности"},
            "trigger_at": {
                "type": "string",
                "description": "Когда показать напоминание, ISO 8601 ('2026-08-08T09:00:00') — только то, что явно назвал пользователь",
            },
            "item_id": {"type": "string", "description": "id заметки/списка, к которому относится напоминание — необязательно"},
            "entry_id": {
                "type": "string",
                "description": "id конкретного пункта списка (из get_list) — необязательно, только если item_id это список",
            },
        },
        "required": ["title", "trigger_at"],
    },
)


async def create_reminder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    if not title:
        raise ToolError("Название напоминания не может быть пустым")

    trigger_raw = args.get("trigger_at")
    if not trigger_raw:
        raise ToolError("trigger_at обязателен")
    try:
        trigger_at = datetime.fromisoformat(str(trigger_raw))
    except ValueError:
        raise ToolError(f"Некорректные дата/время: {trigger_raw}") from None
    if trigger_at.tzinfo is None:
        trigger_at = trigger_at.replace(tzinfo=timezone.utc)

    payload: dict[str, Any] = {}
    item_id_raw = args.get("item_id")
    if item_id_raw:
        item = await _get_item_cross_space(ctx, item_id_raw)
        payload["item_id"] = str(item.id)
        payload["space_id"] = str(item.space_id)
        payload["material_type"] = item.material_type

        entry_id_raw = args.get("entry_id")
        if entry_id_raw:
            entries = item.properties.get("entries", [])
            if not any(e["id"] == str(entry_id_raw) for e in entries):
                raise ToolError("Пункт списка не найден")
            payload["entry_id"] = str(entry_id_raw)

    notification = Notification(
        user_id=ctx.user_id,
        type="reminder",
        title=title,
        body=str(args.get("body", "")).strip(),
        payload=payload,
        trigger_at=trigger_at,
    )
    ctx.db.add(notification)
    await ctx.db.commit()
    await ctx.db.refresh(notification)
    return {"id": str(notification.id), "title": title, "trigger_at": trigger_at.isoformat()}


# "Выполнено" — независимая ось от trigger_at (ТЗ живой жалобы: время
# напоминания прошло не значит, что дело сделано, юзер продолжает считать
# его активным, пока сам не отметит). list_reminders — чтобы модель могла
# найти нужное напоминание по смыслу перед resolve_reminder, не зная id
# заранее (тот же паттерн, что get_list/toggle_list_entry для пунктов
# списка).

LIST_REMINDERS = ToolDefinition(
    name="list_reminders",
    description=(
        "Список активных (ещё не отмеченных выполненными) напоминаний пользователя — id, "
        "заголовок, текст, время срабатывания. Используй перед resolve_reminder, чтобы найти "
        "нужное напоминание по смыслу, если пользователь ссылается на него не по id, а по теме "
        "(например «отметь, что с банком я разобрался»)."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)


async def list_reminders(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.db.execute(
        select(Notification)
        .where(Notification.user_id == ctx.user_id, Notification.resolved_at.is_(None))
        .order_by(Notification.trigger_at.asc().nulls_first())
    )
    reminders = result.scalars().all()
    return {
        "reminders": [
            {
                "id": str(n.id),
                "title": n.title,
                "body": n.body,
                "trigger_at": n.trigger_at.isoformat() if n.trigger_at else None,
            }
            for n in reminders
        ]
    }


RESOLVE_REMINDER = ToolDefinition(
    name="resolve_reminder",
    description=(
        "Отметить напоминание выполненным — уходит из активных, вне зависимости от того, "
        "наступило ли уже его время. Используй, когда пользователь говорит, что уже сделал или "
        "разобрался с тем, о чём было напоминание. Не спрашивай подтверждения — сама просьба "
        "пользователя уже и есть подтверждение (в отличие от create_reminder, где спрашивать "
        "обязательно)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "notification_id": {"type": "string", "description": "id напоминания, взятый из list_reminders"},
        },
        "required": ["notification_id"],
    },
)


async def resolve_reminder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    notification_id_raw = args.get("notification_id")
    if not notification_id_raw:
        raise ToolError("notification_id обязателен")
    try:
        notification_id = uuid.UUID(str(notification_id_raw))
    except ValueError:
        raise ToolError("Некорректный notification_id") from None

    notification = await ctx.db.get(Notification, notification_id)
    if notification is None or notification.user_id != ctx.user_id:
        raise ToolError("Напоминание не найдено")

    if notification.resolved_at is None:
        notification.resolved_at = datetime.now(timezone.utc)
        await ctx.db.commit()
    return {"id": str(notification.id), "title": notification.title, "resolved": True}
