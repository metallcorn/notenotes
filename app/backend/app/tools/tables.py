from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.deps import ensure_space_access, is_vault_space
from app.llm.base import ToolDefinition
from app.models import Item, Space
from app.routers.items import create_item_row
from app.routers.tables import _broadcast, _flatten_table, _serialize
from app.tools.lists import _resolve_folder
from app.tools.registry import ToolContext, ToolError

logger = logging.getLogger(__name__)


async def _safe_broadcast(item: Item) -> None:
    """Та же причина, что tools/lists.py::_safe_broadcast — рассылка не
    источник истины, падение сериализации/сети не должно превращать
    успешно сохранённую запись в "ошибку" для модели."""
    try:
        await _broadcast(item.id, _serialize(item).model_dump(mode="json"))
    except Exception:
        logger.exception("Не удалось разослать обновление таблицы %s по WS (сама запись уже сохранена)", item.id)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_table_item(ctx: ToolContext, table_id_raw: Any) -> Item:
    """Таблица ищется среди ВСЕХ спейсов пользователя, не только текущего
    диалога — тот же принцип, что tools/lists.py::_get_list_item."""
    try:
        table_id = uuid.UUID(str(table_id_raw))
    except (ValueError, TypeError):
        raise ToolError(f"Некорректный id таблицы: {table_id_raw} — нужен UUID из результата list_all_items, а не название таблицы") from None

    item = await ctx.db.get(Item, table_id)
    if item is None or item.material_type != "table" or item.deleted_at is not None:
        raise ToolError("Таблица не найдена — вызови list_all_items, чтобы увидеть реальные таблицы и их id")
    try:
        await ensure_space_access(ctx.db, item.space_id, ctx.user_id)
    except HTTPException:
        raise ToolError("Таблица не найдена — вызови list_all_items, чтобы увидеть реальные таблицы и их id") from None
    if await is_vault_space(ctx.db, item.space_id):
        raise ToolError("Таблица не найдена — вызови list_all_items, чтобы увидеть реальные таблицы и их id")
    return item


# Ячейка таблицы — ПЛОСКИЙ ТЕКСТ: TableGrid.tsx рендерит её в <textarea>
# значением, без markdown. А модель, дописывая подход в ячейку, выделяет
# добавленное жирным — и в данные уезжает буквальное «**2: 7 кг × 8**».
# Найдено на боевой базе 07.10: 21 строка из 35 в «Таблице тренировок»,
# всегда последний подход, и именно это ломало «нормально найти и
# статистику собрать» (жалоба владельца в том же диалоге).
#
# Снимаем на записи, а не на отображении: в ячейке лежат данные, и
# чинить их показом значило бы хранить мусор вечно.
_EMPHASIS_RE = re.compile(
    r"""
    (?<![*_\w])            # не середина слова и не ***жирный курсив***
    (\*\*|\*|__|_)        # открывающий маркер
    (?=\S)                 # сразу за ним непробел — иначе это не разметка
    (.+?)                  # содержимое, минимально
    (?<=\S)                # перед закрывающим маркером тоже непробел
    \1                     # тот же маркер
    (?![*_\w])
    """,
    re.VERBOSE | re.DOTALL,
)


def strip_emphasis(value: str) -> str:
    r"""Убрать markdown-выделение, оставив сам текст.

    Подчёркивание тоже маркер, но в данных оно часто значимо
    (`snake_case`, `id_строки`), поэтому `(?<![*_\w])` и `(?![*_\w])`:
    `_курсив_` снимается, `some_name_here` — нет.
    """
    previous = None
    text = value
    # Цикл — ради вложенного «**_текст_**»: один проход снимет только
    # внешний маркер.
    while text != previous:
        previous = text
        text = _EMPHASIS_RE.sub(r"\2", text)
    return text


def _cells_by_name(item: Item, cells_by_name: dict[str, str]) -> dict[str, str]:
    """Модель адресует столбцы по имени (id столбца ей взять неоткуда без
    лишнего get_table) — переводим в id для хранения, тем же способом,
    каким create_table переводит имена столбцов в rows при создании."""
    columns = item.properties.get("columns", [])
    name_to_id = {c["name"]: c["id"] for c in columns}
    result: dict[str, str] = {}
    unknown: list[str] = []
    for name, value in cells_by_name.items():
        col_id = name_to_id.get(name)
        if col_id is None:
            unknown.append(name)
        else:
            result[col_id] = strip_emphasis(str(value))
    if unknown:
        valid = ", ".join(c["name"] for c in columns) or "(столбцов пока нет)"
        raise ToolError(f"Нет столбца с именем {unknown} — реальные столбцы: {valid}")
    return result


def _row_cells_to_names(item: Item, row: dict[str, Any]) -> dict[str, str]:
    columns = item.properties.get("columns", [])
    id_to_name = {c["id"]: c["name"] for c in columns}
    return {id_to_name.get(k, k): v for k, v in row.get("cells", {}).items()}


CREATE_TABLE = ToolDefinition(
    name="create_table",
    description=(
        "Создать таблицу (структурные данные со столбцами и строками — для дневников тренировок, "
        "учёта расходов и подобного, где нужны именно колонки, а не текст заметки или пункты списка). "
        "Можно сразу задать столбцы и несколько первых строк. Без folder_id создаётся в текущем "
        "спейсе диалога — ПЕРЕД вызовом без folder_id проверь list_folders на тематически подходящую "
        "папку; с folder_id — в спейсе, которому принадлежит папка."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Название таблицы"},
            "folder_id": {"type": "string", "description": "id папки; не указывать — таблица в корне текущего спейса"},
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Названия столбцов по порядку, например ['Упражнение', 'Вес', 'Повторы']",
            },
            "rows": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": {"type": "string"}},
                "description": (
                    "Первые строки (необязательно) — каждая строка объект {имя_столбца: значение}, "
                    "имена ДОЛЖНЫ точно совпадать с columns выше."
                ),
            },
        },
        "required": ["title"],
    },
)


async def create_table(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    if not title:
        raise ToolError("Название таблицы не может быть пустым — придумай короткое по смыслу содержимого или спроси у пользователя через suggest_replies")

    folder_id, space_id = await _resolve_folder(ctx, args.get("folder_id"))

    columns = [
        {"id": str(uuid.uuid4()), "name": str(n).strip(), "type": "text"}
        for n in (args.get("columns") or [])
        if str(n).strip()
    ]
    name_to_id = {c["name"]: c["id"] for c in columns}

    rows = []
    for raw_row in args.get("rows") or []:
        if not isinstance(raw_row, dict):
            continue
        cells = {name_to_id[k]: strip_emphasis(str(v)) for k, v in raw_row.items() if k in name_to_id}
        if cells:
            rows.append({"id": str(uuid.uuid4()), "cells": cells, "created_at": _now_iso()})

    item = await create_item_row(
        ctx.db,
        space_id=space_id,
        author_id=ctx.user_id,
        material_type="table",
        title=title,
        folder_id=folder_id,
        content=_flatten_table(columns, rows),
        properties={"columns": columns, "rows": rows},
    )

    space = await ctx.db.get(Space, item.space_id)
    return {
        "id": str(item.id),
        "title": item.title,
        "columns": [c["name"] for c in columns],
        "rows_added": len(rows),
        "space_id": str(item.space_id),
        "space_name": space.name if space else "",
    }


GET_TABLE = ToolDefinition(
    name="get_table",
    description=(
        "Посмотреть реальное содержимое таблицы (столбцы и все строки) по id. Вызывай перед тем, как "
        "показывать пользователю содержимое, отвечать на вопросы о нём или менять строки/столбцы — "
        "НИКОГДА не придумывай содержимое таблицы самостоятельно. Нужен и для получения id строк "
        "(update_table_row/delete_table_row адресуют строку по id, не по содержимому)."
    ),
    parameters={
        "type": "object",
        "properties": {"table_id": {"type": "string"}},
        "required": ["table_id"],
    },
)


async def get_table(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_table_item(ctx, args.get("table_id"))
    columns = item.properties.get("columns", [])
    rows = item.properties.get("rows", [])
    return {
        "id": str(item.id),
        "title": item.title,
        "columns": [{"id": c["id"], "name": c["name"], "type": c["type"]} for c in columns],
        "rows": [{"id": r["id"], "cells": _row_cells_to_names(item, r)} for r in rows],
    }


ADD_TABLE_ROW = ToolDefinition(
    name="add_table_row",
    description=(
        "Добавить НОВУЮ строку в уже существующую таблицу — одна строка, а не вся таблица целиком "
        "(в отличие от update_note для обычных заметок, здесь не нужно пересказывать предыдущие "
        "строки). cells — объект {имя_столбца: значение}, имена столбцов ДОЛЖНЫ точно совпадать с "
        "реальными (сверься по get_table, если не уверен); столбцы, не упомянутые в cells, останутся "
        "пустыми у этой строки. В результате возвращается row_id созданной строки — используй его "
        "для update_table_row, повторный get_table ради id не нужен. Значения — ПЛОСКИЙ текст, "
        "markdown в ячейках не отображается: никакого **жирного**, только сами данные."
    ),
    parameters={
        "type": "object",
        "properties": {
            "table_id": {"type": "string"},
            "cells": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": ["table_id", "cells"],
    },
)


async def add_table_row(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_table_item(ctx, args.get("table_id"))
    cells = _cells_by_name(item, dict(args.get("cells") or {}))

    rows = list(item.properties.get("rows", []))
    row_id = str(uuid.uuid4())
    rows.append({"id": row_id, "cells": cells, "created_at": _now_iso()})
    item.properties = {**item.properties, "rows": rows}
    item.content = _flatten_table(item.properties.get("columns", []), rows)
    await ctx.db.commit()
    await ctx.db.refresh(item)

    await _safe_broadcast(item)
    # id/title — тот же формат результата, что у create_note/create_list,
    # чтобы фронтенд (CreatedItemLinks в AssistantChat.tsx) мог показать
    # кликабельную "Открыть «Название»" единым способом для всех тулов.
    #
    # row_id ОБЯЗАТЕЛЕН в результате. Без него модель не знает id строки,
    # которую сама же только что создала, — а update_table_row адресует
    # строку только по id. Живой случай 07.10 (диалог «Тренировки»): на
    # каждое «ещё подход» выходило update_table_row с выдуманным id →
    # "Строка не найдена" → get_table (дамп всей таблицы, ~9 300 симв.) →
    # повтор. Четырнадцать таких циклов в одном диалоге, ~130 тысяч
    # символов контекста на то, чего не должно было случиться.
    return {
        "id": str(item.id),
        "title": item.title,
        "table_id": str(item.id),
        "row_id": row_id,
        "cells": _row_cells_to_names(item, rows[-1]),
    }


UPDATE_TABLE_ROW = ToolDefinition(
    name="update_table_row",
    description=(
        "Изменить ячейки уже существующей строки по её id (row_id из результата add_table_row "
        "или из get_table) — обновляет только переданные в cells столбцы, остальные ячейки строки "
        "не трогает. Значения — ПЛОСКИЙ текст: markdown в ячейках не отображается, не выделяй "
        "дописанное **жирным**."
    ),
    parameters={
        "type": "object",
        "properties": {
            "table_id": {"type": "string"},
            "row_id": {"type": "string"},
            "cells": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": ["table_id", "row_id", "cells"],
    },
)


async def update_table_row(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_table_item(ctx, args.get("table_id"))
    row_id = str(args.get("row_id", ""))
    new_cells = _cells_by_name(item, dict(args.get("cells") or {}))

    rows = []
    found = None
    for row in item.properties.get("rows", []):
        if row["id"] == row_id:
            merged = {**row["cells"], **new_cells}
            found = {**row, "cells": merged}
            rows.append(found)
        else:
            rows.append(row)
    if found is None:
        raise ToolError("Строка не найдена — сначала вызови get_table, чтобы увидеть реальные строки и их id")

    item.properties = {**item.properties, "rows": rows}
    item.content = _flatten_table(item.properties.get("columns", []), rows)
    await ctx.db.commit()
    await ctx.db.refresh(item)

    await _safe_broadcast(item)
    return {
        "id": str(item.id),
        "title": item.title,
        "table_id": str(item.id),
        "row_id": row_id,
        "cells": _row_cells_to_names(item, found),
    }


DELETE_TABLE_ROW = ToolDefinition(
    name="delete_table_row",
    description="Удалить строку таблицы по её id (из get_table).",
    parameters={
        "type": "object",
        "properties": {"table_id": {"type": "string"}, "row_id": {"type": "string"}},
        "required": ["table_id", "row_id"],
    },
)


async def delete_table_row(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_table_item(ctx, args.get("table_id"))
    row_id = str(args.get("row_id", ""))
    existing = item.properties.get("rows", [])
    rows = [r for r in existing if r["id"] != row_id]
    if len(rows) == len(existing):
        raise ToolError("Строка не найдена — сначала вызови get_table, чтобы увидеть реальные строки и их id")

    item.properties = {**item.properties, "rows": rows}
    item.content = _flatten_table(item.properties.get("columns", []), rows)
    await ctx.db.commit()
    await ctx.db.refresh(item)

    await _safe_broadcast(item)
    return {"id": str(item.id), "title": item.title, "table_id": str(item.id), "row_id": row_id, "deleted": True}


ADD_TABLE_COLUMN = ToolDefinition(
    name="add_table_column",
    description="Добавить новый столбец в конец уже существующей таблицы (например, «добавь колонку для комментария»).",
    parameters={
        "type": "object",
        "properties": {
            "table_id": {"type": "string"},
            "name": {"type": "string"},
        },
        "required": ["table_id", "name"],
    },
)


async def add_table_column(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    # См. create_folder в notes.py: соседние тулы ждут "title", этот —
    # "name". Принимаем оба, чтобы обобщение модели не ломало вызов.
    name = str(args.get("name") or args.get("title") or "").strip()
    if not name:
        raise ToolError("Пустое название столбца — передай непустое name; текущие столбцы видны в результате get_table")

    item = await _get_table_item(ctx, args.get("table_id"))
    columns = list(item.properties.get("columns", []))
    columns.append({"id": str(uuid.uuid4()), "name": name, "type": "text"})
    item.properties = {**item.properties, "columns": columns}
    item.content = _flatten_table(columns, item.properties.get("rows", []))
    await ctx.db.commit()
    await ctx.db.refresh(item)

    await _safe_broadcast(item)
    return {"id": str(item.id), "title": item.title, "table_id": str(item.id), "columns": [c["name"] for c in columns]}
