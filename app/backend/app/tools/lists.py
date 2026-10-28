from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.deps import ensure_space_access, is_vault_space
from app.llm.base import ToolDefinition
from app.models import Folder, Item, Space
from app.routers.items import create_item_row
from app.routers.lists import _broadcast, _serialize, _snapshot_version
from app.tools.notes import SPACE_PARAM
from app.tools.notes import _resolve_folder as _notes_resolve_folder
from app.tools.registry import ToolContext, ToolError

logger = logging.getLogger(__name__)


async def _safe_broadcast(item: Item) -> None:
    """Реальный найденный баг: WS-рассылка (чисто UX-приятность — синхронизация
    открытых вкладок в реальном времени) шла ПОСЛЕ db.commit() — то есть
    сам список УЖЕ сохранился, но если _serialize/_broadcast упадёт
    (поймано вживую: тестовые данные без created_at — Pydantic ValidationError),
    исключение улетает наружу и registry.dispatch превращает успешную
    операцию в "Внутренняя ошибка" для модели. Модель в ответ на РЕАЛЬНО
    удавшийся toggle честно, но неверно, говорила пользователю, что
    отметить не получилось. Рассылка — не источник истины, не должна уметь
    маскировать удавшуюся запись под провал."""
    try:
        await _broadcast(item.id, _serialize(item).model_dump(mode="json"))
    except Exception:
        logger.exception("Не удалось разослать обновление списка %s по WS (сама запись уже сохранена)", item.id)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flatten_entries(entries: list[dict]) -> str:
    return "\n".join(f"{'[x]' if e['checked'] else '[ ]'} {e['text']}" for e in entries)


# Одна реализация на заметки, списки и таблицы (tools/notes.py): раньше
# здесь была копия, и параметр space пришлось бы добавлять дважды.
_resolve_folder = _notes_resolve_folder


async def _get_list_item(ctx: ToolContext, list_id_raw: Any) -> Item:
    """Список ищется среди ВСЕХ спейсов пользователя, не только текущего
    диалога (ТЗ §10a — область контекста ассистента не ограничена одним
    спейсом, как и обычный поиск)."""
    try:
        list_id = uuid.UUID(str(list_id_raw))
    except (ValueError, TypeError):
        raise ToolError(f"Некорректный id списка: {list_id_raw} — нужен UUID из результата list_all_items, а не название списка") from None

    item = await ctx.db.get(Item, list_id)
    if item is None or item.material_type != "list" or item.deleted_at is not None:
        raise ToolError("Список не найден — вызови list_all_items, чтобы увидеть реальные списки и их id")
    try:
        await ensure_space_access(ctx.db, item.space_id, ctx.user_id)
    except HTTPException:
        raise ToolError("Список не найден — вызови list_all_items, чтобы увидеть реальные списки и их id") from None
    if await is_vault_space(ctx.db, item.space_id):
        raise ToolError("Список не найден — вызови list_all_items, чтобы увидеть реальные списки и их id")
    return item


CREATE_LIST = ToolDefinition(
    name="create_list",
    description=(
        "Создать список (чек-лист) — для покупок, задач и т.п., где нужны отмечаемые пункты, "
        "а не просто текст заметки. Можно сразу передать пункты. Без folder_id создаётся в "
        "текущем спейсе диалога — ПЕРЕД вызовом без folder_id проверь list_folders на "
        "тематически подходящую папку (например, список покупок логично класть туда же, где "
        "уже лежат похожие списки покупок, а не в спейс, где просто идёт разговор); с "
        "folder_id — в спейсе, которому принадлежит папка."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Название списка"},
            "folder_id": {"type": "string", "description": "id папки; не указывать — список в корне текущего спейса"},
            "space": SPACE_PARAM,
            "entries": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Пункты списка сразу при создании (необязательно). Если у пункта есть ссылка "
                    "— ТОЛЬКО markdown-формат '[короткое название](url)', например "
                    "'[Zarkoperfume The Muse](https://...)'. НИКОГДА не дописывай голый URL "
                    "текстом после названия ('Название https://...') — фронтенд не умеет "
                    "показывать это красиво, длинный URL как есть не помещается в строку "
                    "пункта на телефоне и становится нечитаемым/некликабельным."
                ),
            },
        },
        "required": ["title"],
    },
)


async def create_list(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    if not title:
        raise ToolError("Название списка не может быть пустым — придумай короткое по смыслу содержимого или спроси у пользователя через suggest_replies")

    folder_id, space_id = await _resolve_folder(ctx, args.get("folder_id"), args.get("space"))

    entries = [
        {"id": str(uuid.uuid4()), "text": str(t).strip(), "checked": False, "created_at": _now_iso()}
        for t in (args.get("entries") or [])
        if str(t).strip()
    ]

    item = await create_item_row(
        ctx.db,
        space_id=space_id,
        author_id=ctx.user_id,
        material_type="list",
        title=title,
        folder_id=folder_id,
        properties={"entries": entries},
    )
    if entries:
        item.content = _flatten_entries(entries)
        await ctx.db.commit()

    space = await ctx.db.get(Space, item.space_id)
    return {
        "id": str(item.id),
        "title": item.title,
        "entries": [e["text"] for e in entries],
        "space_id": str(item.space_id),
        "space_name": space.name if space else "",
    }


GET_LIST = ToolDefinition(
    name="get_list",
    description=(
        "Посмотреть реальное содержимое списка (все пункты и их статус выполнено/нет) по id. "
        "Вызывай это перед тем, как показывать пользователю содержимое списка, отвечать на вопросы "
        "о нём или отмечать/добавлять пункты — НИКОГДА не придумывай содержимое списка самостоятельно, "
        "list_items_in_folder и search_base дают только название и id, не сами пункты."
    ),
    parameters={
        "type": "object",
        "properties": {"list_id": {"type": "string"}},
        "required": ["list_id"],
    },
)


async def get_list(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_list_item(ctx, args.get("list_id"))
    entries = item.properties.get("entries", [])
    return {
        "id": str(item.id),
        "title": item.title,
        "entries": [{"id": e["id"], "text": e["text"], "checked": e["checked"]} for e in entries],
    }


ADD_LIST_ENTRY = ToolDefinition(
    name="add_list_entry",
    description=(
        "Добавить НОВЫЙ пункт в уже существующий список. Не используй это, чтобы отметить уже "
        "существующий пункт купленным/выполненным — для этого toggle_list_entry, иначе получится "
        "дубликат."
    ),
    parameters={
        "type": "object",
        "properties": {
            "list_id": {"type": "string"},
            "text": {
                "type": "string",
                "description": (
                    "Текст пункта. Если есть ссылка — ТОЛЬКО markdown '[короткое название](url)', "
                    "никогда голый URL текстом после названия — не помещается в строку на телефоне."
                ),
            },
        },
        "required": ["list_id", "text"],
    },
)


async def add_list_entry(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_list_item(ctx, args.get("list_id"))

    text = str(args.get("text", "")).strip()
    if not text:
        raise ToolError("Пустой пункт — передай непустой text")

    entries = list(item.properties.get("entries", []))
    await _snapshot_version(ctx.db, item, ctx.user_id)
    entries.append({"id": str(uuid.uuid4()), "text": text, "checked": False, "created_at": _now_iso()})
    item.properties = {**item.properties, "entries": entries}
    item.content = _flatten_entries(entries)
    await ctx.db.commit()
    await ctx.db.refresh(item)

    await _safe_broadcast(item)
    return {"list_id": str(item.id), "entries": [e["text"] for e in entries]}


TOGGLE_LIST_ENTRY = ToolDefinition(
    name="toggle_list_entry",
    description=(
        "Отметить существующий пункт списка выполненным/купленным или снять отметку — по id пункта "
        "(из get_list) или по совпадению текста, если id неизвестен. Сначала вызови get_list, если "
        "не уверен, что пункт действительно есть и как он называется."
    ),
    parameters={
        "type": "object",
        "properties": {
            "list_id": {"type": "string"},
            "entry_id": {"type": "string", "description": "id пункта, если известен"},
            "text_match": {"type": "string", "description": "текст пункта для поиска, если id неизвестен"},
            "checked": {"type": "boolean", "description": "true — отметить выполненным, false — снять отметку"},
        },
        "required": ["list_id", "checked"],
    },
)


async def toggle_list_entry(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_list_item(ctx, args.get("list_id"))
    entry_id = args.get("entry_id")
    text_match = str(args.get("text_match", "")).strip().lower()
    checked = args.get("checked")
    if checked is None:
        raise ToolError("Не передан checked — true чтобы отметить пункт купленным/сделанным, false чтобы снять отметку")

    existing = item.properties.get("entries", [])
    target = None
    if entry_id:
        target = next((e for e in existing if e["id"] == entry_id), None)
    elif text_match:
        target = next((e for e in existing if text_match in e["text"].lower()), None)

    if target is None:
        raise ToolError("Пункт не найден — сначала вызови get_list, чтобы увидеть реальные пункты и их id")

    entries = [dict(e, checked=checked) if e["id"] == target["id"] else e for e in existing]
    await _snapshot_version(ctx.db, item, ctx.user_id)
    item.properties = {**item.properties, "entries": entries}
    item.content = _flatten_entries(entries)
    await ctx.db.commit()
    await ctx.db.refresh(item)

    await _safe_broadcast(item)
    return {"list_id": str(item.id), "entry": target["text"], "checked": checked}


# Правка и удаление пунктов — то, чего у ассистента не было до 28.10 (были
# только «добавить» и «отметить»): «исправь молоко на молоко 2 л» и «убери
# хлеб» заканчивались дубликатом или отказом. Пункт ищется так же, как у
# toggle_list_entry: по id из get_list или по вхождению текста.


def _find_entry(item: Item, entry_id: Any, text_match: Any) -> dict:
    existing = item.properties.get("entries", [])
    text = str(text_match or "").strip().lower()
    target = None
    if entry_id:
        target = next((e for e in existing if e["id"] == str(entry_id)), None)
    elif text:
        matches = [e for e in existing if text in e["text"].lower()]
        if len(matches) > 1:
            exact = [e for e in matches if e["text"].strip().lower() == text]
            if len(exact) != 1:
                names = ", ".join(f"«{e['text']}»" for e in matches[:5])
                raise ToolError(f"Под «{text_match}» подходит несколько пунктов: {names} — возьми entry_id из get_list")
            matches = exact
        target = matches[0] if matches else None
    if target is None:
        raise ToolError("Пункт не найден — сначала вызови get_list, чтобы увидеть реальные пункты и их id")
    return target


async def _save_entries(ctx: ToolContext, item: Item, entries: list[dict]) -> None:
    await _snapshot_version(ctx.db, item, ctx.user_id)
    item.properties = {**item.properties, "entries": entries}
    item.content = _flatten_entries(entries)
    await ctx.db.commit()
    await ctx.db.refresh(item)
    await _safe_broadcast(item)


UPDATE_LIST_ENTRY = ToolDefinition(
    name="update_list_entry",
    description=(
        "Изменить ТЕКСТ существующего пункта списка («исправь “молоко” на “молоко 2 л”»). Пункт — "
        "по entry_id из get_list или по text_match (вхождение текста). Для отметки выполнено/нет — "
        "toggle_list_entry, для нового пункта — add_list_entry."
    ),
    parameters={
        "type": "object",
        "properties": {
            "list_id": {"type": "string"},
            "entry_id": {"type": "string", "description": "id пункта из get_list, если известен"},
            "text_match": {"type": "string", "description": "текст (или часть) существующего пункта, если id неизвестен"},
            "text": {"type": "string", "description": "Новый текст пункта целиком"},
        },
        "required": ["list_id", "text"],
    },
)


async def update_list_entry(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_list_item(ctx, args.get("list_id"))
    text = str(args.get("text", "")).strip()
    if not text:
        raise ToolError("Пустой text — передай новый текст пункта; удалить пункт — delete_list_entry")
    target = _find_entry(item, args.get("entry_id"), args.get("text_match"))
    entries = [dict(e, text=text) if e["id"] == target["id"] else e for e in item.properties.get("entries", [])]
    await _save_entries(ctx, item, entries)
    return {"list_id": str(item.id), "entry_id": target["id"], "was": target["text"], "text": text}


DELETE_LIST_ENTRY = ToolDefinition(
    name="delete_list_entry",
    description=(
        "Удалить пункт из списка («убери хлеб из списка»). Пункт — по entry_id из get_list или по "
        "text_match. Не используй вместо отметки «куплено» — для этого toggle_list_entry: "
        "отмеченный пункт остаётся в списке зачёркнутым, удалённый пропадает."
    ),
    parameters={
        "type": "object",
        "properties": {
            "list_id": {"type": "string"},
            "entry_id": {"type": "string", "description": "id пункта из get_list, если известен"},
            "text_match": {"type": "string", "description": "текст (или часть) пункта, если id неизвестен"},
        },
        "required": ["list_id"],
    },
)


async def delete_list_entry(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_list_item(ctx, args.get("list_id"))
    target = _find_entry(item, args.get("entry_id"), args.get("text_match"))
    entries = [e for e in item.properties.get("entries", []) if e["id"] != target["id"]]
    await _save_entries(ctx, item, entries)
    return {"list_id": str(item.id), "deleted": target["text"], "entries_left": len(entries)}
