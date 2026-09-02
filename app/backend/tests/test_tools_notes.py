import uuid

import pytest

from app.core.config import get_settings
from app.tools.notes import (
    append_to_note,
    create_note,
    get_note,
    item_url,
    list_all_items,
    list_items_by_tag,
    list_items_in_folder,
)
from app.tools.registry import ToolContext, ToolError


def test_item_url_format():
    base_url = get_settings().public_base_url.rstrip("/")
    uid = uuid.uuid4()
    assert item_url(uid) == f"{base_url}/?item={uid}"


# --- Реальная жалоба: "не кликабельные ссылки от ассистента" -------------
# Модель придумывала несуществующую схему notenotes://<id> или вставляла
# голый id, потому что ни один тул не давал ей готовый URL — теперь дают.

async def test_create_note_includes_url(auth_client, db_session, test_user):
    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    result = await create_note(ctx, {"title": "T", "content": "C"})
    assert result["url"] == item_url(result["id"])


async def test_get_note_includes_url(auth_client, db_session, test_user):
    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    created = await create_note(ctx, {"title": "T", "content": "C"})
    result = await get_note(ctx, {"item_id": created["id"]})
    assert result["url"] == item_url(created["id"])


async def test_list_all_items_includes_url(auth_client, db_session, test_user):
    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    created = await create_note(ctx, {"title": "T", "content": "C"})
    result = await list_all_items(ctx, {})
    found = next(i for i in result["items"] if i["id"] == created["id"])
    assert found["url"] == item_url(created["id"])


async def test_list_items_in_folder_includes_url(auth_client, db_session, test_user):
    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    created = await create_note(ctx, {"title": "T", "content": "C"})
    result = await list_items_in_folder(ctx, {})
    found = next(i for i in result["items"] if i["id"] == created["id"])
    assert found["url"] == item_url(created["id"])


async def test_search_base_includes_url(auth_client, db_session, test_user):
    from app.tools.search_base import handle as search_base_handle

    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    created = await create_note(ctx, {"title": "Уникальныйзаголовок42", "content": "C"})

    result = await search_base_handle(ctx, {"query": "Уникальныйзаголовок42"})
    found = next(r for r in result["results"] if r["id"] == created["id"])
    assert found["url"] == item_url(created["id"])


async def test_list_items_by_tag_includes_url(auth_client, db_session, test_user):
    from app.tools.notes import add_tag

    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    created = await create_note(ctx, {"title": "T", "content": "C"})
    await add_tag(ctx, {"item_id": created["id"], "tag_name": "важное"})
    result = await list_items_by_tag(ctx, {"tag_name": "важное"})
    found = next(i for i in result["items"] if i["id"] == created["id"])
    assert found["url"] == item_url(created["id"])


# --- Реальная жалоба: модель вызвала append_to_note с параметром "content"
# (перепутав со схемой update_note), тул отдал "Пустой текст для
# добавления", а модель всё равно доложила пользователю "Готово" — ничего
# не добавив. append_to_note должен принимать оба имени параметра.

async def test_append_to_note_accepts_text_param(auth_client, db_session, test_user):
    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    created = await create_note(ctx, {"title": "T", "content": "Было"})
    result = await append_to_note(ctx, {"item_id": created["id"], "text": "Добавлено"})
    assert "Добавлено" in result["content"]


async def test_append_to_note_accepts_content_param_as_fallback(auth_client, db_session, test_user):
    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    created = await create_note(ctx, {"title": "T", "content": "Было"})
    result = await append_to_note(ctx, {"item_id": created["id"], "content": "Добавлено через content"})
    assert "Добавлено через content" in result["content"]


async def test_append_to_note_rejects_empty_both_params(auth_client, db_session, test_user):
    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    created = await create_note(ctx, {"title": "T", "content": "Было"})
    with pytest.raises(ToolError):
        await append_to_note(ctx, {"item_id": created["id"]})
