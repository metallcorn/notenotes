from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from app import collab, realtime
from app.core.config import get_settings
from app.deps import ensure_space_access, is_vault_space
from app.llm.base import ToolDefinition
from app.models import Folder, Item, ItemTag, ItemVersion, Space, SpaceMember, Tag
from app.note_formatting import linkify_notes_content
from app.routers.items import create_item_row
from app.attachment_text import attachment_texts, readable_content
from app.identifier_ambiguity import ambiguity_warning
from app.tools.registry import ToolContext, ToolError

# Реальный найденный случай: пользователь просит ссылку на заметку —
# модель, не имея готового URL ни в одном тул-результате, придумывала его
# сама (несуществующая схема "notenotes://<id>", либо голый id вместо
# ссылки) — обе формы не кликабельны. item_url — единственный источник
# правды для ссылки на заметку/список, отдаётся прямо в результатах
# тулов ниже, чтобы модели не приходилось ничего собирать самой (тот же
# принцип, что "Не составляй и не достраивай URL сам" в SYSTEM_PROMPT_BASE,
# routers/dialogs.py). Тот же паттерн /?item=, что уже использует
# notification_dispatch.py для кнопки "Открыть" в Telegram-уведомлениях.
def item_url(item_id: uuid.UUID | str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/?item={item_id}"

# ТЗ §10a: "область контекста — все спейсы пользователя, та же логика, что
# у обычного поиска" — ассистент не должен быть слеп к спейсам, отличным от
# того, где идёт текущий диалог. Поэтому чтение/изменение существующих
# объектов проверяется через ensure_space_access (любой спейс пользователя),
# а не жёстким сравнением с ctx.space_id. Создание нового по умолчанию всё
# ещё идёт в текущий спейс диалога — если явно не указана папка из другого.


async def _resolve_folder(
    ctx: ToolContext, folder_id_raw: Any, space_raw: Any = None
) -> tuple[uuid.UUID | None, uuid.UUID]:
    """Без folder_id — спейс space_raw (или текущий спейс диалога). С
    folder_id — спейс папки, даже если это не тот же спейс, где идёт диалог
    (если пользователь там состоит)."""
    if not folder_id_raw:
        return None, await _resolve_space(ctx, space_raw)
    try:
        folder_id = uuid.UUID(str(folder_id_raw))
    except ValueError:
        raise ToolError(f"Некорректный id папки: {folder_id_raw} — нужен UUID из результата list_folders, а не название папки") from None
    folder = await ctx.db.get(Folder, folder_id)
    if folder is None:
        raise ToolError("Папка не найдена — вызови list_folders, чтобы увидеть реальные папки и их id")
    try:
        await ensure_space_access(ctx.db, folder.space_id, ctx.user_id)
    except HTTPException:
        raise ToolError("Папка не найдена — вызови list_folders, чтобы увидеть реальные папки и их id") from None
    # Сейф — ассистент не должен даже знать о его существовании (тот же
    # ответ, что для реально недоступной папки), не только не читать
    # содержимое: сервер физически не может ничего прочитать в сейфе.
    if await is_vault_space(ctx.db, folder.space_id):
        raise ToolError("Папка не найдена — вызови list_folders, чтобы увидеть реальные папки и их id")
    if space_raw is not None and str(space_raw).strip():
        if await _resolve_space(ctx, space_raw) != folder.space_id:
            raise ToolError("Эта папка в другом спейсе — возьми папку из нужного спейса (list_folders) или не указывай space")
    return folder_id, folder.space_id


# Живой случай 19.10 (Telegram, участник семьи): «сделай заметку в
# семейном спейсе» — трижды подряд заметка создавалась в спейсе «Telegram»,
# куда привязан бот. Указать спейс было просто нечем: create_note знал
# только folder_id, create_folder — только текущий спейс, а перенести
# готовую заметку ассистент не умел вовсе. Теперь спейс можно назвать
# словами — так, как его называет человек.
SPACE_PARAM = {
    "type": "string",
    "description": (
        "Спейс — название, как его называет пользователь («Семейный»), или id. "
        "Не указывать — текущий спейс диалога"
    ),
}


async def _user_spaces(ctx: ToolContext) -> list[Space]:
    return list(
        (
            await ctx.db.execute(
                select(Space)
                .join(SpaceMember, SpaceMember.space_id == Space.id)
                .where(SpaceMember.user_id == ctx.user_id, Space.is_vault.is_(False))
                .order_by(Space.created_at, Space.id)
            )
        ).scalars().all()
    )


def _space_key(name: str) -> str:
    key = name.casefold().replace("ё", "е")
    for noise in ("спейсе", "спейс", "space", "пространстве", "пространство"):
        key = key.replace(noise, " ")
    return " ".join(key.split())


async def _resolve_space(ctx: ToolContext, raw: Any) -> uuid.UUID:
    """Спейс по названию или id. Без значения — текущий спейс диалога.

    Название сверяется без регистра, а затем по общему началу слова:
    человек говорит «в семейном», а спейс называется «Семейный». Сейф не
    находится никак — тот же ответ, что для несуществующего.
    """
    if raw is None or not str(raw).strip():
        return ctx.space_id
    spaces = await _user_spaces(ctx)
    names = ", ".join(f"«{sp.name}»" for sp in spaces)
    text = str(raw).strip()
    try:
        wanted_id = uuid.UUID(text)
    except ValueError:
        wanted_id = None
    if wanted_id is not None:
        for sp in spaces:
            if sp.id == wanted_id:
                return sp.id
        raise ToolError(f"Спейс не найден. Спейсы пользователя: {names}")

    key = _space_key(text)
    exact = [sp for sp in spaces if _space_key(sp.name) == key]
    if len(exact) == 1:
        return exact[0].id
    # По словам, с общим началом от 4 букв: «в семейном» ~ «Семейный»,
    # «личном» ~ «Личное». Предлоги короче трёх букв не в счёт.
    said = [w for w in key.split() if len(w) >= 3]

    def stem_match(sp: Space) -> bool:
        for name_word in _space_key(sp.name).split():
            for word in said:
                need = min(4, len(name_word), len(word))
                if name_word[:need] == word[:need] and need >= min(3, len(name_word)):
                    return True
        return False

    close = [sp for sp in spaces if stem_match(sp)]
    if len(close) == 1:
        return close[0].id
    if close:
        options = ", ".join(f"«{sp.name}»" for sp in close)
        raise ToolError(f"Под «{text}» подходит несколько спейсов: {options} — уточни у пользователя")
    raise ToolError(f"Спейса «{text}» нет. Спейсы пользователя: {names}")


async def _get_item_cross_space(ctx: ToolContext, item_id_raw: Any) -> Item:
    try:
        item_id = uuid.UUID(str(item_id_raw))
    except (ValueError, TypeError):
        raise ToolError(f"Некорректный id заметки: {item_id_raw} — нужен UUID из результата search_base или list_all_items, а не название заметки") from None

    item = await ctx.db.get(Item, item_id)
    if item is None or item.deleted_at is not None:
        raise ToolError("Заметка не найдена — найди её через search_base (по смыслу) или list_all_items и возьми id из результата")
    try:
        await ensure_space_access(ctx.db, item.space_id, ctx.user_id)
    except HTTPException:
        raise ToolError("Заметка не найдена — найди её через search_base (по смыслу) или list_all_items и возьми id из результата") from None
    if await is_vault_space(ctx.db, item.space_id):
        raise ToolError("Заметка не найдена — найди её через search_base (по смыслу) или list_all_items и возьми id из результата")
    return item


_MATERIAL_TYPE_HINTS = {
    "list": "это список — используй get_list/add_list_entry/toggle_list_entry",
    "table": "это таблица — используй get_table/add_table_row/update_table_row",
}


def _require_note_like(item: Item) -> None:
    """Реальный найденный баг: append_to_note вызвали на id ТАБЛИЦЫ
    (material_type="table") — тул тихо дописал markdown-текст в
    неиспользуемое поле content этого item'а (таблица рендерится из
    properties.columns/rows, не из content), тул отрапортовал успех, а
    визуально для пользователя ничего не изменилось — тот же класс лжи,
    что уже чинили для пустого text. get_note уже проверял material_type
    (сообщение "не заметка, используй get_list") — update_note/
    append_to_note той же проверки не имели вообще."""
    if item.material_type in ("note", "ticket"):
        return
    hint = _MATERIAL_TYPE_HINTS.get(item.material_type, f"material_type={item.material_type}")
    raise ToolError(f"Это не заметка — {hint}")


CREATE_NOTE = ToolDefinition(
    name="create_note",
    description=(
        "Создать новую заметку. Содержимое — в формате Markdown. Где: space — спейс по названию "
        "(«в семейном» → space=\"Семейный\"); folder_id — папка (спейс берётся от неё). Ничего "
        "не указано — корень текущего спейса диалога."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Заголовок заметки"},
            "content": {"type": "string", "description": "Содержимое в Markdown"},
            "folder_id": {"type": "string", "description": "id папки; не указывать — заметка в корне спейса"},
            "space": SPACE_PARAM,
        },
        "required": ["title", "content"],
    },
)


async def create_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    # Ассистент никогда не проходит через paste в редакторе, поэтому строка
    # вида "[readyfest.pl](url)" сама по себе не станет карточкой сайта без
    # этого шага (тот же приём, что уже был у Telegram-бота, см.
    # note_formatting.py — реальная жалоба: заметки от ассистента с
    # ссылками выглядели "необработанными" по сравнению с заметками,
    # созданными вручную вставкой ссылки).
    content = linkify_notes_content(str(args.get("content", "")))
    folder_id, space_id = await _resolve_folder(ctx, args.get("folder_id"), args.get("space"))

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
    return {
        "id": str(item.id),
        "title": item.title,
        "space_id": str(item.space_id),
        "space_name": space.name if space else "",
        "url": item_url(item.id),
    }


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


# Потолок текста одного файла в get_note. Раньше текст PDF приходил в
# content целиком (до 20000 символов) — ровно то, от чего тонул контекст
# ассистента. Дальше — get_file.
_FILE_TEXT_CHARS = 8000


async def get_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    _require_note_like(item)
    result: dict[str, Any] = {"id": str(item.id), "title": item.title, "content": item.content, "url": item_url(item.id)}
    if item.material_type == "ticket":
        # content для билета — почти только служебный <div
        # data-ticket-attachment ...> (сам текст полностью заменяется
        # карточкой при распознавании, см. tickets.py) — моделью не
        # читается осмысленно. properties — уже готовые чистые поля
        # (тип, дата/время, откуда-куда, место), их и возвращаем как
        # основной источник ответа.
        result["material_type"] = "ticket"
        result["properties"] = item.properties
    # Распознанный текст вложений — отдельным полем, а не внутри content.
    # С 18.10 его нет в заметке (app/attachment_text.py); раскрывать его в
    # сам content нельзя: модель переписывает заметку через update_note
    # целиком, и вместо тега карточки в заметку лёг бы голый текст файла.
    files = []
    for t in await attachment_texts(ctx.db, item.content or ""):
        entry: dict[str, Any] = {"filename": t.filename, "text": t.text[:_FILE_TEXT_CHARS]}
        if t.attachment.upload_id is not None:
            entry["file_id"] = str(t.attachment.upload_id)
        if len(t.text) > _FILE_TEXT_CHARS:
            entry["text_truncated"] = "полный текст — get_file по file_id"
        files.append(entry)
    if files:
        result["files"] = files
    # Несколько разных номеров в одном документе — модель обязана узнать
    # об этом до того, как назовёт один из них (identifier_ambiguity.py).
    # По заметке ВМЕСТЕ с текстом файлов: номера живут в сканах.
    warning = ambiguity_warning(await readable_content(ctx.db, item.content or ""))
    if warning:
        result["чьи_номера"] = warning
    return result


UPDATE_NOTE = ToolDefinition(
    name="update_note",
    description=(
        "Изменить заголовок и/или содержимое существующей заметки. Незаданные поля не меняются. "
        "content заменяет содержимое ЦЕЛИКОМ, не добавляет к старому — просто ДОПИСАТЬ что-то "
        "в конец (лог тренировки по подходу, добавить пункт и т.п.) используй append_to_note, "
        "не это: он сам дописывает в базе, не заставляя тебя перепечатывать всё, что уже было, "
        "а значит невозможно случайно потерять тег вложения (![](url), <video>, <audio>, "
        "data-url=...) или старую запись при переписывании. Настоящее update_note — для "
        "правки/удаления/реструктуризации уже существующего текста, когда правда нужно "
        "заменить содержимое целиком. Перенести заметку (или список, таблицу) в другую папку "
        "или спейс — folder_id и/или space; переносится сама заметка, копию не создавай."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "folder_id": {"type": "string", "description": "Перенести в эту папку (id из list_folders)"},
            "space": {**SPACE_PARAM, "description": "Перенести в этот спейс (название или id), в корень, если без folder_id"},
        },
        "required": ["item_id"],
    },
)


async def _move_item(ctx: ToolContext, item: Item, folder_raw: Any, space_raw: Any) -> None:
    """Перенос тем же кодом, что кнопка «Переместить» в вебе
    (routers/items.py::move_item_space): у переноса между спейсами есть
    побочные эффекты (файлы заметки переезжают вместе с ней), и второй
    реализации им взяться неоткуда."""
    from app.models import User
    from app.routers.items import move_item_space
    from app.schemas.item import ItemMoveSpace

    if folder_raw:
        folder_id, space_id = await _resolve_folder(ctx, folder_raw, space_raw)
    else:
        folder_id, space_id = None, await _resolve_space(ctx, space_raw)
    user = await ctx.db.get(User, ctx.user_id)
    try:
        await move_item_space(item.id, ItemMoveSpace(space_id=space_id, folder_id=folder_id), user, ctx.db)
    except HTTPException as e:
        raise ToolError(f"Перенести не удалось: {e.detail}") from None
    await ctx.db.refresh(item)


async def update_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    new_title = args.get("title")
    new_content = args.get("content")
    moving = bool(args.get("folder_id")) or bool(str(args.get("space") or "").strip())
    # Перенос годится и для списка с таблицей — их тоже раскладывают по
    # папкам. Правка текста — только заметке (см. _require_note_like).
    if new_title is not None or new_content is not None or not moving:
        _require_note_like(item)
    if moving:
        await _move_item(ctx, item, args.get("folder_id"), args.get("space"))
        if new_title is None and new_content is None:
            space = await ctx.db.get(Space, item.space_id)
            folder = await ctx.db.get(Folder, item.folder_id) if item.folder_id else None
            return {
                "id": str(item.id),
                "title": item.title,
                "space_name": space.name if space else "",
                "folder_name": folder.name if folder else None,
                "url": item_url(item.id),
            }
    if new_content is not None:
        # Та же причина, что в create_note — ассистент не проходит через
        # paste в редакторе, ссылка сама по себе не станет карточкой без
        # этого шага.
        new_content = linkify_notes_content(str(new_content))

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
    # Заметка могла быть открыта с живой коллаборацией (Yjs) — её Y.Doc
    # ничего не знает про эту правку в обход WS-протокола, см.
    # collab.invalidate_room. Тот же баг, что уже был найден и закрыт для
    # фоновых воркеров (vision.py/pdf_processing.py/tickets.py), но не для
    # правок самого ассистента — реальный случай потери контента: заметку
    # редактировали и в браузере, и через ассистента одновременно.
    if content_changed:
        await collab.invalidate_room(item.id)
    result: dict[str, Any] = {"id": str(item.id), "title": item.title}
    if moving:
        space = await ctx.db.get(Space, item.space_id)
        result["space_name"] = space.name if space else ""
    return result


APPEND_TO_NOTE = ToolDefinition(
    name="append_to_note",
    description=(
        "Добавить текст В КОНЕЦ существующей заметки, не трогая то, что там уже есть. "
        "Безопаснее update_note для этого случая: не нужно самому копировать и печатать "
        "заново весь текущий текст, поэтому невозможно случайно что-то потерять при "
        "переписывании — картинку, вложение, старую запись. Используй для 'допиши/добавь "
        "к заметке X', особенно когда заметка уже содержит вложения (картинки/видео/аудио/"
        "файлы/билеты) или когда правишь её много раз подряд по чуть-чуть (например, лог "
        "тренировки — по подходу за раз). Для настоящего переписывания/удаления/"
        "реструктуризации уже существующего текста — update_note, не это."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "text": {"type": "string", "description": "Текст, который нужно добавить в конец заметки"},
        },
        "required": ["item_id", "text"],
    },
)


async def append_to_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    _require_note_like(item)
    # Реальный найденный баг: модель вызвала этот тул с параметром "content"
    # вместо "text" — перепутав со схемой соседнего update_note (у него
    # именно content). args.get("text", "") тихо давал "", тул отдавал
    # "Пустой текст для добавления — передай непустой text", а модель, ПОЛУЧИВ эту ошибку от тула,
    # всё равно доложила пользователю "Готово" — ничего не добавив. Раз
    # модель может недописать строгую форму (её слова), принимаем оба
    # имени параметра кодом, вместо того чтобы полагаться на промпт.
    text = str(args.get("text") or args.get("content") or "").strip()
    if not text:
        raise ToolError("Пустой текст для добавления — передай непустой text")

    ctx.db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=ctx.user_id))
    item.content = f"{item.content.rstrip()}\n\n{text}" if item.content.strip() else text

    await ctx.db.commit()
    await ctx.db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    # См. комментарий в update_note выше — та же причина.
    await collab.invalidate_room(item.id)
    return {"id": str(item.id), "title": item.title, "content": item.content}


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
        raise ToolError("Имя тега не может быть пустым — существующие теги даёт list_tags")

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
    description=(
        "Список спейсов пользователя (spaces — все, даже без папок) и папок во всех них — "
        "чтобы понимать, куда раскладывать заметки."
    ),
    parameters={"type": "object", "properties": {}},
)


async def list_folders(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.db.execute(
        select(Folder, Space.name)
        .join(Space, Space.id == Folder.space_id)
        .join(SpaceMember, SpaceMember.space_id == Folder.space_id)
        .where(SpaceMember.user_id == ctx.user_id, Space.is_vault.is_(False))
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
        ],
        # Спейс без единой папки иначе невидим: в списке папок ему просто
        # не из чего появиться, и модель не знала, что он есть.
        "spaces": [{"id": str(sp.id), "name": sp.name} for sp in await _user_spaces(ctx)],
    }


CREATE_FOLDER = ToolDefinition(
    name="create_folder",
    description=(
        "Создать новую папку. С parent_id — вложенная папка в спейсе родителя; иначе — в корне "
        "спейса space (название, «в семейном» → \"Семейный\") или текущего спейса диалога. Используй это, "
        "когда пользователь просит разложить заметки по папкам, а не только предполагай, что "
        "папка уже есть — сначала list_folders, и только если её правда нет, создавай."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Название папки"},
            "parent_id": {"type": "string", "description": "id родительской папки; не указывать — папка в корне"},
            "space": SPACE_PARAM,
        },
        "required": ["name"],
    },
)


async def create_folder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    # И "name", и "title" — тот же приём, что у append_to_note с
    # text/content, и по той же причине. Реальный случай (замер
    # 2026-09-05, сценарий воскресного ужина, оценка 1/5): модель дважды
    # подряд вызвала create_folder({"title": "Рецепты"}) и дважды получила
    # «Название папки не может быть пустым» — при том что название она
    # передала. Ошибка не в модели: create_note, create_table и
    # create_calendar_event ждут "title", и create_folder выбивается из
    # ряда единственный. Обобщение по трём соседним тулам — разумное
    # поведение, а не сбой, поэтому чиним схему, а не модель.
    name = str(args.get("name") or args.get("title") or "").strip()
    if not name:
        raise ToolError("Название папки не может быть пустым — придумай короткое по смыслу содержимого или спроси у пользователя через suggest_replies")

    # Родитель из ЛЮБОГО спейса пользователя, и папка создаётся там же.
    # Раньше родитель обязан был лежать в текущем спейсе диалога, и 19.10
    # модель восемь раз подряд получила «родительская папка не найдена» на
    # настоящую папку из «Семейного» — пока не кончились шаги.
    parent_id, space_id = await _resolve_folder(ctx, args.get("parent_id"), args.get("space"))

    folder = Folder(space_id=space_id, parent_id=parent_id, name=name)
    ctx.db.add(folder)
    await ctx.db.commit()
    await ctx.db.refresh(folder)
    await realtime.notify_space(folder.space_id, "folders")
    space = await ctx.db.get(Space, folder.space_id)
    return {
        "id": str(folder.id),
        "name": folder.name,
        "space_id": str(folder.space_id),
        "space_name": space.name if space else "",
    }


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
        Item.space_id == space_id, Item.material_type.in_(("note", "list", "ticket", "table")), Item.deleted_at.is_(None)
    )
    query = query.where(Item.folder_id == folder_id) if folder_id else query.where(Item.folder_id.is_(None))
    items = (await ctx.db.execute(query)).scalars().all()
    return {
        "items": [
            {"id": str(i.id), "title": i.title, "material_type": i.material_type, "url": item_url(i.id)} for i in items
        ]
    }


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
        "search_base: проверь подходящий тег в первую очередь, до серии вариаций полнотекстового "
        "запроса (почему это важно — см. инструкцию про search_base)."
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
        raise ToolError("tag_name обязателен — существующие теги даёт list_tags")

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
            Item.material_type.in_(("note", "list", "ticket", "table")),
            Item.deleted_at.is_(None),
            Space.is_vault.is_(False),
        )
        .order_by(Item.updated_at.desc())
    )
    return {
        "items": [
            {
                "id": str(i.id),
                "title": i.title,
                "material_type": i.material_type,
                "space_name": space_name,
                "url": item_url(i.id),
            }
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
        "и оцени, что подходит по смыслу, вместо того чтобы сообщать, что ничего не нашлось. "
        "Ссылок (url) здесь НЕТ намеренно — это перечисление заголовков, а не выдача: нашёл "
        "подходящее, вызови get_note/get_list по id, оттуда и возьмёшь ссылку."
    ),
    parameters={"type": "object", "properties": {}},
)


# БЮДЖЕТ В СИМВОЛАХ, А НЕ ЧИСЛО ЗАПИСЕЙ. Так пришлось сделать со второй
# попытки, и причина поучительная.
#
# Нашла дефект самопроверка на первом же прогоне: при лимите 200 записей
# и полях с url и space_id результат вырастал до 57 850 символов — больше
# потолка на один результат (30 000, dialog_tool_window.py). То есть он
# ОБРЕЗАЛСЯ, и на «просмотри заголовки сам, ты понимаешь смысл лучше
# поиска» модель видела половину базы, не зная об этом, и честно
# отвечала «не нашёл».
#
# Первая попытка была «убрать лишние поля и поднять лимит до 250» — и
# упала на тесте: с живыми названиями вроде «🐕 Marsz Kejterka уже в эту
# субботу в Познани» вышло 42 068 символов, снова больше потолка. Число
# записей НЕ УПРАВЛЯЕТ размером: названия бывают и в пять символов, и в
# шестьдесят.
#
# Поэтому набираем, пока не кончится бюджет, и честно говорим, сколько
# показали из сколько. Такой результат не обрежется никогда — а значит,
# модель всегда знает, полное перечисление она видит или нет.
_LIST_ALL_BUDGET_CHARS = 25_000

# Жёсткий потолок на число записей — чтобы не вытягивать из БД всё при
# базе на десятки тысяч заметок. Бюджет всё равно сработает раньше.
_LIST_ALL_MAX_ROWS = 2000


async def list_all_items(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.db.execute(
        select(Item, Space.name)
        .join(Space, Space.id == Item.space_id)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .where(
            SpaceMember.user_id == ctx.user_id,
            Item.material_type.in_(("note", "list", "ticket", "table")),
            Item.deleted_at.is_(None),
            # Сейф не должен даже засветиться в перечислении — не только
            # содержимое скрыто, сам факт его существования ассистенту
            # знать незачем.
            Space.is_vault.is_(False),
        )
        .order_by(Item.updated_at.desc())
        .limit(_LIST_ALL_MAX_ROWS)
    )
    rows = result.all()

    items: list[dict[str, Any]] = []
    spent = 0
    for item, space_name in rows:
        entry = {
            "id": str(item.id),
            "title": item.title,
            "material_type": item.material_type,
            "space_name": space_name,
        }
        # ~55 символов служебного JSON на запись (кавычки, ключи, запятые)
        # плюс сами значения. Считаем грубо и с запасом в свою сторону.
        cost = 55 + sum(len(str(v)) for v in entry.values())
        if items and spent + cost > _LIST_ALL_BUDGET_CHARS:
            break
        items.append(entry)
        spent += cost

    out: dict[str, Any] = {
        "items": items,
        # Явной строкой, а не только в описании тула: модель читает
        # результат внимательнее, чем описание, а выдумывание ссылок —
        # реальный найденный баг (см. системный промпт про «notenotes://»).
        "ссылок_здесь_нет": "Нужна ссылка на запись — вызови get_note/get_list по её id.",
    }
    if len(items) < len(rows):
        # Неполноту проговариваем, иначе модель скажет «в базе этого нет»,
        # посмотрев на урезанное перечисление.
        out["показано"] = f"{len(items)} из {len(rows)} — самые недавно изменённые"
        out["примечание"] = (
            "Перечисление неполное. Если нужного здесь нет, это НЕ значит, что его нет в базе: "
            "попробуй search_base другими словами или list_items_in_folder по подходящей папке."
        )
    return out
