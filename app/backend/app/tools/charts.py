"""График по таблице — блок в заметке.

Запрос владельца 18.11: показания из медицинских документов попадают в
таблицы, и их хочется видеть графиком — линией по датам, столбцами,
кругом, точками «одна ось против другой».

Устройство то же, что у встроенной таблицы (TableEmbed.ts): заметка
хранит только СПЕЦИФИКАЦИЮ графика — id таблицы, вид, столбцы — а данные
берутся из таблицы при показе (ChartEmbedCard.tsx). Таблица поменялась —
график перерисовался; удалили блок — таблица на месте. Столбцы
записываются по id, а не по имени: переименование столбца график не
ломает. Значений в заметке нет, поэтому в индекс и в сводку для модели
ничего лишнего не утекает.
"""

from __future__ import annotations

import html
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app import collab, realtime
from app.llm.base import ToolDefinition
from app.models import Item, ItemVersion
from app.tools.notes import _get_item_cross_space, _require_note_like
from app.tools.registry import ToolContext, ToolError
from app.tools.tables import _get_table_item

KINDS = ("line", "bar", "pie", "scatter")

_KIND_NAMES = {"line": "линия", "bar": "столбцы", "pie": "круг", "scatter": "точки"}

# Один самодостаточный тег на строке — как у остальных блоков-карточек.
_BLOCK_RE = re.compile(r'<div data-chart((?:\s+[\w-]+(?:="[^"]*")?)*)\s*></div>')
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def serialize_chart(
    table_id: str,
    kind: str,
    x: str | None,
    y: list[str],
    *,
    series: str | None = None,
    size: str | None = None,
    title: str = "",
) -> str:
    attrs = [f'data-table-id="{table_id}"', f'data-kind="{kind}"']
    if x:
        attrs.append(f'data-x="{x}"')
    attrs.append(f'data-y="{",".join(y)}"')
    if series:
        attrs.append(f'data-series="{series}"')
    if size:
        attrs.append(f'data-size="{size}"')
    if title:
        attrs.append(f'data-title="{html.escape(title, quote=True)}"')
    return f'<div data-chart {" ".join(attrs)}></div>'


def find_charts(content: str) -> list[dict[str, Any]]:
    """Спецификации всех графиков заметки в порядке появления."""
    found: list[dict[str, Any]] = []
    for m in _BLOCK_RE.finditer(content):
        attrs = {k: html.unescape(v) for k, v in _ATTR_RE.findall(m.group(1))}
        found.append({
            "table_id": attrs.get("data-table-id", ""),
            "kind": attrs.get("data-kind", "line"),
            "x": attrs.get("data-x") or None,
            "y": [c for c in attrs.get("data-y", "").split(",") if c],
            "series": attrs.get("data-series") or None,
            "size": attrs.get("data-size") or None,
            "title": attrs.get("data-title", ""),
        })
    return found


async def describe_charts(db: AsyncSession, content: str) -> list[dict[str, Any]]:
    """Графики заметки словами для модели: id столбцов → имена. Сырой тег
    модель прочитать не может, а «линия по таблице «Анализы»: X — Дата,
    Y — Значение, серии — Показатель» — может."""
    out: list[dict[str, Any]] = []
    for spec in find_charts(content):
        try:
            table = await db.get(Item, uuid.UUID(spec["table_id"]))
        except ValueError:
            table = None
        if table is None or table.material_type != "table" or table.deleted_at is not None:
            out.append({"kind": spec["kind"], "title": spec["title"], "table": None, "note": "таблица удалена или недоступна"})
            continue
        names = {c["id"]: c["name"] for c in table.properties.get("columns", [])}
        entry: dict[str, Any] = {
            "kind": spec["kind"],
            "title": spec["title"],
            "table_id": str(table.id),
            "table": table.title,
            "x": names.get(spec["x"], spec["x"]) if spec["x"] else None,
            "y": [names.get(c, c) for c in spec["y"]],
        }
        if spec["series"]:
            entry["series"] = names.get(spec["series"], spec["series"])
        if spec["size"]:
            entry["size"] = names.get(spec["size"], spec["size"])
        out.append(entry)
    return out


INSERT_CHART_BLOCK = ToolDefinition(
    name="insert_chart_block",
    description=(
        "Добавляет в конец заметки ГРАФИК по данным существующей таблицы: линия по датам (line), "
        "столбцы (bar), круговая диаграмма (pie) или точки «одна ось против другой» (scatter, "
        "с size_column — пузырьки). График живой: меняются строки таблицы — меняется и график. "
        "Данные в заметку не копируются, хранится только ссылка на таблицу и имена столбцов. "
        "Типичный случай — показатели анализов: таблица со столбцами «Дата», «Показатель», "
        "«Значение» → kind=line, x_column=«Дата», y_columns=[«Значение»], series_column=«Показатель» "
        "(одна линия на показатель). Если такой таблицы ещё нет — сначала create_table, "
        "потом этот тул. Столбцы называй ИМЕНАМИ из get_table/create_table."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "description": "id заметки, в которую вставить график"},
            "table_id": {"type": "string", "description": "id таблицы с данными (из list_all_items/create_table)"},
            "kind": {"type": "string", "enum": list(KINDS), "description": "Вид графика: line, bar, pie или scatter"},
            "x_column": {
                "type": "string",
                "description": "Столбец оси X (дата, число или категории). Для pie — столбец с подписями долей.",
            },
            "y_columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Числовые столбцы для оси Y. Для pie и scatter — ровно один; с series_column — тоже один.",
            },
            "series_column": {
                "type": "string",
                "description": "Столбец, по значениям которого данные делятся на серии (линии/группы столбцов/цвета точек), например «Показатель». Не для pie.",
            },
            "size_column": {"type": "string", "description": "Только для scatter: числовой столбец размера пузырька."},
            "title": {"type": "string", "description": "Подпись графика (необязательно)"},
        },
        "required": ["item_id", "table_id", "kind", "y_columns"],
    },
)


def _resolve_column(table: Item, raw: Any, *, what: str) -> dict[str, Any]:
    columns = table.properties.get("columns", [])
    wanted = str(raw).strip()
    for col in columns:
        if col["id"] == wanted or col["name"].strip().casefold() == wanted.casefold():
            return col
    valid = ", ".join(c["name"] for c in columns) or "(столбцов пока нет)"
    raise ToolError(f"Нет столбца «{wanted}» для {what} — реальные столбцы таблицы: {valid}")


async def insert_chart_block(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    _require_note_like(item)
    table = await _get_table_item(ctx, args.get("table_id"))

    kind = str(args.get("kind", "")).strip().lower()
    if kind not in KINDS:
        raise ToolError(f"Неизвестный вид графика «{kind}» — допустимы: {', '.join(KINDS)}")

    raw_y = args.get("y_columns") or []
    if isinstance(raw_y, str):
        raw_y = [raw_y]
    y_columns = [_resolve_column(table, raw, what="оси Y") for raw in raw_y if str(raw).strip()]
    if not y_columns:
        raise ToolError("В y_columns пусто — передай хотя бы один числовой столбец, имена столбцов смотри в get_table")
    x_raw = args.get("x_column")
    x_column = _resolve_column(table, x_raw, what="оси X") if x_raw and str(x_raw).strip() else None
    series_raw = args.get("series_column")
    series_column = _resolve_column(table, series_raw, what="серий") if series_raw and str(series_raw).strip() else None
    size_raw = args.get("size_column")
    size_column = _resolve_column(table, size_raw, what="размера") if size_raw and str(size_raw).strip() else None

    if kind == "pie":
        if len(y_columns) != 1:
            raise ToolError("Для круговой диаграммы в y_columns должен быть ровно один столбец — оставь столбец значений, а подписи долей задай через x_column")
        if x_column is None:
            raise ToolError("Для круговой диаграммы укажи x_column — столбец с подписями долей")
        if series_column is not None:
            raise ToolError("Круговая диаграмма не делится на серии — убери series_column")
    if kind == "scatter":
        if len(y_columns) != 1:
            raise ToolError("Для точечного графика в y_columns должен быть один столбец — второй показатель передай как size_column или series_column")
        if x_column is None:
            raise ToolError("Для точечного графика укажи x_column — числовой столбец или дата по оси X")
    if size_column is not None and kind != "scatter":
        raise ToolError("size_column работает только для scatter (пузырьки) — убери его или выбери kind=scatter")
    if series_column is not None and len(y_columns) > 1:
        raise ToolError("С series_column в y_columns нужен один столбец — серии и так дают несколько линий; для нескольких столбцов убери series_column")
    if kind in ("line", "bar") and x_column is None:
        raise ToolError("Укажи x_column — столбец дат или категорий по оси X")

    title = str(args.get("title") or "").strip()
    block = serialize_chart(
        str(table.id),
        kind,
        x_column["id"] if x_column else None,
        [c["id"] for c in y_columns],
        series=series_column["id"] if series_column else None,
        size=size_column["id"] if size_column else None,
        title=title,
    )

    ctx.db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=ctx.user_id))
    item.content = f"{item.content.rstrip()}\n\n{block}" if (item.content or "").strip() else block
    await ctx.db.commit()
    await ctx.db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    # Тот же обход Yjs, что у insert_delivery_block: иначе блок не долетит
    # до заметки с открытой живой коллаборацией.
    await collab.invalidate_room(item.id)

    description = f"{_KIND_NAMES[kind]} по таблице «{table.title}»"
    return {
        "id": str(item.id),
        "title": item.title,
        "chart": {
            "kind": kind,
            "table_id": str(table.id),
            "table": table.title,
            "x": x_column["name"] if x_column else None,
            "y": [c["name"] for c in y_columns],
            "series": series_column["name"] if series_column else None,
            "size": size_column["name"] if size_column else None,
            "title": title,
        },
        "message": f"График ({description}) добавлен в конец заметки",
    }
