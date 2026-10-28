"""Инструменты ассистента для папок и тегов: переименовать, перенести,
удалить, снять тег, слить теги.

До 28.10 ассистент умел только создавать папки и добавлять теги: «назови
папку иначе», «перенеси папку в семейный», «убери тег», «слей “кот” и
“коты”» — всё это было только руками в интерфейсе. Пользователь ходит в
базу и через MCP (Claude), где такие просьбы естественны.

Границы:
- удалить можно только ПУСТУЮ папку: подпапки удаляются каскадом (FK
  folders.parent_id ON DELETE CASCADE), заметки уезжают в корень — для
  ассистента это слишком тихо. Непустая — отказ с числом вложений и
  подсказкой перенести;
- тег — личная сущность пользователя (Tag.user_id), ищется по имени без
  учёта регистра, как его называет человек.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from app import realtime
from app.deps import ensure_space_access, is_vault_space
from app.llm.base import ToolDefinition
from app.models import Folder, Item, ItemTag, Tag
from app.routers.folders import move_folder_space
from app.schemas.folder import FolderMoveSpace
from app.tools.notes import SPACE_PARAM, _get_item_cross_space, _resolve_space
from app.tools.registry import ToolContext, ToolError


async def _get_folder(ctx: ToolContext, raw: Any) -> Folder:
    try:
        folder_id = uuid.UUID(str(raw))
    except (ValueError, TypeError):
        raise ToolError(f"Некорректный id папки: {raw} — нужен UUID из list_folders, а не название") from None
    folder = await ctx.db.get(Folder, folder_id)
    not_found = ToolError("Папка не найдена — вызови list_folders, чтобы увидеть реальные папки и их id")
    if folder is None:
        raise not_found
    try:
        await ensure_space_access(ctx.db, folder.space_id, ctx.user_id)
    except HTTPException:
        raise not_found from None
    if await is_vault_space(ctx.db, folder.space_id):
        raise not_found
    return folder


UPDATE_FOLDER = ToolDefinition(
    name="update_folder",
    description=(
        "Переименовать папку (name), вложить в другую папку или вынести в корень (parent_id, "
        "пустая строка — в корень), перенести в другой спейс целиком со всем содержимым (space). "
        "Передавай только то, что меняешь. folder_id — из list_folders."
    ),
    parameters={
        "type": "object",
        "properties": {
            "folder_id": {"type": "string", "description": "id папки из list_folders"},
            "name": {"type": "string", "description": "Новое название"},
            "parent_id": {"type": "string", "description": "id новой родительской папки в том же спейсе; пустая строка — в корень"},
            "space": SPACE_PARAM,
        },
        "required": ["folder_id"],
    },
)


async def update_folder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    folder = await _get_folder(ctx, args.get("folder_id"))
    changed: list[str] = []
    if args.get("name") is not None and str(args["name"]).strip():
        folder.name = str(args["name"]).strip()[:255]
        changed.append("name")
    if "parent_id" in args and args["parent_id"] is not None:
        raw = str(args["parent_id"]).strip()
        if not raw:
            folder.parent_id = None
        else:
            parent = await _get_folder(ctx, raw)
            if parent.space_id != folder.space_id:
                raise ToolError("Родительская папка в другом спейсе — сначала перенеси папку туда через space")
            if parent.id == folder.id:
                raise ToolError("Папка не может быть родителем самой себе — укажи другую папку или пустую строку для корня")
            ancestor: Folder | None = parent
            while ancestor is not None:
                if ancestor.id == folder.id:
                    raise ToolError("Нельзя вложить папку в её же подпапку — выбери папку вне её поддерева")
                ancestor = await ctx.db.get(Folder, ancestor.parent_id) if ancestor.parent_id else None
            folder.parent_id = parent.id
        changed.append("parent_id")
    if changed:
        await ctx.db.commit()
        await ctx.db.refresh(folder)
        await realtime.notify_space(folder.space_id, "folders")
    if args.get("space"):
        target = await _resolve_space(ctx, args["space"])
        if target != folder.space_id:
            from app.models import User

            user = await ctx.db.get(User, ctx.user_id)
            try:
                await move_folder_space(folder.id, FolderMoveSpace(space_id=target), user=user, db=ctx.db)
            except HTTPException as exc:
                raise ToolError(str(exc.detail)) from None
            await ctx.db.refresh(folder)
            changed.append("space")
    if not changed:
        raise ToolError("Нечего менять — передай name, parent_id или space")
    return {
        "id": str(folder.id),
        "name": folder.name,
        "parent_id": str(folder.parent_id) if folder.parent_id else None,
        "space_id": str(folder.space_id),
        "changed": changed,
    }


DELETE_FOLDER = ToolDefinition(
    name="delete_folder",
    description=(
        "Удалить ПУСТУЮ папку. Если в ней есть заметки или подпапки — откажет и скажет, сколько: "
        "сначала перенеси содержимое (update_note с folder_id, update_folder с parent_id) или "
        "удали его. folder_id — из list_folders."
    ),
    parameters={
        "type": "object",
        "properties": {"folder_id": {"type": "string", "description": "id папки из list_folders"}},
        "required": ["folder_id"],
    },
)


async def delete_folder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    folder = await _get_folder(ctx, args.get("folder_id"))
    items = (await ctx.db.execute(select(func.count()).select_from(Item).where(Item.folder_id == folder.id))).scalar_one()
    subfolders = (await ctx.db.execute(select(func.count()).select_from(Folder).where(Folder.parent_id == folder.id))).scalar_one()
    if items or subfolders:
        raise ToolError(
            f"Папка «{folder.name}» не пуста: заметок {items}, подпапок {subfolders} (включая корзину) — "
            "перенеси или удали содержимое, потом удаляй папку"
        )
    space_id, name = folder.space_id, folder.name
    await ctx.db.delete(folder)
    await ctx.db.commit()
    await realtime.notify_space(space_id, "folders")
    return {"deleted": name}


# --- теги ----------------------------------------------------------------


async def _own_tag(ctx: ToolContext, raw: Any) -> Tag:
    name = str(raw or "").strip()
    if not name:
        raise ToolError("Имя тега не может быть пустым — существующие теги даёт list_tags")
    rows = (await ctx.db.execute(select(Tag).where(Tag.user_id == ctx.user_id, func.lower(Tag.name) == name.lower()))).scalars().all()
    if not rows:
        raise ToolError(f"Тега «{name}» нет — вызови list_tags, чтобы увидеть реальные теги")
    exact = [t for t in rows if t.name == name]
    return exact[0] if exact else rows[0]


REMOVE_TAG = ToolDefinition(
    name="remove_tag",
    description="Снять тег с заметки (сам тег остаётся у пользователя). Обратное к add_tag.",
    parameters={
        "type": "object",
        "properties": {"item_id": {"type": "string"}, "tag_name": {"type": "string"}},
        "required": ["item_id", "tag_name"],
    },
)


async def remove_tag(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    tag = await _own_tag(ctx, args.get("tag_name"))
    link = (
        await ctx.db.execute(select(ItemTag).where(ItemTag.item_id == item.id, ItemTag.tag_id == tag.id, ItemTag.user_id == ctx.user_id))
    ).scalar_one_or_none()
    if link is None:
        return {"item_id": str(item.id), "tag": tag.name, "removed": False, "note": "Этого тега на заметке и не было"}
    await ctx.db.delete(link)
    await ctx.db.commit()
    await realtime.notify_space(item.space_id, "items")
    return {"item_id": str(item.id), "tag": tag.name, "removed": True}


RENAME_TAG = ToolDefinition(
    name="rename_tag",
    description="Переименовать тег везде, где он стоит. Если тег с новым именем уже есть — используй merge_tag.",
    parameters={
        "type": "object",
        "properties": {"tag_name": {"type": "string"}, "new_name": {"type": "string"}},
        "required": ["tag_name", "new_name"],
    },
)


async def rename_tag(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    tag = await _own_tag(ctx, args.get("tag_name"))
    new_name = str(args.get("new_name") or "").strip()
    if not new_name:
        raise ToolError("Новое имя тега пустое — передай непустое new_name")
    clash = (
        await ctx.db.execute(select(Tag).where(Tag.user_id == ctx.user_id, Tag.name == new_name, Tag.id != tag.id))
    ).scalar_one_or_none()
    if clash is not None:
        raise ToolError(f"Тег «{new_name}» уже есть — чтобы объединить, вызови merge_tag")
    was = tag.name
    tag.name = new_name
    await ctx.db.commit()
    return {"was": was, "name": new_name}


MERGE_TAG = ToolDefinition(
    name="merge_tag",
    description=(
        "Слить два тега: все заметки с tag_name получают into, tag_name удаляется («кот» и «коты» "
        "— один тег). Необратимо, поэтому назови пользователю оба тега перед вызовом."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tag_name": {"type": "string", "description": "Тег, который исчезнет"},
            "into": {"type": "string", "description": "Тег, который останется"},
        },
        "required": ["tag_name", "into"],
    },
)


async def merge_tag(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    source = await _own_tag(ctx, args.get("tag_name"))
    target = await _own_tag(ctx, args.get("into"))
    if source.id == target.id:
        raise ToolError("Это один и тот же тег — сливать нечего, выбери два разных из list_tags")
    links = (await ctx.db.execute(select(ItemTag).where(ItemTag.tag_id == source.id))).scalars().all()
    moved = 0
    for link in links:
        already = (
            await ctx.db.execute(
                select(ItemTag).where(ItemTag.item_id == link.item_id, ItemTag.tag_id == target.id, ItemTag.user_id == link.user_id)
            )
        ).scalar_one_or_none()
        if already is None:
            ctx.db.add(ItemTag(item_id=link.item_id, tag_id=target.id, user_id=link.user_id))
            moved += 1
        await ctx.db.delete(link)
    await ctx.db.delete(source)
    await ctx.db.commit()
    return {"merged": source.name, "into": target.name, "items_retagged": moved}


DELETE_TAG = ToolDefinition(
    name="delete_tag",
    description=(
        "Удалить тег у пользователя целиком — он пропадёт со всех заметок (сами заметки не "
        "трогаются). Если нужно только снять с одной заметки — remove_tag."
    ),
    parameters={"type": "object", "properties": {"tag_name": {"type": "string"}}, "required": ["tag_name"]},
)


async def delete_tag(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    tag = await _own_tag(ctx, args.get("tag_name"))
    count = (await ctx.db.execute(select(func.count()).select_from(ItemTag).where(ItemTag.tag_id == tag.id))).scalar_one()
    name = tag.name
    await ctx.db.delete(tag)
    await ctx.db.commit()
    return {"deleted": name, "was_on_items": count}
