from __future__ import annotations

from typing import Any

from app.llm.base import ToolDefinition
from app.routers.search import search_items
from app.tools.registry import ToolContext

DEFINITION = ToolDefinition(
    name="search_base",
    description=(
        "Полнотекстовый поиск по заметкам и спискам пользователя — по ВСЕМ его спейсам, не "
        "только текущему (ТЗ §10a). excerpt для списка это его реальные пункты (в формате "
        "[x]/[ ] текст), а для заметки — обрезанные первые 300 символов, НЕ всё содержимое. "
        "Если в заметке таблица, длинный список или что угодно длиннее пары предложений — после "
        "поиска вызови get_note по её id, чтобы прочитать целиком, прежде чем отвечать по её "
        "содержимому. Используй перед тем, как отвечать на вопрос по содержимому базы или "
        "перед созданием заметки/списка, чтобы не плодить дубликаты — объект может быть в "
        "другом спейсе пользователя, не только в текущем."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Поисковый запрос"}},
        "required": ["query"],
    },
)


async def handle(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"results": []}
    items = await search_items(ctx.db, ctx.user_id, query, material_types=("note", "list"), limit=20)
    if not items:
        # Модель обычно пишет запрос естественной фразой ("купить продукты"),
        # а не одним точным словом — при пустом строгом результате пробуем
        # мягче, по любому слову, а не по всем сразу.
        items = await search_items(
            ctx.db, ctx.user_id, query, material_types=("note", "list"), limit=20, match="or"
        )
    return {
        "results": [
            {
                "id": str(item.id),
                "title": item.title,
                "material_type": item.material_type,
                "excerpt": item.content[:300],
                "folder_id": str(item.folder_id) if item.folder_id else None,
                "space_id": str(item.space_id),
            }
            for item in items
        ]
    }
