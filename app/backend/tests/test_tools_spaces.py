"""Ассистент кладёт и переносит заметки в спейс, который назвал человек.

Живой случай 19.10 (Telegram): «сделай заметку в семейном» — трижды
подряд заметка ложилась в спейс бота, папка в «Семейном» восемь раз не
создалась («родительская папка не найдена»), а «перенесла» оказалось
неправдой: update_note молча проглотил folder_id, которого у него не было.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import Folder, Item, Space, SpaceMember, Upload
from app.tools.lists import create_list
from app.tools.notes import create_folder, create_note, list_folders, update_note
from app.tools.registry import ToolContext, ToolError, dispatch


@pytest_asyncio.fixture
async def spaces(db_session, test_user):
    made = {}
    for name in ("Telegram", "Семейный", "Личное"):
        sp = Space(name=name, owner_id=test_user.id)
        db_session.add(sp)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=sp.id, user_id=test_user.id))
        made[name] = sp
    vault = Space(name="Сейф", owner_id=test_user.id, is_vault=True)
    db_session.add(vault)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=vault.id, user_id=test_user.id))
    made["Сейф"] = vault
    await db_session.commit()
    return made


def _ctx(db_session, test_user, spaces):
    return ToolContext(db=db_session, user_id=test_user.id, space_id=spaces["Telegram"].id)


async def test_заметка_в_спейсе_по_названию_в_падеже(db_session, test_user, spaces):
    result = await create_note(
        _ctx(db_session, test_user, spaces), {"title": "План поездки", "content": "x", "space": "в семейном спейсе"}
    )

    assert result["space_name"] == "Семейный"


async def test_без_спейса_как_раньше(db_session, test_user, spaces):
    result = await create_note(_ctx(db_session, test_user, spaces), {"title": "T", "content": "x"})

    assert result["space_name"] == "Telegram"


async def test_несуществующий_спейс_называет_настоящие(db_session, test_user, spaces):
    with pytest.raises(ToolError) as e:
        await create_note(_ctx(db_session, test_user, spaces), {"title": "T", "content": "x", "space": "Работа"})

    assert "«Семейный»" in str(e.value) and "Сейф" not in str(e.value)


async def test_сейф_не_находится(db_session, test_user, spaces):
    with pytest.raises(ToolError):
        await create_note(_ctx(db_session, test_user, spaces), {"title": "T", "content": "x", "space": "Сейф"})


async def test_подпапка_в_чужом_для_диалога_спейсе(db_session, test_user, spaces):
    """Ровно то, на чём ассистент споткнулся восемь раз подряд."""
    parent = Folder(space_id=spaces["Семейный"].id, name="Квартира")
    db_session.add(parent)
    await db_session.commit()

    result = await create_folder(
        _ctx(db_session, test_user, spaces), {"name": "Поездки", "parent_id": str(parent.id)}
    )

    assert result["space_name"] == "Семейный"


async def test_папка_в_корне_названного_спейса(db_session, test_user, spaces):
    result = await create_folder(_ctx(db_session, test_user, spaces), {"name": "Поездки", "space": "Семейный"})

    assert result["space_id"] == str(spaces["Семейный"].id)


async def test_список_в_названном_спейсе(db_session, test_user, spaces):
    result = await create_list(_ctx(db_session, test_user, spaces), {"title": "Покупки", "space": "семейный"})

    item = await db_session.get(Item, uuid.UUID(result["id"]))
    assert item.space_id == spaces["Семейный"].id


async def test_перенос_заметки_с_файлом_в_папку_другого_спейса(db_session, test_user, spaces):
    ctx = _ctx(db_session, test_user, spaces)
    upload = Upload(
        space_id=spaces["Telegram"].id, author_id=test_user.id, filename="plan.pdf",
        content_type="application/pdf",
    )
    db_session.add(upload)
    folder = Folder(space_id=spaces["Семейный"].id, name="Поездка")
    db_session.add(folder)
    await db_session.flush()
    created = await create_note(
        ctx, {"title": "План", "content": f'<a data-url="/api/uploads/{upload.id}/file">plan.pdf</a>'}
    )

    result = await update_note(ctx, {"item_id": created["id"], "folder_id": str(folder.id)})

    item = await db_session.get(Item, uuid.UUID(created["id"]))
    assert item.space_id == spaces["Семейный"].id and item.folder_id == folder.id
    assert result["folder_name"] == "Поездка"
    await db_session.refresh(upload)
    assert upload.space_id == spaces["Семейный"].id
    copies = (await db_session.execute(select(Item).where(Item.title == "План"))).scalars().all()
    assert len(copies) == 1


async def test_перенос_списка_в_спейс(db_session, test_user, spaces):
    ctx = _ctx(db_session, test_user, spaces)
    created = await create_list(ctx, {"title": "Покупки"})

    await update_note(ctx, {"item_id": created["id"], "space": "Семейный"})

    item = await db_session.get(Item, uuid.UUID(created["id"]))
    assert item.space_id == spaces["Семейный"].id


async def test_папка_не_из_того_спейса(db_session, test_user, spaces):
    folder = Folder(space_id=spaces["Личное"].id, name="Разное")
    db_session.add(folder)
    await db_session.commit()

    with pytest.raises(ToolError):
        await create_note(
            _ctx(db_session, test_user, spaces),
            {"title": "T", "content": "x", "folder_id": str(folder.id), "space": "Семейный"},
        )


async def test_спейс_без_папок_виден(db_session, test_user, spaces):
    result = await list_folders(_ctx(db_session, test_user, spaces), {})

    names = {s["name"] for s in result["spaces"]}
    assert {"Telegram", "Семейный", "Личное"} <= names and "Сейф" not in names


async def test_лишний_аргумент_не_проглатывается_молча(db_session, test_user, spaces):
    ctx = _ctx(db_session, test_user, spaces)
    created = await create_note(ctx, {"title": "T", "content": "x"})

    result = await dispatch("append_to_note", ctx, {"item_id": created["id"], "text": "y", "folder": "Поездки"})

    assert "folder" in result["warning"] and "НЕ применены" in result["warning"]
