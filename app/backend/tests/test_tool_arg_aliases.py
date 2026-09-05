"""Тулы принимают синоним имени параметра, если он расходится с соседями.

Реальный случай (замер 2026-09-05, воскресный ужин, оценка 1/5): модель
дважды подряд вызвала create_folder({"title": "Рецепты"}) и дважды
получила «Название папки не может быть пустым» — при том что название она
передала. Диалог после этого развалился: ни рецепта, ни списка покупок,
ни напоминания.

Ошибка не в модели. create_note, create_table и create_calendar_event
ждут "title", а create_folder — "name", и он выбивается из ряда
единственный. Обобщать по трём соседним тулам — разумное поведение, так
что чинится схема, а не модель. Тот же приём уже применён в
append_to_note (text/content).
"""

import uuid

import pytest

from app.tools.notes import create_folder
from app.tools.registry import ToolContext, ToolError


async def _space(auth_client) -> str:
    r = await auth_client.post("/api/spaces", json={"name": "Space"})
    return r.json()["id"]


@pytest.mark.parametrize("key", ["name", "title"])
async def test_create_folder_accepts_both_name_and_title(auth_client, db_session, test_user, key):
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(await _space(auth_client)))
    result = await create_folder(ctx, {key: "Рецепты"})
    assert result["name"] == "Рецепты"


async def test_create_folder_still_rejects_truly_empty(auth_client, db_session, test_user):
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(await _space(auth_client)))
    with pytest.raises(ToolError) as exc:
        await create_folder(ctx, {})
    # Сообщение по-прежнему подсказывает, что делать (см. test_tool_error_hints).
    assert "—" in str(exc.value)
