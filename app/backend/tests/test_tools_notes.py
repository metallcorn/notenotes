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


async def test_list_all_items_отдаёт_id_а_за_ссылкой_посылает_к_get_note(auth_client, db_session, test_user):
    """Раньше здесь проверялось наличие url — его убрали 10.10 осознанно.

    Причина: при 263 записях перечисление с url и space_id занимало
    57 850 символов, обрезалось по потолку (30 000), и модель видела
    половину базы, не зная об этом. url — 70 символов на запись и в
    перечислении не нужен: по id вызывается get_note, и ссылка приходит
    оттуда.

    Инвариант «не выдумывай ссылку» при этом остаётся закрытым: он держится
    на том, что ссылка берётся ИЗ РЕЗУЛЬТАТА тула, а не собирается из id.
    Поэтому id здесь обязателен, а в самом результате прямо написано, где
    брать ссылку (тесты ниже).
    """
    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    created = await create_note(ctx, {"title": "T", "content": "C"})
    result = await list_all_items(ctx, {})
    found = next(i for i in result["items"] if i["id"] == created["id"])
    assert "url" not in found
    assert "get_note" in result["ссылок_здесь_нет"]
    # Остальные тулы url отдают по-прежнему — проверено тестами выше/ниже.
    assert item_url(created["id"])


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


# --- Реальная жалоба: append_to_note вызвали на id ТАБЛИЦЫ — тул тихо
# дописал markdown-текст в неиспользуемое поле content этого item'а
# (таблица рендерится из properties.columns/rows, не из content), тул
# отрапортовал успех, а визуально ничего не изменилось. get_note уже
# проверял material_type — update_note/append_to_note той же проверки не
# имели вообще.

async def test_append_to_note_rejects_table_item(auth_client, db_session, test_user):
    from app.tools.tables import create_table

    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    table = await create_table(ctx, {"title": "Таблица", "columns": ["A"]})
    with pytest.raises(ToolError):
        await append_to_note(ctx, {"item_id": table["id"], "text": "мусор"})


async def test_update_note_rejects_table_item(auth_client, db_session, test_user):
    from app.tools.notes import update_note
    from app.tools.tables import create_table

    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    table = await create_table(ctx, {"title": "Таблица", "columns": ["A"]})
    with pytest.raises(ToolError):
        await update_note(ctx, {"item_id": table["id"], "content": "мусор"})


async def test_get_note_rejects_list_item(auth_client, db_session, test_user):
    from app.tools.lists import create_list

    space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    lst = await create_list(ctx, {"title": "Список"})
    with pytest.raises(ToolError):
        await get_note(ctx, {"item_id": lst["id"]})


class TestПеречислениеВлезаетВКонтекст:
    """Нашла самопроверка на первом же прогоне: при лимите 200 и полях с
    url и space_id результат list_all_items вырастал до 57 850 символов —
    больше потолка на один результат (30 000), то есть обрезался. На
    «просмотри заголовки сам» модель видела ПОЛОВИНУ базы, не зная об
    этом, и честно отвечала «не нашёл»."""

    async def test_результат_никогда_не_перерастает_потолок(self, db_session, test_user):
        import json
        from types import SimpleNamespace

        from app.dialog_tool_window import MAX_RESULT_CHARS
        from app.models import Item, Space, SpaceMember
        from app.tools import notes

        space = Space(name="Личное", owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
        for i in range(260):
            db_session.add(Item(
                space_id=space.id, author_id=test_user.id, material_type="note",
                # Длинные названия — так в живой базе и бывает
                # («🐕 Marsz Kejterka уже в эту субботу в Познани»).
                title=f"Заметка номер {i} с довольно длинным названием про Познань",
                content="", properties={},
            ))
        await db_session.commit()
        ctx = SimpleNamespace(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="UTC")

        result = await notes.list_all_items(ctx, {})
        size = len(json.dumps(result, ensure_ascii=False))

        assert size < MAX_RESULT_CHARS, f"{size} символов — обрежется и модель не узнает"
        assert result["items"], "хоть что-то показать надо"
        assert "из 260" in result["показано"]

    async def test_про_неполноту_сказано_честно(self, db_session, test_user):
        """Обрезали по лимиту — модель должна об этом знать, иначе скажет
        «в базе этого нет»."""
        from types import SimpleNamespace

        from app.models import Item, Space, SpaceMember
        from app.tools import notes

        space = Space(name="Личное", owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
        # Коротких названий влезает больше — именно поэтому бюджет в
        # символах, а не в числе записей.
        for i in range(400):
            db_session.add(Item(space_id=space.id, author_id=test_user.id, material_type="note",
                                title=f"З{i}", content="", properties={}))
        await db_session.commit()
        ctx = SimpleNamespace(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="UTC")

        result = await notes.list_all_items(ctx, {})

        assert "Перечисление неполное" in result["примечание"]
        # И главное — чем это НЕ является: «здесь нет» ≠ «в базе нет».
        assert "НЕ значит, что его нет в базе" in result["примечание"]

    async def test_ссылок_нет_но_про_это_сказано(self, db_session, test_user):
        """Убрать url молча нельзя: выдумывание ссылок — реальный баг
        («notenotes://<id>»). Поэтому прямо в результате написано, где
        брать ссылку."""
        from types import SimpleNamespace

        from app.models import Item, Space, SpaceMember
        from app.tools import notes

        space = Space(name="Личное", owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
        db_session.add(Item(space_id=space.id, author_id=test_user.id, material_type="note",
                            title="Одна", content="", properties={}))
        await db_session.commit()
        ctx = SimpleNamespace(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="UTC")

        result = await notes.list_all_items(ctx, {})

        assert "url" not in result["items"][0]
        assert "get_note" in result["ссылок_здесь_нет"]
        # id остаётся — без него не вызвать get_note.
        assert result["items"][0]["id"]

    async def test_короткие_названия_влезают_числом_больше(self, db_session, test_user):
        """Главный довод за бюджет в символах: число записей размером не
        управляет. С названиями по пять символов их влезает кратно
        больше, чем с живыми вроде «🐕 Marsz Kejterka уже в субботу»."""
        from types import SimpleNamespace

        from app.models import Item, Space, SpaceMember
        from app.tools import notes

        space = Space(name="S", owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
        for i in range(400):
            db_session.add(Item(space_id=space.id, author_id=test_user.id, material_type="note",
                                title=f"З{i}", content="", properties={}))
        await db_session.commit()
        ctx = SimpleNamespace(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="UTC")

        short = await notes.list_all_items(ctx, {})

        for item in (await db_session.execute(__import__("sqlalchemy").select(Item))).scalars().all():
            item.title = item.title + " с довольно длинным названием про Познань и документы"
        await db_session.commit()
        long = await notes.list_all_items(ctx, {})

        assert len(short["items"]) > len(long["items"])
