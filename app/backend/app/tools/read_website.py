from __future__ import annotations

from typing import Any

from app.llm.base import ToolDefinition
from app.read_website import fetch as fetch_website
from app.tools.registry import ToolContext, ToolError

DEFINITION = ToolDefinition(
    name="read_website",
    description=(
        "Скачивает страницу по КОНКРЕТНОЙ уже известной ссылке и возвращает её "
        "текстовое содержимое для чтения/пересказа. Не для поиска в интернете "
        "(для этого web_search) — только когда пользователь прислал ссылку на "
        "сайт и просит прочитать/пересказать/спрашивает, что там написано. "
        "Извлечение текста упрощённое (не полноценный алгоритм вроде Readability) "
        "— на статейных страницах обычно работает нормально, на сложных сайтах, "
        "где контент грузится через JavaScript, может вернуть пусто или мусор; "
        "тул в этом случае явно вернёт error, не выдумывай содержимое сам."
    ),
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Ссылка на страницу, которую нужно прочитать"}},
        "required": ["url"],
    },
)


async def handle(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url", "")).strip()
    if not url:
        raise ToolError("Ссылка не может быть пустой")
    return await fetch_website(url)
