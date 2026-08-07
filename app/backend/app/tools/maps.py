from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.llm.base import ToolDefinition
from app.tools.registry import ToolContext, ToolError

# Модель систематически придумывает несуществующие Google Maps ссылки с
# координатами/place-id (реальный баг, ловили на живом диалоге) — вместо
# запрета "никогда не пиши ссылку сам" даём безопасную альтернативу: обычный
# универсальный поиск-URL Google Maps по текстовому названию места, без
# координат и place-id. Такая ссылка синтаксически не может быть "неверной" —
# она либо найдёт место по названию, либо покажет обычный пустой поиск.

CREATE_MAPS_LINK = ToolDefinition(
    name="create_maps_link",
    description=(
        "Создать безопасную ссылку-навигатор на место по названию/адресу. НЕ пиши "
        "ссылки на Google Maps текстом сам — координаты и place-id ты гарантированно "
        "придумаешь неверными. Вместо этого вызови этот тул с текстовым названием "
        "и/или адресом места (из заметки или web_search) — ссылка откроет поиск по "
        "этому названию в Google Maps (в приложении на телефоне или в браузере). "
        "Работает для любого места, даже если точный адрес и координаты неизвестны. "
        "ВАЖНО: это текстовый поиск, не точная точка — короткое общее название "
        "(например, просто 'вокзал' или частое имя без города) может совпасть с "
        "несколькими местами, и пользователь не поймёт, куда его привело. Клади в "
        "query максимум конкретики, которая у тебя реально есть (полное официальное "
        "название + город/улица/район из web_search, а не то, что придумал сам)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Название и/или адрес места — максимально конкретно, например "
                    "'Rock Garaż, ul. Kozia 10, Poznań', а не просто 'Rock Garaż' или "
                    "'вокзал'"
                ),
            }
        },
        "required": ["query"],
    },
)


async def create_maps_link(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ToolError("Название места не может быть пустым")
    return {"query": query, "url": f"https://www.google.com/maps/search/?api=1&query={quote(query)}"}
