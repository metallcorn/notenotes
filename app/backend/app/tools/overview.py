"""Инструменты-обзоры: что ссылается на заметку, что правили недавно,
все документы одним списком.

Это те же выборки, что у экранов «Активность», «Документы» и панели
обратных ссылок в вебе (routers/items.py, routers/documents.py) — через
ассистента и MCP до 28.10 их не было, хотя «что я трогал на неделе» и
«какие документы за июль пришли» — обычные вопросы к базе. Обработчик
документов переиспользуется как функция: там серии (ежемесячные
документы с пропусками) считаются отдельным модулем, повторять не надо.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.llm.base import ToolDefinition
from app.models import Item, Space, SpaceMember, User
from app.routers.documents import list_documents as _list_documents
from app.tools.notes import _get_item_cross_space, item_url
from app.tools.registry import ToolContext, ToolError

LIST_BACKLINKS = ToolDefinition(
    name="list_backlinks",
    description=(
        "Заметки, которые ссылаются НА эту заметку (обратные ссылки). Используй на «откуда на это "
        "ссылаются», «что связано с этой заметкой», перед удалением заметки — чтобы предупредить, "
        "что ссылки осиротеют."
    ),
    parameters={"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]},
)


async def list_backlinks(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    rows = (
        await ctx.db.execute(
            select(Item, Space.name)
            .join(SpaceMember, SpaceMember.space_id == Item.space_id)
            .join(Space, Space.id == Item.space_id)
            .where(
                SpaceMember.user_id == ctx.user_id,
                Space.is_vault.is_(False),
                Item.deleted_at.is_(None),
                Item.id != item.id,
                Item.content.like(f"%{item.id}%"),
            )
            .order_by(Item.updated_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "item_id": str(item.id),
        "title": item.title,
        "backlinks": [
            {"id": str(i.id), "title": i.title, "material_type": i.material_type, "space_name": space_name, "url": item_url(i.id)}
            for i, space_name in rows
        ],
    }


LIST_RECENT = ToolDefinition(
    name="list_recent",
    description=(
        "Что правили последним — заметки, списки, таблицы и рутины по всем спейсам, самые свежие "
        "сверху, с датой изменения. Используй на «что я недавно делал», «над чем работал на "
        "неделе», «последняя заметка». Не путай с list_all_items (всё подряд) и search_base (по "
        "содержимому)."
    ),
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Сколько показать, по умолчанию 20, максимум 100"}},
        "required": [],
    },
)


async def list_recent(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = max(1, min(int(args.get("limit") or 20), 100))
    except (TypeError, ValueError):
        raise ToolError("limit — целое число от 1 до 100") from None
    rows = (
        await ctx.db.execute(
            select(Item, Space.name)
            .join(SpaceMember, SpaceMember.space_id == Item.space_id)
            .join(Space, Space.id == Item.space_id)
            .where(
                SpaceMember.user_id == ctx.user_id,
                Space.is_vault.is_(False),
                Item.deleted_at.is_(None),
                Item.material_type.in_(("note", "list", "ticket", "table", "routine")),
            )
            .order_by(Item.updated_at.desc())
            .limit(limit)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(i.id),
                "title": i.title,
                "material_type": i.material_type,
                "space_name": space_name,
                "updated_at": i.updated_at.isoformat(timespec="minutes"),
            }
            for i, space_name in rows
        ],
        "ссылок_здесь_нет": "Нужна ссылка на запись — вызови get_note/get_list по её id.",
    }


LIST_DOCUMENTS = ToolDefinition(
    name="list_documents",
    description=(
        "Все документы пользователя одним списком, из всех спейсов: PDF, офисные файлы, сканы с "
        "распознанным текстом — с датой, спейсом и заметкой, где лежит файл. Плюс серии: "
        "документы, приходящие ежемесячно (счета, выписки), с пропущенными месяцами и ожидаемым "
        "следующим. Используй на «какие документы есть», «пришёл ли счёт за сентябрь», «чего не "
        "хватает в серии». Содержимое конкретного файла — get_file по id."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)


async def list_documents(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    user = await ctx.db.get(User, ctx.user_id)
    out = await _list_documents(user=user, db=ctx.db)
    data = out.model_dump(mode="json")
    for doc in data["documents"]:
        doc["file_id"] = doc.pop("id")
    data["documents"] = data["documents"][:200]
    return data
