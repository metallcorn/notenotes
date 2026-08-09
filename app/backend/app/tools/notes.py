from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from app import realtime
from app.deps import ensure_space_access
from app.llm.base import ToolDefinition
from app.models import Folder, Item, ItemTag, ItemVersion, Space, SpaceMember, Tag
from app.routers.items import create_item_row
from app.tools.registry import ToolContext, ToolError

# ТЗ §10a: "область контекста — все спейсы пользователя, та же логика, что
# у обычного поиска" — ассистент не должен быть слеп к спейсам, отличным от
# того, где идёт текущий диалог. Поэтому чтение/изменение существующих
# объектов проверяется через ensure_space_access (любой спейс пользователя),
# а не жёстким сравнением с ctx.space_id. Создание нового по умолчанию всё
# ещё идёт в текущий спейс диалога — если явно не указана папка из другого.


async def _resolve_folder(ctx: ToolContext, folder_id_raw: Any) -> tuple[uuid.UUID | None, uuid.UUID]:
    """Без folder_id — текущий спейс диалога. С folder_id — спейс папки,
    даже если это не тот же спейс, где идёт диалог (если пользователь там
    состоит)."""
    if not folder_id_raw:
        return None, ctx.space_id
    try:
        folder_id = uuid.UUID(str(folder_id_raw))
    except ValueError:
        raise ToolError(f"Некорректный id папки: {folder_id_raw}") from None
    folder = await ctx.db.get(Folder, folder_id)
    if folder is None:
        raise ToolError("Папка не найдена")
    try:
        await ensure_space_access(ctx.db, folder.space_id, ctx.user_id)
    except HTTPException:
        raise ToolError("Папка не найдена") from None
    return folder_id, folder.space_id


async def _get_item_cross_space(ctx: ToolContext, item_id_raw: Any) -> Item:
    try:
        item_id = uuid.UUID(str(item_id_raw))
    except (ValueError, TypeError):
        raise ToolError(f"Некорректный id заметки: {item_id_raw}") from None

    item = await ctx.db.get(Item, item_id)
    if item is None or item.deleted_at is not None:
        raise ToolError("Заметка не найдена")
    try:
        await ensure_space_access(ctx.db, item.space_id, ctx.user_id)
    except HTTPException:
        raise ToolError("Заметка не найдена") from None
    return item


CREATE_NOTE = ToolDefinition(
    name="create_note",
    description=(
        "Создать новую заметку. Содержимое — в формате Markdown. Без folder_id создаётся в "
        "текущем спейсе диалога; с folder_id — в том спейсе, которому принадлежит папка "
        "(может быть другой спейс пользователя, не только текущий)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Заголовок заметки"},
            "content": {"type": "string", "description": "Содержимое в Markdown"},
            "folder_id": {"type": "string", "description": "id папки; не указывать — заметка в корне текущего спейса"},
        },
        "required": ["title", "content"],
    },
)


async def create_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    content = str(args.get("content", ""))
    folder_id, space_id = await _resolve_folder(ctx, args.get("folder_id"))

    item = await create_item_row(
        ctx.db,
        space_id=space_id,
        author_id=ctx.user_id,
        material_type="note",
        title=title,
        content=content,
        folder_id=folder_id,
    )
    space = await ctx.db.get(Space, item.space_id)
    return {"id": str(item.id), "title": item.title, "space_id": str(item.space_id), "space_name": space.name if space else ""}


GET_NOTE = ToolDefinition(
    name="get_note",
    description=(
        "Прочитать ПОЛНОЕ содержимое заметки по id (search_base и list_all_items дают только "
        "название или обрезанный отрывок в 300 символов — этого недостаточно, если в заметке "
        "таблица, список пунктов или любой текст длиннее пары предложений). Вызывай это перед "
        "тем, как отвечать на вопрос по содержимому конкретной заметки — НИКОГДА не придумывай "
        "содержимое самостоятельно и не притворяйся, что прочитал заметку, если не вызвал этот тул."
    ),
    parameters={
        "type": "object",
        "properties": {"item_id": {"type": "string"}},
        "required": ["item_id"],
    },
)


async def get_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    if item.material_type not in ("note", "ticket"):
        raise ToolError("Это не заметка (возможно, список — используй get_list)")
    result: dict[str, Any] = {"id": str(item.id), "title": item.title, "content": item.content}
    if item.material_type == "ticket":
        # content для билета — почти только служебный <div
        # data-ticket-attachment ...> (сам текст полностью заменяется
        # карточкой при распознавании, см. tickets.py) — моделью не
        # читается осмысленно. properties — уже готовые чистые поля
        # (тип, дата/время, откуда-куда, место), их и возвращаем как
        # основной источник ответа.
        result["material_type"] = "ticket"
        result["properties"] = item.properties
    return result


UPDATE_NOTE = ToolDefinition(
    name="update_note",
    description="Изменить заголовок и/или содержимое существующей заметки. Незаданные поля не меняются.",
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["item_id"],
    },
)


async def update_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    new_title = args.get("title")
    new_content = args.get("content")

    content_changed = (new_title is not None and new_title != item.title) or (
        new_content is not None and new_content != item.content
    )
    if content_changed:
        # Версия сохраняется и здесь: правки ассистента должны быть
        # откатываемы точно так же, как ручные (CLAUDE.md — история версий
        # обязательна, а не опциональна).
        ctx.db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=ctx.user_id))

    if new_title is not None:
        item.title = str(new_title)
    if new_content is not None:
        item.content = str(new_content)

    await ctx.db.commit()
    await ctx.db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    return {"id": str(item.id), "title": item.title}


DELETE_NOTE = ToolDefinition(
    name="delete_note",
    description="Удалить заметку. Перемещается в корзину — не безвозвратно, пользователь может восстановить.",
    parameters={
        "type": "object",
        "properties": {"item_id": {"type": "string"}},
        "required": ["item_id"],
    },
)


async def delete_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    item.deleted_at = datetime.now(timezone.utc)
    await ctx.db.commit()
    await realtime.notify_space(item.space_id, "items")
    return {"id": str(item.id), "deleted": True}


ADD_TAG = ToolDefinition(
    name="add_tag",
    description="Добавить тег к заметке. Если тега с таким именем ещё нет у пользователя — он создаётся.",
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "tag_name": {"type": "string"},
        },
        "required": ["item_id", "tag_name"],
    },
)


async def add_tag(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    tag_name = str(args.get("tag_name", "")).strip()
    if not tag_name:
        raise ToolError("Имя тега не может быть пустым")

    existing = await ctx.db.execute(select(Tag).where(Tag.user_id == ctx.user_id, Tag.name == tag_name))
    tag = existing.scalar_one_or_none()
    if tag is None:
        tag = Tag(user_id=ctx.user_id, name=tag_name)
        ctx.db.add(tag)
        await ctx.db.flush()

    link_existing = await ctx.db.execute(
        select(ItemTag).where(ItemTag.item_id == item.id, ItemTag.tag_id == tag.id, ItemTag.user_id == ctx.user_id)
    )
    if link_existing.scalar_one_or_none() is None:
        ctx.db.add(ItemTag(item_id=item.id, tag_id=tag.id, user_id=ctx.user_id))

    await ctx.db.commit()
    await realtime.notify_space(item.space_id, "items")
    return {"item_id": str(item.id), "tag": tag_name}


LIST_FOLDERS = ToolDefinition(
    name="list_folders",
    description="Список папок пользователя во всех его спейсах — чтобы понимать, куда раскладывать заметки.",
    parameters={"type": "object", "properties": {}},
)


async def list_folders(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.db.execute(
        select(Folder, Space.name)
        .join(Space, Space.id == Folder.space_id)
        .join(SpaceMember, SpaceMember.space_id == Folder.space_id)
        .where(SpaceMember.user_id == ctx.user_id)
    )
    return {
        "folders": [
            {
                "id": str(folder.id),
                "name": folder.name,
                "parent_id": str(folder.parent_id) if folder.parent_id else None,
                "space_id": str(folder.space_id),
                "space_name": space_name,
            }
            for folder, space_name in result.all()
        ]
    }


CREATE_FOLDER = ToolDefinition(
    name="create_folder",
    description=(
        "Создать новую папку. Без parent_id — в корне текущего спейса диалога; с parent_id — "
        "вложенная папка (должна принадлежать тому же спейсу, где создаётся). Используй это, "
        "когда пользователь просит разложить заметки по папкам, а не только предполагай, что "
        "папка уже есть — сначала list_folders, и только если её правда нет, создавай."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Название папки"},
            "parent_id": {"type": "string", "description": "id родительской папки; не указывать — папка в корне"},
        },
        "required": ["name"],
    },
)


async def create_folder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name", "")).strip()
    if not name:
        raise ToolError("Название папки не может быть пустым")

    parent_id_raw = args.get("parent_id")
    parent_id: uuid.UUID | None = None
    if parent_id_raw:
        try:
            parent_id = uuid.UUID(str(parent_id_raw))
        except ValueError:
            raise ToolError(f"Некорректный id родительской папки: {parent_id_raw}") from None
        parent = await ctx.db.get(Folder, parent_id)
        if parent is None or parent.space_id != ctx.space_id:
            raise ToolError("Родительская папка не найдена в текущем спейсе")

    folder = Folder(space_id=ctx.space_id, parent_id=parent_id, name=name)
    ctx.db.add(folder)
    await ctx.db.commit()
    await ctx.db.refresh(folder)
    await realtime.notify_space(folder.space_id, "folders")
    return {"id": str(folder.id), "name": folder.name, "space_id": str(folder.space_id)}


LIST_ITEMS_IN_FOLDER = ToolDefinition(
    name="list_items_in_folder",
    description=(
        "Посмотреть, какие заметки и списки лежат в конкретной папке (включая пустоту) — "
        "используй перед тем, как предполагать, что там что-то есть или нет, вместо угадывания. "
        "Без folder_id — корень текущего спейса диалога."
    ),
    parameters={
        "type": "object",
        "properties": {
            "folder_id": {"type": "string", "description": "id папки (из list_folders); не указывать — корень текущего спейса"}
        },
    },
)


async def list_items_in_folder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    folder_id, space_id = await _resolve_folder(ctx, args.get("folder_id"))

    query = select(Item).where(
        Item.space_id == space_id, Item.material_type.in_(("note", "list", "ticket")), Item.deleted_at.is_(None)
    )
    query = query.where(Item.folder_id == folder_id) if folder_id else query.where(Item.folder_id.is_(None))
    items = (await ctx.db.execute(query)).scalars().all()
    return {"items": [{"id": str(i.id), "title": i.title, "material_type": i.material_type} for i in items]}


LIST_TAGS = ToolDefinition(
    name="list_tags",
    description="Список тегов пользователя.",
    parameters={"type": "object", "properties": {}},
)


async def list_tags(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.db.execute(select(Tag).where(Tag.user_id == ctx.user_id).order_by(Tag.name))
    tags = result.scalars().all()
    return {"tags": [t.name for t in tags]}


LIST_ITEMS_BY_TAG = ToolDefinition(
    name="list_items_by_tag",
    description=(
        "Показать заметки/списки/билеты, помеченные конкретным тегом пользователя (тег — из "
        "list_tags). Используй это, а не только полнотекстовый поиск, когда ищешь что-то по общей "
        "теме, а не по точному слову — пользователь мог заранее разложить заметки по тегам "
        "(например 'здоровье', 'работа'), и это точнее и надёжнее, чем гадать формулировки для "
        "search_base. Реальный случай: искали 'больницы' одним словом мимо тега 'здоровье', под "
        "которым уже была нужная заметка — если по теме есть похожий тег, проверь его в первую "
        "очередь, до серии вариаций полнотекстового запроса."
    ),
    parameters={
        "type": "object",
        "properties": {"tag_name": {"type": "string", "description": "Название тега, как в list_tags"}},
        "required": ["tag_name"],
    },
)


async def list_items_by_tag(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    tag_name = str(args.get("tag_name", "")).strip()
    if not tag_name:
        raise ToolError("tag_name обязателен")

    tag = (
        await ctx.db.execute(
            select(Tag).where(Tag.user_id == ctx.user_id, func.lower(Tag.name) == tag_name.lower())
        )
    ).scalar_one_or_none()
    if tag is None:
        return {"items": [], "error": f"Тег «{tag_name}» не найден — проверь точное название через list_tags"}

    result = await ctx.db.execute(
        select(Item, Space.name)
        .join(ItemTag, ItemTag.item_id == Item.id)
        .join(Space, Space.id == Item.space_id)
        .where(
            ItemTag.tag_id == tag.id,
            ItemTag.user_id == ctx.user_id,
            Item.material_type.in_(("note", "list", "ticket")),
            Item.deleted_at.is_(None),
        )
        .order_by(Item.updated_at.desc())
    )
    return {
        "items": [
            {"id": str(i.id), "title": i.title, "material_type": i.material_type, "space_name": space_name}
            for i, space_name in result.all()
        ]
    }


LIST_ALL_ITEMS = ToolDefinition(
    name="list_all_items",
    description=(
        "Показать заголовки ВСЕХ заметок и списков пользователя во всех его спейсах (без "
        "содержимого — только title/id/тип/спейс). Используй, когда search_base по ключевым "
        "словам ничего не находит, но объект скорее всего есть под другим словом — полнотекстовый "
        "поиск не понимает, что 'закупка', 'покупки' и 'купить' связаны по смыслу (это разные "
        "приставочные формы, не варианты одного слова), а ты понимаешь. Просмотри заголовки сам "
        "и оцени, что подходит по смыслу, вместо того чтобы сообщать, что ничего не нашлось."
    ),
    parameters={"type": "object", "properties": {}},
)


async def list_all_items(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.db.execute(
        select(Item, Space.name)
        .join(Space, Space.id == Item.space_id)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .where(
            SpaceMember.user_id == ctx.user_id,
            Item.material_type.in_(("note", "list", "ticket")),
            Item.deleted_at.is_(None),
        )
        .order_by(Item.updated_at.desc())
        .limit(200)
    )
    return {
        "items": [
            {
                "id": str(item.id),
                "title": item.title,
                "material_type": item.material_type,
                "space_id": str(item.space_id),
                "space_name": space_name,
            }
            for item, space_name in result.all()
        ]
    }
