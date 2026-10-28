"""Инструменты ассистента для истории версий, корзины и архива.

История версий обязательна (CLAUDE.md, ТЗ §7): каждая правка через
ассистента оставляет снимок, но до 28.10 ассистент сам этих снимков не
видел — «верни вчерашний вариант» и «я случайно удалил заметку, верни»
были только руками в интерфейсе. Пользователь ходит в базу и через MCP
(Claude), где такие просьбы обычны.

Откат и архив переиспользуют обработчики REST (routers/items.py) как
функции — там уже есть то, что легко забыть: снимок текущего состояния
перед откатом, пересборка пунктов списка из текста, invalidate_room для
живой коллаборации. Повторять это здесь — завести вторую, отстающую копию.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from app import realtime
from app.deps import is_vault_space
from app.llm.base import ToolDefinition
from app.models import Item, ItemVersion, Space, SpaceMember, User
from app.routers.items import archive_item as _archive_item, revert_version as _revert_version
from app.tools.notes import SPACE_PARAM, _get_item_cross_space, _resolve_space, item_url
from app.tools.registry import ToolContext, ToolError

_PREVIEW = 200


def _version_entry(v: ItemVersion, authors: dict[uuid.UUID, str]) -> dict[str, Any]:
    content = v.content or ""
    return {
        "version_id": str(v.id),
        "created_at": v.created_at.isoformat(timespec="minutes"),
        "author": authors.get(v.author_id, "—") if v.author_id else "система",
        "title": v.title,
        "length": len(content),
        "preview": content[:_PREVIEW] + ("…" if len(content) > _PREVIEW else ""),
    }


LIST_VERSIONS = ToolDefinition(
    name="list_versions",
    description=(
        "История версий заметки или списка: когда, кто, заголовок, длина и начало текста каждого "
        "снимка (снимок делается ПЕРЕД каждой правкой, то есть хранит состояние ДО неё). "
        "Используй на «что было в заметке вчера», «кто это поменял», «верни как было» — выбери "
        "версию и вызови revert_version. Полный текст одной версии — передай её version_id, он "
        "придёт в full_text."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "version_id": {"type": "string", "description": "Показать одну версию целиком"},
        },
        "required": ["item_id"],
    },
)


async def list_versions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    rows = (
        await ctx.db.execute(select(ItemVersion).where(ItemVersion.item_id == item.id).order_by(ItemVersion.created_at.desc()))
    ).scalars().all()
    author_ids = {v.author_id for v in rows if v.author_id}
    authors = {
        u.id: (u.name or u.username)
        for u in ((await ctx.db.execute(select(User).where(User.id.in_(author_ids)))).scalars().all() if author_ids else [])
    }
    if args.get("version_id"):
        try:
            wanted = uuid.UUID(str(args["version_id"]))
        except ValueError:
            raise ToolError("Некорректный version_id — нужен UUID из list_versions") from None
        version = next((v for v in rows if v.id == wanted), None)
        if version is None:
            raise ToolError("Версия не найдена — вызови list_versions без version_id, чтобы увидеть реальные версии")
        return {"item_id": str(item.id), **_version_entry(version, authors), "full_text": version.content}
    return {
        "item_id": str(item.id),
        "title": item.title,
        "current_length": len(item.content or ""),
        "versions": [_version_entry(v, authors) for v in rows[:50]],
        **({"note": f"Показаны 50 из {len(rows)} версий, самые свежие"} if len(rows) > 50 else {}),
    }


REVERT_VERSION = ToolDefinition(
    name="revert_version",
    description=(
        "Откатить заметку или список к версии из list_versions. Текущее состояние перед откатом "
        "тоже сохраняется как версия, так что откат обратим. Перед вызовом назови пользователю, "
        "к какой версии (дата, начало текста) откатываешь, и получи согласие — это заменяет "
        "содержимое целиком."
    ),
    parameters={
        "type": "object",
        "properties": {"item_id": {"type": "string"}, "version_id": {"type": "string"}},
        "required": ["item_id", "version_id"],
    },
)


async def revert_version(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    try:
        version_id = uuid.UUID(str(args.get("version_id")))
    except (ValueError, TypeError):
        raise ToolError("Некорректный version_id — нужен UUID из list_versions") from None
    user = await ctx.db.get(User, ctx.user_id)
    try:
        await _revert_version(item.id, version_id, user=user, db=ctx.db)
    except HTTPException as exc:
        raise ToolError(str(exc.detail)) from None
    await ctx.db.refresh(item)
    return {"id": str(item.id), "title": item.title, "reverted": True, "url": item_url(item.id)}


LIST_TRASH = ToolDefinition(
    name="list_trash",
    description=(
        "Корзина: удалённые заметки, списки и таблицы (во всех спейсах пользователя или в одном "
        "— space). Используй на «я удалил заметку про…, верни», затем restore_note по id."
    ),
    parameters={"type": "object", "properties": {"space": SPACE_PARAM}, "required": []},
)


async def list_trash(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = (
        select(Item, Space.name)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .join(Space, Space.id == Item.space_id)
        .where(SpaceMember.user_id == ctx.user_id, Space.is_vault.is_(False), Item.deleted_at.is_not(None))
        .order_by(Item.deleted_at.desc())
        .limit(100)
    )
    if args.get("space"):
        query = query.where(Item.space_id == await _resolve_space(ctx, args["space"]))
    rows = (await ctx.db.execute(query)).all()
    return {
        "items": [
            {
                "id": str(item.id),
                "title": item.title,
                "material_type": item.material_type,
                "space_name": space_name,
                "deleted_at": item.deleted_at.isoformat(timespec="minutes"),
            }
            for item, space_name in rows
        ]
    }


RESTORE_NOTE = ToolDefinition(
    name="restore_note",
    description="Вернуть заметку/список/таблицу из корзины (id — из list_trash). Обратное к delete_note.",
    parameters={"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]},
)


async def restore_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        item_id = uuid.UUID(str(args.get("item_id")))
    except (ValueError, TypeError):
        raise ToolError("Некорректный id — нужен UUID из list_trash") from None
    item = await ctx.db.get(Item, item_id)
    not_found = ToolError("В корзине такого нет — вызови list_trash, чтобы увидеть, что там лежит")
    if item is None or item.deleted_at is None:
        raise not_found
    member = (
        await ctx.db.execute(select(SpaceMember).where(SpaceMember.space_id == item.space_id, SpaceMember.user_id == ctx.user_id))
    ).scalar_one_or_none()
    if member is None or await is_vault_space(ctx.db, item.space_id):
        raise not_found
    item.deleted_at = None
    await ctx.db.commit()
    await realtime.notify_space(item.space_id, "items")
    return {"id": str(item.id), "title": item.title, "restored": True, "url": item_url(item.id)}


ARCHIVE_NOTE = ToolDefinition(
    name="archive_note",
    description=(
        "Убрать заметку/список/таблицу в папку «Архив» её спейса (создаётся при первом "
        "использовании) — когда не нужно сейчас, но удалять жалко. Достать обратно — update_note с "
        "folder_id другой папки."
    ),
    parameters={"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]},
)


async def archive_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    user = await ctx.db.get(User, ctx.user_id)
    try:
        await _archive_item(item.id, user=user, db=ctx.db)
    except HTTPException as exc:
        raise ToolError(str(exc.detail)) from None
    await ctx.db.refresh(item)
    return {"id": str(item.id), "title": item.title, "archived": True, "folder_id": str(item.folder_id)}
