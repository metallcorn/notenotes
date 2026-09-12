"""Файлы: посмотреть, прочитать, положить.

Дыра, найденная живой работой через MCP: по нему нельзя было ни скачать
файл из базы, ни отправить туда новый. При том что файлов 214 —
картинки, PDF, аудио, видео, — и у 183 из них текст УЖЕ извлечён (OCR
картинок, расшифровка видео, текстовый слой PDF). То есть самое ценное
лежало готовым и не отдавалось никому.

Инструментов нет было не только у MCP: у веб-ассистента и Telegram-бота
тоже. Ассистент мог найти заметку, в которую вставлен скан договора, но
не мог прочитать сам скан.

ПОЧЕМУ ТЕКСТ ВАЖНЕЕ БАЙТОВ. На вопрос «что в этом документе» ответ — это
текст, а не мегабайт base64: он короче, дешевле и уже посчитан.
Поэтому get_file отдаёт сначала извлечённый текст, и лишь для картинок
добавляет сами байты — их модель действительно умеет смотреть.

ПОТОЛОК ОБЯЗАТЕЛЕН. Загружать можно файлы до 300 МБ; такой файл не
пролезет ни в один ответ и просто взорвёт контекст на том конце. Поэтому
байты отдаются только в пределах лимита, а сверх него — честное
объяснение и ссылка для человека.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.deps import ensure_space_access, is_vault_space
from app.llm.base import ToolDefinition
from app.models import Item, Space, SpaceMember, Upload
from app.tools.registry import ToolContext, ToolError

# Сколько байтов файла готовы положить в ответ. Картинка на 4 МБ — это
# ~5.3 МБ base64, и это уже много для одного ответа; всё, что больше,
# почти наверняка не то, что человек хотел «посмотреть».
MAX_INLINE_BYTES = 4 * 1024 * 1024
# Столько принимаем на загрузку через инструмент. Не 300 МБ, как в вебе:
# здесь файл едет base64-строкой внутри аргументов вызова, и большой
# просто не доедет.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Извлечённый текст тоже режем: расшифровка часового видео — это десятки
# тысяч слов, и целиком она в ответе не нужна.
MAX_TEXT_CHARS = 20000


def _file_url(upload_id: uuid.UUID) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/uploads/{upload_id}"


def _path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


async def _accessible(ctx: ToolContext, upload: Upload) -> bool:
    """Файл из чужого спейса или из сейфа не отдаём.

    Сейф отдельно: его байты зашифрованы на клиенте, сервер их прочитать
    не может — отдать их модели значит отдать мусор и сделать вид, что
    это документ.
    """
    member = (
        await ctx.db.execute(
            select(SpaceMember.user_id).where(
                SpaceMember.space_id == upload.space_id, SpaceMember.user_id == ctx.user_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        return False
    return not await is_vault_space(ctx.db, upload.space_id)


LIST_FILES = ToolDefinition(
    name="list_files",
    description=(
        "Файлы пользователя: картинки, PDF, документы, аудио, видео. Ищи по СОДЕРЖИМОМУ "
        "через query: у картинок есть автоматическое описание того, что на них, у PDF и "
        "видео — извлечённый текст, и query ищет по всему этому плюс по имени файла. Просят "
        "«фото с жабой» — query=\"жаба\", а не листать всё подряд: файлов сотни, а без query "
        "отдаются только последние. С item_id — только вложения этой заметки. У каждого файла "
        "видно, извлечён ли текст: если да, читать его через get_file дёшево и быстро."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Что искать: слово из описания картинки, из текста документа или из имени файла",
            },
            "item_id": {"type": "string", "description": "id заметки — показать только её вложения"},
            "limit": {"type": "integer", "description": "Сколько показать, по умолчанию 20"},
        },
        "required": [],
    },
)


async def list_files(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = max(1, min(int(args.get("limit") or 20), 100))
    except (TypeError, ValueError):
        limit = 20

    query = (
        select(Upload)
        .join(SpaceMember, SpaceMember.space_id == Upload.space_id)
        .join(Space, Space.id == Upload.space_id)
        .where(SpaceMember.user_id == ctx.user_id, Space.is_vault.is_(False))
        .order_by(Upload.created_at.desc())
    )

    # Поиск по содержимому. Живой случай 12.09: «покажи фото с жабой» —
    # Клод взял list_files без запроса, получил 20 последних файлов,
    # просмотрел 8 картинок среди них и заключил, что жаб нет. А их четыре,
    # от 8 августа, с описанием «жаба» в transcript — в двадцатку они не
    # попали. Инструмент подталкивал к перебору вместо поиска.
    #
    # ILIKE, а не полнотекст: описания картинок короткие, слов там единицы,
    # и подстрока здесь точнее словаря — «жаб» найдёт и «жаба», и «жабы»,
    # а to_tsvector('simple') без морфологии не нашёл бы.
    needle = str(args.get("query") or "").strip()
    if needle:
        pattern = f"%{needle}%"
        query = query.where(Upload.transcript.ilike(pattern) | Upload.filename.ilike(pattern))
    query = query.limit(limit)

    raw_item_id = str(args.get("item_id") or "").strip()
    item: Item | None = None
    if raw_item_id:
        try:
            item = await ctx.db.get(Item, uuid.UUID(raw_item_id))
        except ValueError:
            raise ToolError(
                "Некорректный id заметки — это UUID из результата поиска, а не название. "
                "Если есть только название, найди заметку через search_base."
            )
        if item is None or item.deleted_at is not None:
            raise ToolError("Заметка не найдена — сначала найди её через search_base или list_all_items")
        await ensure_space_access(ctx.db, item.space_id, ctx.user_id)
        # Вложения заметки — те, чьи ссылки стоят в её тексте. Отдельной
        # связи «файл принадлежит заметке» в схеме нет: файл живёт в
        # спейсе, а в заметку попадает ссылкой (ТЗ §7 — картинки
        # отдельными файлами, не base64).
        query = (
            select(Upload)
            .where(Upload.space_id == item.space_id)
            .order_by(Upload.created_at.desc())
        )
        # needle и limit применяются ниже, после отбора по тексту заметки.

    uploads = (await ctx.db.execute(query)).scalars().all()
    if item is not None:
        content = item.content or ""
        uploads = [u for u in uploads if str(u.id) in content]
        if needle:
            low = needle.lower()
            uploads = [u for u in uploads if low in (u.transcript or "").lower() or low in u.filename.lower()]
        uploads = uploads[:limit]

    files = []
    for upload in uploads:
        path = _path(upload.id)
        has_text = bool((upload.transcript or "").strip())
        files.append({
            "id": str(upload.id),
            "filename": upload.filename,
            "content_type": upload.content_type,
            "size_bytes": path.stat().st_size if path.exists() else None,
            "text_extracted": has_text,
            # Статус нужен, чтобы модель не решила, будто текста нет
            # вовсе, когда он просто ещё считается.
            "processing": upload.transcription_status if upload.transcription_status not in ("none", "done") else None,
            "url": _file_url(upload.id),
        })
    return {"files": files}


GET_FILE = ToolDefinition(
    name="get_file",
    description=(
        "Прочитать файл и получить его содержимое. Отдаёт извлечённый текст (OCR картинки, "
        "расшифровку речи, текстовый слой PDF) И САМ ФАЙЛ: картинку — чтобы рассмотреть, "
        "остальное — блоком resource, который можно сохранить или передать пользователю. "
        "Поле url — прямая ссылка НА САМ ФАЙЛ (не на заметку): по ней он открывается и "
        "скачивается, её и давай человеку, если он просит файл. Слишком большие файлы "
        "приходят только ссылкой. Отвечая по содержимому, ссылайся на файл, а не выдавай за "
        "своё знание."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "id файла из list_files"},
        },
        "required": ["file_id"],
    },
)


async def get_file(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    raw_id = str(args.get("file_id", "")).strip()
    try:
        upload = await ctx.db.get(Upload, uuid.UUID(raw_id))
    except ValueError:
        raise ToolError("Некорректный id файла — это UUID из результата list_files, а не имя файла")
    if upload is None or not await _accessible(ctx, upload):
        raise ToolError("Файл не найден — сначала посмотри список через list_files")

    result: dict[str, Any] = {
        "id": str(upload.id),
        "filename": upload.filename,
        "content_type": upload.content_type,
        "url": _file_url(upload.id),
    }

    text = (upload.transcript or "").strip()
    if text:
        result["text"] = text[:MAX_TEXT_CHARS]
        result["text_truncated"] = len(text) > MAX_TEXT_CHARS
    elif upload.transcription_status == "pending":
        result["note"] = "Текст из файла ещё извлекается — попробуй через минуту"

    path = _path(upload.id)
    if not path.exists():
        result["note"] = "Файл есть в базе, но его содержимое недоступно"
        return result

    size = path.stat().st_size
    result["size_bytes"] = size

    # Сами байты. Живой случай: человек попросил Клода прислать скан
    # паспорта, и тот ответил «нет инструмента для передачи вложений» —
    # потому что первая версия отдавала байты ТОЛЬКО для картинок. У PDF
    # возвращался текст и ссылка, то есть сохранить файл клиент не мог
    # физически.
    #
    # Теперь отдаём любой файл в пределах лимита, но РАЗНЫМИ блоками, и
    # это не формальность:
    #   * картинка — блоком image: модель её действительно рассматривает;
    #   * остальное — блоком resource: клиент может сохранить файл на диск
    #     или предложить человеку скачать, а модель не пытается «читать»
    #     двоичное содержимое.
    if size <= MAX_INLINE_BYTES:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        if upload.content_type.startswith("image/"):
            result["_mcp_image"] = {"data": encoded, "mime_type": upload.content_type}
        else:
            result["_mcp_resource"] = {
                "data": encoded,
                "mime_type": upload.content_type,
                "filename": upload.filename,
                "uri": _file_url(upload.id),
            }
    else:
        result["note"] = (
            f"Файл большой ({size // (1024 * 1024)} МБ), целиком не отдаю — "
            f"дай пользователю прямую ссылку: {_file_url(upload.id)}"
        )
    return result


UPLOAD_FILE = ToolDefinition(
    name="upload_file",
    description=(
        "Положить файл в базу пользователя. Содержимое передаётся строкой base64. Годится для "
        "документов, картинок и текстовых файлов разумного размера; большие файлы пользователь "
        "загружает сам через приложение. Если указан item_id, файл добавляется ссылкой в конец "
        "этой заметки — иначе просто кладётся в спейс и возвращает ссылку. Картинки и PDF после "
        "загрузки автоматически распознаются, текст появится через некоторое время."
    ),
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Имя файла с расширением"},
            "content_base64": {"type": "string", "description": "Содержимое файла в base64"},
            "item_id": {"type": "string", "description": "id заметки, в которую добавить ссылку"},
        },
        "required": ["filename", "content_base64"],
    },
)


async def upload_file(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import mimetypes
    from io import BytesIO

    from fastapi import UploadFile as FastAPIUploadFile
    from starlette.datastructures import Headers

    from app.models import User
    from app.routers.uploads import create_upload

    filename = str(args.get("filename", "")).strip()
    if not filename:
        raise ToolError("Нужно имя файла с расширением — по нему определяется тип")

    raw = str(args.get("content_base64", "")).strip()
    if not raw:
        raise ToolError(
            "Нужно содержимое файла строкой base64 — прочитай файл и передай его "
            "в поле content_base64"
        )
    try:
        # validate=True: иначе base64 молча проглатывает мусор и на диск
        # ложится обрезанный файл, который потом не открывается.
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise ToolError("Содержимое не разобралось как base64 — передай файл целиком, без переносов и пробелов")
    if not data:
        raise ToolError("Файл пустой — проверь, что прочитал его целиком, и передай содержимое заново")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ToolError(
            f"Файл больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ — такой пользователь загружает "
            "сам через приложение, через этот канал он не доедет"
        )

    target_space = ctx.space_id
    item: Item | None = None
    raw_item_id = str(args.get("item_id") or "").strip()
    if raw_item_id:
        try:
            item = await ctx.db.get(Item, uuid.UUID(raw_item_id))
        except ValueError:
            raise ToolError("Некорректный id заметки — это UUID из результата поиска, а не название")
        if item is None or item.deleted_at is not None:
            raise ToolError("Заметка не найдена — сначала найди её через search_base")
        await ensure_space_access(ctx.db, item.space_id, ctx.user_id)
        target_space = item.space_id

    if await is_vault_space(ctx.db, target_space):
        raise ToolError("В зашифрованный сейф загружать нельзя — он шифруется на стороне пользователя")

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    # Зовём НАСТОЯЩИЙ обработчик загрузки, а не повторяем его. В нём
    # текстовый слой PDF, превью, миниатюры, постановка в очередь OCR и
    # проверка сейфа — переписать это здесь значило бы завести вторую
    # копию, которая разойдётся с первой при первой же правке.
    upload_file_obj = FastAPIUploadFile(
        file=BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )
    user = await ctx.db.get(User, ctx.user_id)
    created = await create_upload(space_id=target_space, file=upload_file_obj, user=user, db=ctx.db)

    result = {
        "id": str(created.id),
        "filename": created.filename,
        "content_type": created.content_type,
        "url": _file_url(created.id),
        "size_bytes": len(data),
    }

    if item is not None:
        # Markdown-ссылка, картинка — как картинка. Формат хранения заметок
        # всегда Markdown (CLAUDE.md), файл — ссылкой, не base64.
        link = f"![{created.filename}](/api/uploads/{created.id})" if content_type.startswith("image/") \
            else f"[{created.filename}](/api/uploads/{created.id})"
        item.content = f"{(item.content or '').rstrip()}\n\n{link}\n"
        await ctx.db.flush()
        result["added_to_note"] = item.title or "Без названия"

    return result
