"""Инструменты ассистента для публичных ссылок на заметку.

Публикация работает только для заметок в спейсе «Публичные страницы»
(Space.is_public_pages, routers/items.py::share_item) — это осознанная
граница: случайно опубликовать заметку из «Личного» нельзя, её сначала
переносят. Инструмент не обходит это правило, а объясняет его модели.
Сами обработчики REST переиспользуются как функции: токен, пароль, срок,
одноразовость — всё там.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.core.config import get_settings
from app.llm.base import ToolDefinition
from app.models import User
from app.routers.items import share_item as _share_item, unshare_item as _unshare_item
from app.schemas.item import ShareItemIn
from app.tools.notes import _get_item_cross_space
from app.tools.registry import ToolContext, ToolError


def _share_url(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/s/{token}"


SHARE_NOTE = ToolDefinition(
    name="share_note",
    description=(
        "Опубликовать заметку по публичной ссылке (для тех, у кого нет доступа в базу). Работает "
        "только для заметок в спейсе «Публичные страницы» — если заметка в другом спейсе, сначала "
        "перенеси её туда (update_note с space) и скажи об этом пользователю. Можно задать пароль, "
        "срок в днях и одноразовость. Повторный вызов выдаёт новую ссылку, старая перестаёт "
        "работать. Перед публикацией подтверди с пользователем: содержимое станет доступно по "
        "ссылке любому."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "password": {"type": "string", "description": "Пароль на страницу, если нужен"},
            "expires_in_days": {"type": "integer", "description": "Через сколько дней ссылка перестанет работать (1–365); не указать — бессрочно"},
            "single_use": {"type": "boolean", "description": "true — ссылка откроется один раз"},
        },
        "required": ["item_id"],
    },
)


async def share_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    user = await ctx.db.get(User, ctx.user_id)
    try:
        payload = ShareItemIn(
            password=(str(args["password"]).strip() or None) if args.get("password") else None,
            expires_in_days=args.get("expires_in_days") or None,
            single_use=bool(args.get("single_use")),
        )
    except ValueError as exc:
        raise ToolError(f"Параметры не приняты — {exc}; поправь и вызови снова") from None
    try:
        out = await _share_item(item.id, payload, user=user, db=ctx.db)
    except HTTPException as exc:
        if "Публичные страницы" in str(exc.detail):
            raise ToolError(
                "Заметка не в спейсе «Публичные страницы» — публиковать можно только оттуда: "
                "перенеси её (update_note с space=\"Публичные страницы\", если такой спейс есть в list_folders) "
                "или скажи пользователю, что публикация настроена только для этого спейса"
            ) from None
        raise ToolError(f"{exc.detail} — публиковать можно только обычные заметки") from None
    return {
        "id": str(item.id),
        "title": item.title,
        "url": _share_url(out.share_token),
        "has_password": out.has_password,
        "expires_at": out.share_expires_at.isoformat(timespec="minutes") if out.share_expires_at else None,
        "single_use": out.share_single_use,
    }


UNSHARE_NOTE = ToolDefinition(
    name="unshare_note",
    description="Снять заметку с публикации — публичная ссылка перестаёт работать сразу и навсегда.",
    parameters={"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]},
)


async def unshare_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    was_public = bool(item.is_public)
    user = await ctx.db.get(User, ctx.user_id)
    await _unshare_item(item.id, user=user, db=ctx.db)
    return {"id": str(item.id), "title": item.title, "public": False, "was_public": was_public}
