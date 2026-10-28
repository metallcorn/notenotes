"""Инструменты ассистента, добавленные 28.10 по сверке REST ↔ реестр:
пункты списков (правка/удаление), папки и теги, история версий, корзина,
архив. Данные вымышленные (Jan Kowalski).
"""

import uuid

import pytest
from sqlalchemy import select

from app.models import Folder, Item, ItemTag, ItemVersion, Tag, User
from app.security import hash_password
from app.tools.history import archive_note, list_trash, list_versions, restore_note, revert_version
from app.tools.lists import create_list, delete_list_entry, get_list, update_list_entry
from app.tools.notes import add_tag, create_note, delete_note, update_note
from app.tools.registry import ToolContext, ToolError, dispatch, get_tool_definitions
from app.tools.structure import delete_folder, delete_tag, merge_tag, remove_tag, rename_tag, update_folder


async def _space(auth_client, name="Dom"):
    return uuid.UUID((await auth_client.post("/api/spaces", json={"name": name})).json()["id"])


async def _folder(auth_client, space_id, name, parent_id=None):
    r = await auth_client.post("/api/folders", json={"space_id": str(space_id), "name": name, "parent_id": parent_id})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ctx(db_session, test_user, space_id):
    return ToolContext(db=db_session, user_id=test_user.id, space_id=space_id)


# --- пункты списков -------------------------------------------------------


async def test_update_and_delete_list_entry(auth_client, db_session, test_user):
    ctx = _ctx(db_session, test_user, await _space(auth_client))
    created = await create_list(ctx, {"title": "Zakupy", "entries": ["mleko", "chleb", "masło"]})
    list_id = created["id"]

    result = await update_list_entry(ctx, {"list_id": list_id, "text_match": "mleko", "text": "mleko 2 l"})
    assert result["was"] == "mleko" and result["text"] == "mleko 2 l"
    entries = (await get_list(ctx, {"list_id": list_id}))["entries"]
    assert [e["text"] for e in entries] == ["mleko 2 l", "chleb", "masło"]

    result = await delete_list_entry(ctx, {"list_id": list_id, "entry_id": entries[1]["id"]})
    assert result["deleted"] == "chleb" and result["entries_left"] == 2
    entries = (await get_list(ctx, {"list_id": list_id}))["entries"]
    assert [e["text"] for e in entries] == ["mleko 2 l", "masło"]
    # Снимки версий: по одному на правку и на удаление (плюс те, что оставил create_list).
    versions = (await db_session.execute(select(ItemVersion).where(ItemVersion.item_id == uuid.UUID(list_id)))).scalars().all()
    assert len(versions) >= 2


async def test_list_entry_match_is_strict_when_ambiguous(auth_client, db_session, test_user):
    ctx = _ctx(db_session, test_user, await _space(auth_client))
    created = await create_list(ctx, {"title": "Zakupy", "entries": ["mleko", "mleko kokosowe"]})
    with pytest.raises(ToolError, match="несколько пунктов"):
        await delete_list_entry(ctx, {"list_id": created["id"], "text_match": "mlek"})
    # Точное совпадение среди нескольких — однозначно.
    result = await delete_list_entry(ctx, {"list_id": created["id"], "text_match": "mleko"})
    assert result["deleted"] == "mleko"
    with pytest.raises(ToolError, match="get_list"):
        await update_list_entry(ctx, {"list_id": created["id"], "text_match": "ser", "text": "x"})
    with pytest.raises(ToolError, match="Пустой text"):
        await update_list_entry(ctx, {"list_id": created["id"], "text_match": "kokos", "text": " "})


# --- папки ----------------------------------------------------------------


async def test_update_folder_rename_nest_and_move_space(auth_client, db_session, test_user):
    home = await _space(auth_client, "Osobiste")
    family = await _space(auth_client, "Rodzinny")
    ctx = _ctx(db_session, test_user, home)
    parent_id = await _folder(auth_client, home, "Dokumenty")
    child_id = await _folder(auth_client, home, "Stare")
    note = await create_note(ctx, {"title": "Umowa", "content": "x", "folder_id": child_id})

    result = await update_folder(ctx, {"folder_id": child_id, "name": "Archiwalne", "parent_id": parent_id})
    assert result["changed"] == ["name", "parent_id"] and result["name"] == "Archiwalne" and result["parent_id"] == parent_id

    with pytest.raises(ToolError, match="подпапку"):
        await update_folder(ctx, {"folder_id": parent_id, "parent_id": child_id})

    result = await update_folder(ctx, {"folder_id": child_id, "parent_id": ""})
    assert result["parent_id"] is None

    result = await update_folder(ctx, {"folder_id": parent_id, "space": "rodzinny"})
    assert result["changed"] == ["space"] and result["space_id"] == str(family)

    # Перенос папки везёт заметки с собой.
    result = await update_folder(ctx, {"folder_id": child_id, "space": "Rodzinny"})
    assert result["space_id"] == str(family)
    moved = await db_session.get(Item, uuid.UUID(note["id"]))
    assert moved.space_id == family

    with pytest.raises(ToolError, match="Нечего менять"):
        await update_folder(ctx, {"folder_id": child_id})


async def test_delete_folder_only_when_empty(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    ctx = _ctx(db_session, test_user, space_id)
    folder_id = await _folder(auth_client, space_id, "Kot")
    sub_id = await _folder(auth_client, space_id, "Weterynarz", parent_id=folder_id)
    note = await create_note(ctx, {"title": "Szczepienia", "content": "x", "folder_id": folder_id})

    with pytest.raises(ToolError, match="заметок 1, подпапок 1"):
        await delete_folder(ctx, {"folder_id": folder_id})
    # В корзине — тоже содержимое: удаление папки не должно тихо выкинуть её из корзины в корень.
    await delete_note(ctx, {"item_id": note["id"]})
    with pytest.raises(ToolError, match="заметок 1"):
        await delete_folder(ctx, {"folder_id": folder_id})

    assert (await delete_folder(ctx, {"folder_id": sub_id}))["deleted"] == "Weterynarz"
    item = await db_session.get(Item, uuid.UUID(note["id"]))
    item.folder_id = None
    await db_session.commit()
    assert (await delete_folder(ctx, {"folder_id": folder_id}))["deleted"] == "Kot"
    assert await db_session.get(Folder, uuid.UUID(folder_id)) is None

    with pytest.raises(ToolError, match="list_folders"):
        await delete_folder(ctx, {"folder_id": "Kot"})


# --- теги -----------------------------------------------------------------


async def test_tags_remove_rename_merge_delete(auth_client, db_session, test_user):
    ctx = _ctx(db_session, test_user, await _space(auth_client))
    a = await create_note(ctx, {"title": "A", "content": "x"})
    b = await create_note(ctx, {"title": "B", "content": "x"})
    await add_tag(ctx, {"item_id": a["id"], "tag_name": "kot"})
    await add_tag(ctx, {"item_id": b["id"], "tag_name": "kot"})
    await add_tag(ctx, {"item_id": b["id"], "tag_name": "koty"})

    assert (await remove_tag(ctx, {"item_id": a["id"], "tag_name": "KOT"}))["removed"] is True
    assert (await remove_tag(ctx, {"item_id": a["id"], "tag_name": "kot"}))["removed"] is False

    with pytest.raises(ToolError, match="merge_tag"):
        await rename_tag(ctx, {"tag_name": "kot", "new_name": "koty"})
    assert await rename_tag(ctx, {"tag_name": "kot", "new_name": "kotek"}) == {"was": "kot", "name": "kotek"}

    result = await merge_tag(ctx, {"tag_name": "kotek", "into": "koty"})
    assert result == {"merged": "kotek", "into": "koty", "items_retagged": 0}
    names = {t.name for t in (await db_session.execute(select(Tag).where(Tag.user_id == test_user.id))).scalars()}
    assert names == {"koty"}
    links = (await db_session.execute(select(ItemTag).where(ItemTag.item_id == uuid.UUID(b["id"])))).scalars().all()
    assert len(links) == 1

    assert (await delete_tag(ctx, {"tag_name": "koty"}))["was_on_items"] == 1
    with pytest.raises(ToolError, match="list_tags"):
        await delete_tag(ctx, {"tag_name": "koty"})


async def test_tags_are_per_user(auth_client, db_session, test_user):
    ctx = _ctx(db_session, test_user, await _space(auth_client))
    other = User(username="inny", password_hash=hash_password("x"), name="Inny")
    db_session.add(other)
    await db_session.flush()
    db_session.add(Tag(user_id=other.id, name="sekret"))
    await db_session.commit()
    with pytest.raises(ToolError, match="нет"):
        await rename_tag(ctx, {"tag_name": "sekret", "new_name": "x"})


# --- история, корзина, архив -----------------------------------------------


async def test_versions_and_revert(auth_client, db_session, test_user):
    ctx = _ctx(db_session, test_user, await _space(auth_client))
    note = await create_note(ctx, {"title": "Plan", "content": "pierwsza wersja"})
    await update_note(ctx, {"item_id": note["id"], "content": "druga wersja"})
    await update_note(ctx, {"item_id": note["id"], "content": "trzecia wersja"})

    listed = await list_versions(ctx, {"item_id": note["id"]})
    assert listed["current_length"] == len("trzecia wersja")
    # Порядок не проверяем: в тестовой транзакции now() у всех версий один
    # и тот же (как в test_mcp), в проде каждая правка — своя транзакция.
    by_preview = {v["preview"]: v for v in listed["versions"]}
    assert set(by_preview) == {"pierwsza wersja", "druga wersja"}
    assert by_preview["druga wersja"]["author"] == test_user.name
    first = by_preview["pierwsza wersja"]["version_id"]
    assert (await list_versions(ctx, {"item_id": note["id"], "version_id": first}))["full_text"] == "pierwsza wersja"

    result = await revert_version(ctx, {"item_id": note["id"], "version_id": first})
    assert result["reverted"] is True
    item = await db_session.get(Item, uuid.UUID(note["id"]))
    assert item.content == "pierwsza wersja"
    # Откат обратим: текущее состояние легло в историю.
    listed = await list_versions(ctx, {"item_id": note["id"]})
    assert "trzecia wersja" in {v["preview"] for v in listed["versions"]}

    with pytest.raises(ToolError, match="не найдена"):
        await revert_version(ctx, {"item_id": note["id"], "version_id": str(uuid.uuid4())})


async def test_trash_restore_and_archive(auth_client, db_session, test_user):
    home = await _space(auth_client, "Osobiste")
    family = await _space(auth_client, "Rodzinny")
    ctx = _ctx(db_session, test_user, home)
    note = await create_note(ctx, {"title": "Paragon", "content": "x"})
    other = await create_note(ctx, {"title": "Inna", "content": "x", "space": "Rodzinny"})
    await delete_note(ctx, {"item_id": note["id"]})
    await delete_note(ctx, {"item_id": other["id"]})

    trash = await list_trash(ctx, {})
    assert {i["title"] for i in trash["items"]} == {"Paragon", "Inna"}
    assert [i["title"] for i in (await list_trash(ctx, {"space": "rodzinny"}))["items"]] == ["Inna"]

    assert (await restore_note(ctx, {"item_id": note["id"]}))["restored"] is True
    assert (await db_session.get(Item, uuid.UUID(note["id"]))).deleted_at is None
    with pytest.raises(ToolError, match="list_trash"):
        await restore_note(ctx, {"item_id": note["id"]})

    result = await archive_note(ctx, {"item_id": note["id"]})
    assert result["archived"] is True
    folder = await db_session.get(Folder, uuid.UUID(result["folder_id"]))
    assert folder.name == "Архив" and folder.space_id == home
    item = await db_session.get(Item, uuid.UUID(note["id"]))
    assert item.folder_id == folder.id


async def test_restore_is_scoped_to_members(auth_client, db_session, test_user):
    ctx = _ctx(db_session, test_user, await _space(auth_client))
    note = await create_note(ctx, {"title": "Paragon", "content": "x"})
    await delete_note(ctx, {"item_id": note["id"]})
    stranger = User(username="obcy", password_hash=hash_password("x"), name="Obcy")
    db_session.add(stranger)
    await db_session.commit()
    their = ToolContext(db=db_session, user_id=stranger.id, space_id=uuid.uuid4())
    assert (await list_trash(their, {}))["items"] == []
    with pytest.raises(ToolError, match="list_trash"):
        await restore_note(their, {"item_id": note["id"]})


# --- реестр ---------------------------------------------------------------


async def test_groups_toggle_as_one(auth_client, db_session, test_user):
    names = {d.name for d in get_tool_definitions()}
    new = {
        "update_list_entry", "delete_list_entry",
        "update_folder", "delete_folder", "remove_tag", "rename_tag", "merge_tag", "delete_tag",
        "list_versions", "revert_version", "list_trash", "restore_note", "archive_note",
    }
    assert new <= names
    without = {d.name for d in get_tool_definitions({"structure", "history"})}
    assert not (without & (new - {"update_list_entry", "delete_list_entry"}))
    assert {"update_list_entry", "delete_list_entry"} <= without
    ctx = _ctx(db_session, test_user, await _space(auth_client))
    assert "отключён" in (await dispatch("list_trash", ctx, {}, disabled={"history"}))["error"]
