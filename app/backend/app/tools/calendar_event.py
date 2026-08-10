from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.llm.base import ToolDefinition
from app.tools.registry import ToolContext, ToolError

# Своей интеграции с календарём ещё нет (ТЗ §16.2/Фаза 4) — вместо нативного
# создания события тул готовит структурированные данные, из которых
# фронтенд на лету собирает .ics-файл (RFC 5545). Клик — и ОС/браузер сам
# открывает системный диалог "добавить событие" в Google/Apple/Outlook.
# Бэкенд ничего не сохраняет и никуда не пишет — это чистое форматирование
# входных данных модели, без побочных эффектов.

CREATE_CALENDAR_EVENT = ToolDefinition(
    name="create_calendar_event",
    description=(
        "Подготовить данные события для кнопки «Добавить в календарь» (Google/Apple/"
        "Outlook) — используй, когда пользователь просит создать заметку или "
        "напоминание про конкретное будущее событие с известной датой. Как подавать "
        "результат пользователю — см. общую инструкцию в промпте."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Название события"},
            "start": {
                "type": "string",
                "description": "Начало, ISO 8601: 'YYYY-MM-DD' для события на весь день или 'YYYY-MM-DDTHH:MM:SS' с временем",
            },
            "end": {
                "type": "string",
                "description": (
                    "Конец, тот же формат, что и start; без указания — +1 час для события с "
                    "временем или тот же день для события на весь день"
                ),
            },
            "location": {"type": "string", "description": "Место проведения"},
            "description": {"type": "string", "description": "Описание события"},
        },
        "required": ["title", "start"],
    },
)


def _parse(value: str) -> tuple[datetime | date, bool]:
    value = value.strip()
    if len(value) == 10:
        try:
            return date.fromisoformat(value), True
        except ValueError:
            raise ToolError(f"Некорректная дата: {value}") from None
    try:
        return datetime.fromisoformat(value), False
    except ValueError:
        raise ToolError(f"Некорректные дата/время: {value}") from None


async def create_calendar_event(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    if not title:
        raise ToolError("Название события не может быть пустым")

    start_raw = args.get("start")
    if not start_raw:
        raise ToolError("start обязателен")
    start, all_day = _parse(str(start_raw))

    end_raw = args.get("end")
    if end_raw:
        end, end_all_day = _parse(str(end_raw))
        if end_all_day != all_day:
            raise ToolError("start и end должны быть в одном формате — оба с датой или оба с датой и временем")
    else:
        end = (start + timedelta(days=1)) if all_day else (start + timedelta(hours=1))

    return {
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "all_day": all_day,
        "location": str(args.get("location") or "").strip(),
        "description": str(args.get("description") or "").strip(),
    }
