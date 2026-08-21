from __future__ import annotations

from typing import Any

from app.delivery import SUPPORTED, track
from app.llm.base import ToolDefinition
from app.tools.registry import ToolContext, ToolError

_CARRIERS = ", ".join(c["id"] for c in SUPPORTED)

DEFINITION = ToolDefinition(
    name="track_delivery",
    description=(
        "Показывает статус доставки посылки по трек-номеру или ссылке "
        "отслеживания. Поддержаны польские перевозчики: InPost, Poczta Polska, "
        "Orlen Paczka, DPD. Живой статус приходит для InPost/Poczta/Orlen; для "
        "DPD возвращается только официальная ссылка (их защита не пускает "
        "автоматические запросы). Вызывай, когда пользователь прислал трек-номер "
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
