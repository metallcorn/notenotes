from __future__ import annotations

from typing import Any

from app.llm.base import ToolDefinition
from app.tools.registry import ToolContext

# Обрабатывается отдельно в routers/dialogs.py ДО вызова dispatch — сюда
# управление никогда не доходит на практике. Реальный handler нужен только
# чтобы тул был валидной записью в реестре (get_tool_definitions читает
# отсюда описание для LLM).
SUGGEST_REPLIES = ToolDefinition(
    name="suggest_replies",
    description=(
        "Когда задаёшь пользователю вопрос с несколькими естественными короткими вариантами "
        "ответа (выбор папки из списка, да/нет, чек-лист или заметка и т.п.) — вызови это "
        "сразу после текста вопроса и предложи 2-5 коротких вариантов, чтобы пользователь мог "
        "кликнуть, а не печатать. Это последнее действие в ходе. Если у вопроса нет естественных "
        "коротких вариантов (ожидается свободный текст) — не вызывай."
    ),
    parameters={
        "type": "object",
        "properties": {
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-5 коротких вариантов ответа одним словом или короткой фразой",
            }
        },
        "required": ["options"],
    },
)


async def suggest_replies(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return {"shown": True}
