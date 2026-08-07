from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
