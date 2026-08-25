from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app import collab, realtime
from app.delivery import SUPPORTED, track
from app.llm.base import ToolDefinition
from app.models import DeliveryWidget, ItemVersion
from app.tools.notes import _get_item_cross_space
from app.tools.registry import ToolContext, ToolError

_CARRIERS = ", ".join(c["id"] for c in SUPPORTED)

DEFINITION = ToolDefinition(
    name="track_delivery",
    description=(
        "Показывает статус доставки посылки по трек-номеру или ссылке "
        "отслеживания. Поддержаны польские перевозчики: InPost, Poczta Polska, "
        "Orlen Paczka, DPD, Allegro Delivery. Живой статус приходит для "
        "InPost/Poczta/Orlen; для DPD и Allegro Delivery возвращается только "
        "официальная ссылка (их защита не пускает автоматические запросы). "
        "Вызывай, когда пользователь прислал трек-номер "
        "или ссылку на отслеживание и спрашивает, где посылка. НЕ угадывай API "
        "перевозчиков и не выдумывай статусы — бери только то, что вернул тул. "
        "Если тул вернул need_carrier — перевозчик неясен, спроси у пользователя, "
        "какой из supported это, и вызови снова с параметром carrier."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tracking_number": {
                "type": "string",
                "description": "Трек-номер посылки или ссылка на страницу отслеживания",
            },
            "carrier": {
                "type": "string",
                "description": f"Перевозчик, если известен: один из {_CARRIERS}. Опционально.",
                "enum": [c["id"] for c in SUPPORTED],
            },
        },
        "required": ["tracking_number"],
    },
)


async def handle(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    raw = str(args.get("tracking_number", "")).strip()
    if not raw:
        raise ToolError("Не указан трек-номер или ссылка")
    carrier = args.get("carrier")
    return await track(raw, str(carrier).strip().lower() if carrier else None)


def _serialize_block(widget_id: object) -> str:
    # В content заметки — только непрозрачная ссылка на DeliveryWidget;
    # перевозчик/номер/результат живут в таблице (по образцу url_check).
    return f'<div data-delivery data-delivery-id="{widget_id}"></div>'


INSERT_DELIVERY_BLOCK = ToolDefinition(
    name="insert_delivery_block",
    description=(
        "Добавляет в заметку ПОСТОЯННЫЙ виджет отслеживания доставки с кнопкой "
        "«Обновить» — в отличие от track_delivery (тот просто показывает статус в "
        "чате), этот сохраняет карточку в заметке, чтобы возвращаться к ней и "
        "обновлять статус позже. Вызывай, когда пользователь просит «следить» за "
        "посылкой, добавить/сохранить отслеживание в заметку. Сначала лучше "
        "показать статус через track_delivery, а этот вызывай, когда пользователь "
        "подтвердил, что хочет сохранить виджет (как с insert_url_check_block — не "
        "молча). Блок добавляется в конец заметки. Если перевозчик по номеру "
        "неоднозначен (need_carrier) — сначала уточни через track_delivery."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "description": "ID заметки, в которую добавить виджет"},
            "tracking_number": {"type": "string", "description": "Трек-номер или ссылка отслеживания"},
            "carrier": {
                "type": "string",
                "description": f"Перевозчик, если известен: один из {_CARRIERS}. Опционально.",
                "enum": [c["id"] for c in SUPPORTED],
            },
        },
        "required": ["item_id", "tracking_number"],
    },
)


async def insert_delivery_block(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    raw = str(args.get("tracking_number", "")).strip()
    if not raw:
        raise ToolError("Не указан трек-номер или ссылка")
    carrier_arg = args.get("carrier")
    result = await track(raw, str(carrier_arg).strip().lower() if carrier_arg else None)
    if result.get("need_carrier"):
        # Перевозчик неясен даже после проверки по всем перевозчикам с
        # живой проверкой (см. track_any в delivery.py) — не создаём виджет
        # вслепую, просим уточнить (тем же способом, что track_delivery).
        return result

    widget = DeliveryWidget(
        item_id=item.id,
        carrier=result["carrier"],
        tracking_number=result["tracking_number"],
        last_result=json.dumps(result, ensure_ascii=False),
        last_fetched_at=datetime.now(timezone.utc),
    )
    ctx.db.add(widget)
    await ctx.db.flush()

    block = _serialize_block(widget.id)
    ctx.db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=ctx.user_id))
    item.content = f"{item.content.rstrip()}\n\n{block}" if item.content.strip() else block

    await ctx.db.commit()
    await ctx.db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    # Тот же обход Yjs, что у insert_url_check_block — иначе блок не долетит
    # до заметки с открытой живой коллаборацией.
    await collab.invalidate_room(item.id)
    return {"id": str(item.id), "title": item.title,
            "carrier": result["carrier"], "tracking_number": result["tracking_number"]}
