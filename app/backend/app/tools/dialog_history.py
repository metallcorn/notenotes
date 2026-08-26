from __future__ import annotations

from typing import Any

from app.dialog_compaction import render_old_messages_for_summary
from app.llm.base import ToolDefinition
from app.tools.notes import _get_item_cross_space
from app.tools.registry import ToolContext, ToolError

# Реальный запрос пользователя: сводка (dialog_compaction.py) хорошо годится
# для "что вообще обсуждали", но для точного вопроса про конкретную дату/
# деталь ("а что там было 10.06") модель по сводке может понять, ЧТО
# обсуждалось, но не хватит точности для уверенного ответа. Вместо отдельного
# поиска по ключевым словам (ненадёжно на перефразированный вопрос) — модель
# сама читает весь дословный оригинал сжатого куска и сама находит нужное,
# тем же способом, что get_note даёт полный текст заметки вместо обрезанного
# превью из search_base.

GET_COMPACTED_HISTORY = ToolDefinition(
    name="get_compacted_history",
    description=(
        "Читает ДОСЛОВНЫЙ оригинальный текст более ранней части ЭТОГО диалога, которая была "
        "сжата в сводку — доступные snapshot_id перечислены в системной подсказке, если сжатия "
        "были. Вызывай, когда сводки недостаточно точно для ответа (например, спросили что-то "
        "конкретное про определённую дату/деталь, а в сводке это расписано не настолько подробно). "
        "НЕ вызывай, если сводки уже достаточно — это не бесплатно, не дёргай на каждый вопрос."
    ),
    parameters={
        "type": "object",
        "properties": {
            "dialog_id": {"type": "string", "description": "id этого диалога"},
            "snapshot_id": {"type": "string", "description": "id точки сжатия из системной подсказки"},
        },
        "required": ["dialog_id", "snapshot_id"],
    },
)


async def get_compacted_history(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("dialog_id"))
    if item.material_type != "dialog":
        raise ToolError("Это не диалог")

    snapshot_id = str(args.get("snapshot_id") or "")
    snapshot = next(
        (s for s in item.properties.get("compaction_snapshots", []) if s["id"] == snapshot_id), None
    )
    if snapshot is None:
        raise ToolError(
            "Точка сжатия не найдена — возможно, её уже отменили (Отменить сжатие) или она "
            "поглощена более поздним сжатием"
        )

    return {"transcript": render_old_messages_for_summary(snapshot["replaced_messages"])}
