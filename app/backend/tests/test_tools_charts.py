"""График по таблице в заметке (tools/charts.py).

Запрос 18.11: показания из медицинских документов лежат в таблицах, их
хочется видеть линией по датам. Блок в заметке хранит только ссылку на
таблицу и id столбцов — ни одного значения. Данные вымышленные.
"""

from __future__ import annotations

import pytest

from app.models import Item, Space, SpaceMember
from app.tools import charts, notes, tables
from app.tools.registry import TOOL_GROUPS, ToolContext, ToolError, _expand_disabled, get_tool_definitions


@pytest.fixture
async def ctx(db_session, test_user):
    space = Space(name="Семейный", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()
    return ToolContext(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="Europe/Warsaw")


async def _table(ctx) -> str:
    out = await tables.create_table(ctx, {
        "title": "Анализы Jan Kowalski",
        "columns": ["Дата", "Показатель", "Значение"],
        "rows": [
            {"Дата": "01.03.2026", "Показатель": "Гемоглобин", "Значение": "140"},
            {"Дата": "01.06.2026", "Показатель": "Гемоглобин", "Значение": "137"},
            {"Дата": "01.03.2026", "Показатель": "Ферритин", "Значение": "55"},
        ],
    })
    return out["id"]


async def _note(ctx, content: str = "Результаты за год") -> Item:
    item = Item(space_id=ctx.space_id, author_id=ctx.user_id, material_type="note", title="Здоровье", content=content)
    ctx.db.add(item)
    await ctx.db.commit()
    return item


def _column_ids(table_props: dict) -> dict[str, str]:
    return {c["name"]: c["id"] for c in table_props["columns"]}


async def test_линия_по_датам_с_сериями_пишет_id_столбцов_а_не_значения(ctx):
    table_id = await _table(ctx)
    note = await _note(ctx)

    out = await charts.insert_chart_block(ctx, {
        "item_id": str(note.id), "table_id": table_id, "kind": "line",
        "x_column": "дата", "y_columns": ["Значение"], "series_column": "Показатель", "title": "Кровь",
    })

    await ctx.db.refresh(note)
    table = await ctx.db.get(Item, __import__("uuid").UUID(table_id))
    ids = _column_ids(table.properties)
    assert note.content.startswith("Результаты за год\n\n<div data-chart ")
    assert note.content.rstrip().endswith("></div>")
    for value in ("140", "137", "Гемоглобин"):
        assert value not in note.content, "данные остаются в таблице, в заметке только ссылка"
    spec, = charts.find_charts(note.content)
    assert spec == {
        "table_id": table_id, "kind": "line", "x": ids["Дата"], "y": [ids["Значение"]],
        "series": ids["Показатель"], "size": None, "title": "Кровь",
    }
    assert out["chart"]["x"] == "Дата" and out["chart"]["series"] == "Показатель"


async def test_get_note_называет_столбцы_графика_именами(ctx):
    table_id = await _table(ctx)
    note = await _note(ctx)
    await charts.insert_chart_block(ctx, {
        "item_id": str(note.id), "table_id": table_id, "kind": "bar", "x_column": "Дата", "y_columns": ["Значение"],
    })

    result = await notes.get_note(ctx, {"item_id": str(note.id)})

    assert result["charts"] == [{
        "kind": "bar", "title": "", "table_id": table_id, "table": "Анализы Jan Kowalski",
        "x": "Дата", "y": ["Значение"],
    }]


async def test_неизвестный_столбец_перечисляет_настоящие(ctx):
    table_id = await _table(ctx)
    note = await _note(ctx)
    with pytest.raises(ToolError, match="Дата, Показатель, Значение"):
        await charts.insert_chart_block(ctx, {
            "item_id": str(note.id), "table_id": table_id, "kind": "line", "x_column": "Дата", "y_columns": ["Вес"],
        })
    await ctx.db.refresh(note)
    assert "data-chart" not in note.content


@pytest.mark.parametrize(
    "args, message",
    [
        ({"kind": "donut", "x_column": "Дата", "y_columns": ["Значение"]}, "Неизвестный вид"),
        ({"kind": "pie", "y_columns": ["Значение"]}, "подписями долей"),
        ({"kind": "pie", "x_column": "Показатель", "y_columns": ["Значение"], "series_column": "Дата"}, "не делится на серии"),
        ({"kind": "line", "y_columns": ["Значение"]}, "Укажи x_column"),
        ({"kind": "line", "x_column": "Дата", "y_columns": ["Значение"], "size_column": "Значение"}, "только для scatter"),
        ({"kind": "line", "x_column": "Дата", "y_columns": []}, "хотя бы один"),
    ],
)
async def test_несовместимые_параметры_отклоняются_словами(ctx, args, message):
    table_id = await _table(ctx)
    note = await _note(ctx)
    with pytest.raises(ToolError, match=message):
        await charts.insert_chart_block(ctx, {"item_id": str(note.id), "table_id": table_id, **args})


async def test_пузырьки_размер_и_серии_по_имени_без_учёта_регистра(ctx):
    table_id = await _table(ctx)
    note = await _note(ctx, content="")
    await charts.insert_chart_block(ctx, {
        "item_id": str(note.id), "table_id": table_id, "kind": "scatter",
        "x_column": "ДАТА", "y_columns": "значение", "size_column": "Значение", "series_column": "показатель",
    })
    await ctx.db.refresh(note)
    spec, = charts.find_charts(note.content)
    assert spec["kind"] == "scatter" and spec["size"] == spec["y"][0] and spec["series"]
    assert not note.content.startswith("\n"), "в пустой заметке блок — первой строкой"


def test_serialize_экранирует_подпись_и_разбирается_обратно():
    block = charts.serialize_chart("t1", "pie", "c1", ["c2"], title='Доли "A" & B')
    assert '"' not in block.split("data-title=")[1][1:-8]
    spec, = charts.find_charts(block)
    assert spec["title"] == 'Доли "A" & B' and spec["x"] == "c1" and spec["y"] == ["c2"]


async def test_describe_charts_переживает_удалённую_таблицу(ctx):
    block = charts.serialize_chart("00000000-0000-0000-0000-000000000000", "line", "x", ["y"])
    described = await charts.describe_charts(ctx.db, block)
    assert described[0]["table"] is None and "удалена" in described[0]["note"]


def test_инструмент_доступен_через_mcp_и_гасится_тумблером_таблиц():
    from app.routers.mcp import MCP_EXCLUDED_TOOLS

    assert "insert_chart_block" in {t.name for t in get_tool_definitions(set(MCP_EXCLUDED_TOOLS))}
    assert "insert_chart_block" in TOOL_GROUPS["tables"]
    assert "insert_chart_block" in _expand_disabled({"tables"})
