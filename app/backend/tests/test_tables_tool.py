"""Инструменты таблиц у ассистента.

Оба проверяемых здесь дефекта найдены на боевой базе 07.10, в диалоге
«Тренировки», куда владелец два месяца записывал подходы.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Item, Space, SpaceMember
from app.tools import tables
from app.tools.registry import ToolContext, ToolError


@pytest.fixture
async def ctx(db_session, test_user):
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()
    return ToolContext(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="Europe/Warsaw")


async def _table(ctx) -> str:
    out = await tables.create_table(ctx, {
        "title": "Таблица тренировок",
        "columns": ["Дата", "Упражнение", "Подходы (вес × повторения)"],
    })
    return out["id"]


class TestIdНовойСтроки:
    """Главный дефект: add_table_row не возвращал row_id, а
    update_table_row адресует строку только по id. Модель не знала id
    строки, которую сама же создала, — и на каждое «ещё подход» выходило
    update_table_row с выдуманным id → «Строка не найдена» → get_table
    (дамп всей таблицы, ~9 300 симв.) → повтор. Четырнадцать таких циклов
    в одном диалоге."""

    async def test_add_table_row_возвращает_row_id(self, ctx):
        table_id = await _table(ctx)

        out = await tables.add_table_row(ctx, {
            "table_id": table_id,
            "cells": {"Дата": "2026-10-07", "Упражнение": "Армейский жим"},
        })

        assert "row_id" in out, "без row_id модель обязана звать get_table ради собственной строки"

    async def test_этим_id_строка_сразу_меняется_без_get_table(self, ctx):
        """Именно то, чего не хватало: добавить и дописать — два вызова, а
        не пять."""
        table_id = await _table(ctx)
        added = await tables.add_table_row(ctx, {
            "table_id": table_id,
            "cells": {"Упражнение": "Армейский жим", "Подходы (вес × повторения)": "1: 16 кг × 10"},
        })

        updated = await tables.update_table_row(ctx, {
            "table_id": table_id,
            "row_id": added["row_id"],
            "cells": {"Подходы (вес × повторения)": "1: 16 кг × 10\n2: 18 кг × 10"},
        })

        assert updated["cells"]["Подходы (вес × повторения)"].endswith("2: 18 кг × 10")

    async def test_выдуманный_id_по_прежнему_отвергается(self, ctx):
        table_id = await _table(ctx)
        await tables.add_table_row(ctx, {"table_id": table_id, "cells": {"Упражнение": "Жим"}})

        with pytest.raises(ToolError) as e:
            await tables.update_table_row(ctx, {
                "table_id": table_id,
                "row_id": "11111111-1111-1111-1111-111111111111",
                "cells": {"Упражнение": "Другое"},
            })

        assert "get_table" in str(e.value)

    async def test_каждая_строка_со_своим_id(self, ctx):
        table_id = await _table(ctx)

        first = await tables.add_table_row(ctx, {"table_id": table_id, "cells": {"Упражнение": "Тяга"}})
        second = await tables.add_table_row(ctx, {"table_id": table_id, "cells": {"Упражнение": "Жим"}})

        assert first["row_id"] != second["row_id"]
        rows = (await tables.get_table(ctx, {"table_id": table_id}))["rows"]
        assert {r["id"] for r in rows} == {first["row_id"], second["row_id"]}


class TestРазметкаВЯчейках:
    """Второй дефект: ячейка рендерится плоским текстом (TableGrid.tsx),
    а модель выделяла жирным только что дописанный подход — и в данные
    уезжало буквальное «**2: 7 кг × 8**». На боевой базе так было
    испорчено 21 строка из 35, всегда последний подход, и именно это
    ломало «нормально найти и статистику собрать»."""

    async def test_жирное_не_попадает_в_ячейку(self, ctx):
        table_id = await _table(ctx)

        out = await tables.add_table_row(ctx, {
            "table_id": table_id,
            "cells": {"Подходы (вес × повторения)": "1: 7 кг × 8\n**2: 7 кг × 8 (на руку)**"},
        })

        assert out["cells"]["Подходы (вес × повторения)"] == "1: 7 кг × 8\n2: 7 кг × 8 (на руку)"

    async def test_и_при_изменении_строки(self, ctx):
        table_id = await _table(ctx)
        added = await tables.add_table_row(ctx, {"table_id": table_id, "cells": {"Упражнение": "Жим"}})

        out = await tables.update_table_row(ctx, {
            "table_id": table_id,
            "row_id": added["row_id"],
            "cells": {"Упражнение": "**Армейский жим**"},
        })

        assert out["cells"]["Упражнение"] == "Армейский жим"

    async def test_и_при_создании_таблицы_сразу_со_строками(self, ctx):
        out = await tables.create_table(ctx, {
            "title": "Расходы",
            "columns": ["Что"],
            "rows": [{"Что": "*молоко*"}],
        })

        item = (await ctx.db.execute(select(Item).where(Item.id == out["id"]))).scalar_one()
        assert list(item.properties["rows"][0]["cells"].values()) == ["молоко"]

    async def test_курсив_и_вложенное(self, ctx):
        table_id = await _table(ctx)

        out = await tables.add_table_row(ctx, {
            "table_id": table_id,
            "cells": {"Упражнение": "**_Жим_** и *тяга*"},
        })

        assert out["cells"]["Упражнение"] == "Жим и тяга"

    @pytest.mark.parametrize("value", [
        "2 * 3 = 6",            # умножение, не разметка
        "60 кг × 8",            # обычные данные
        "snake_case_name",      # подчёркивание внутри слова значимо
        "id_строки",
        "вес * 2",
        "**",                   # одинокие маркеры без содержимого
        "",
    ])
    async def test_не_трогает_осмысленный_текст(self, ctx, value):
        """Снимать разметку нельзя жадно: в ячейках живут и звёздочки как
        умножение, и подчёркивания внутри идентификаторов."""
        table_id = await _table(ctx)

        out = await tables.add_table_row(ctx, {"table_id": table_id, "cells": {"Упражнение": value}})

        assert out["cells"]["Упражнение"] == value

    async def test_чистая_функция_отдельно(self):
        assert tables.strip_emphasis("**жирно**") == "жирно"
        assert tables.strip_emphasis("ничего особенного") == "ничего особенного"
        assert tables.strip_emphasis("a*b*c") == "a*b*c"
