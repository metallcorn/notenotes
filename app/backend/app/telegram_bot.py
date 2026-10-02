from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import realtime
from app import daily_digest
from app.asr.factory import asr_available, get_asr_client
from app.core.config import get_settings
from app.db import async_session
from app.models import Folder, Item, Space, SpaceMember, TelegramLink, TelegramLinkCode, Upload, User
from app.note_formatting import linkify_notes_content
from app.routers.calendar import build_ics
from app.pdf_processing import AUTO_OCR_MAX_PDF_BYTES
from app.pdf_processing import enqueue_ocr as enqueue_pdf_ocr
from app.pdf_processing import extract_text as extract_pdf_text
from app.pdf_processing import serialize_document_attachment
from app.routers.dialogs import run_dialog_turn
from app.routers.items import create_item_row
from app.routers.uploads import _extract_text_preview
from app.transcription import enqueue_transcription
from app.transcription import placeholder_text as video_placeholder_text
from app.vision import enqueue_vision
from app.vision import placeholder_text as image_placeholder_text

logger = logging.getLogger(__name__)

# Telegram-бот как канал захвата заметок (ТЗ, Фаза 2 «Каналы») — обычный
# Bot API с вебхуком, не MTProto (MTProto — Фаза 3, доступ к каналам
# пользователя, отдельная и более рискованная задача). Прямой httpx, без
# SDK вроде aiogram — тот же стиль, что у Mistral/Deepgram/Tavily-клиентов
# в этом проекте. Один воркер на очереди — та же причина, что у
# vision.py/transcription.py: сериализовать вызовы Mistral/Deepgram, не
# жечь лимиты, если пользователь разом форварднёт кучу сообщений.
_queue: "asyncio.Queue[dict]" = asyncio.Queue()

TELEGRAM_API_BASE = "https://api.telegram.org"
# Жёсткий потолок самого Bot API на getFile — не наше решение, файлы
# больше этого размера бот технически не может скачать никаким способом.
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

# Альбом (несколько фото/видео одним постом) Telegram присылает как
# ОТДЕЛЬНЫЙ апдейт на каждый файл — общее у них только media_group_id, и
# явного сигнала "это последний" нет. Буферизуем в памяти и по debounce'у
# (ничего нового для этой группы N секунд) считаем группу завершённой и
# собираем ОДНУ заметку. Живёт в памяти воркер-процесса — как и остальные
# очереди в этом модуле, не переживает рестарт, что приемлемо для окна
# в пару секунд.
_media_groups: dict[str, dict] = {}
_MEDIA_GROUP_DEBOUNCE_SECONDS = 1.5

# Пересланное вручную ("выделить несколько сообщений → переслать") тоже
# приходит отдельным апдейтом на каждое сообщение, но БЕЗ media_group_id —
# он есть только у альбомов (фото/видео/документы, изначально отправленных
# одним постом). Общего "id пачки" для остальных форвардов Bot API не даёт
# вовсе, поэтому буферизуем сами — по (chat_id, автор пересылки), тем же
# debounce-приёмом, что и альбомы, но с чуть большим окном (несколько
# сообщений, разосланных вручную, могут прилетать c бОльшим разбросом по
# времени, чем файлы одного альбома).
_forward_batches: dict[str, dict] = {}
_FORWARD_BATCH_DEBOUNCE_SECONDS = 2.5


def _api_url(method: str) -> str:
    return f"{TELEGRAM_API_BASE}/bot{get_settings().telegram_bot_token}/{method}"


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def enqueue_update(update: dict) -> None:
    _queue.put_nowait(update)


_MARKDOWN_MARKS_RE = re.compile(r"[*_`~]")
# text_link-сущности от _entities_to_markdown иногда попадают в начало
# сообщения (например, эмодзи-ссылка на превью в репост-ботах) — ![alt](url)
# или [text](url) целиком заменяем на alt/text, а не оставляем скобки и URL
# видимыми в названии заметки. Пустой alt (обычная картинка ![](url)) даёт
# пустую строку — та же логика "пустая строка не годится в заголовок" ниже
# просто переходит на следующую строку контента.
_MARKDOWN_LINK_OR_IMAGE_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")

def _derive_title(text: str, fallback: str = "") -> str:
    """Заметки из Telegram создавались без названия ("Без названия" в UI) —
    берём первую непустую строку контента, как заголовок пользователь чаще
    всего и держит там сам. lstrip("#") — заголовок markdown ("# Рецепт
    борща") решётке в названии заметки не нужен; сама строка уже могла
    получить **bold**/_italic_/`code`/[ссылки](url) от _entities_to_markdown
    — эта разметка тоже убирается, в названии заметки она не нужна, только
    мусор (скобки, звёздочки, голый URL)."""
    for line in text.splitlines():
        candidate = line.strip().lstrip("#")
        candidate = _MARKDOWN_LINK_OR_IMAGE_RE.sub(lambda m: m.group(1), candidate)
        stripped = _MARKDOWN_MARKS_RE.sub("", candidate).strip()
        if stripped:
            return stripped[:80]
    return fallback


# Форматирование Telegram (жирный, курсив, ссылки и т.д.) приходит не
# инлайновым markdown в самом тексте, а отдельным списком entities
# (offset/length в UTF-16 code units — ЛЕГКО ошибиться на эмодзи и подобных
# символах вне BMP, если считать по Python-индексам строки, поэтому режем
# по закодированным в UTF-16 code unit'ам, как считает сам Telegram).
_ENTITY_MARKDOWN_WRAP = {"bold": "**", "italic": "_", "code": "`", "strikethrough": "~~", "underline": "__"}


def _entities_to_markdown(text: str, entities: list[dict] | None) -> str:
    if not entities or not text:
        return text

    units = text.encode("utf-16-le")
    total_units = len(units) // 2

    def unit_slice(start: int, end: int) -> str:
        return units[start * 2 : end * 2].decode("utf-16-le")

    # Пересекающиеся сущности (например, одновременно bold+italic на одном
    # спане) — редкий случай для обычной переписки; берём первую по offset
    # и не пытаемся вкладывать разметку друг в друга.
    entities_sorted = sorted(entities, key=lambda e: e["offset"])

    parts: list[str] = []
    cursor = 0
    for e in entities_sorted:
        offset, length = e["offset"], e["length"]
        if offset < cursor:
            continue
        parts.append(unit_slice(cursor, offset))
        segment = unit_slice(offset, offset + length)
        etype = e.get("type")
        if etype in _ENTITY_MARKDOWN_WRAP:
            wrap = _ENTITY_MARKDOWN_WRAP[etype]
            parts.append(f"{wrap}{segment}{wrap}")
        elif etype == "text_link" and e.get("url"):
            # Скобки в ТЕКСТЕ ссылки ломают разметку: «[смотри [тут]]»
            # разъезжается, и в заметке остаётся мусор вместо ссылки. Тот же
            # класс, что \Z в подстановке распознанного текста — чужой текст
            # попадает туда, где символы что-то значат.
            #
            # URL сознательно НЕ трогаем. Закрывающая скобка в адресе
            # (википедия) теоретически обрывает ссылку, но лечение — обернуть
            # в <>, а поддержку этой формы нашим редактором я не проверял.
            # Риск сломать ВСЕ ссылки из Telegram ради редкого случая
            # несоразмерен; отдельная задача, если всплывёт живьём.
            label = segment.replace("[", "\\[").replace("]", "\\]")
            parts.append(f"[{label}]({e['url']})")
        elif etype == "pre":
            parts.append(f"\n```{e.get('language', '')}\n{segment}\n```\n")
        else:
            parts.append(segment)
        cursor = offset + length
    parts.append(unit_slice(cursor, total_units))
    return "".join(parts)


async def register_webhook() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    url = f"{settings.public_base_url}/api/telegram/webhook"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                _api_url("setWebhook"),
                json={
                    "url": url,
                    "secret_token": settings.telegram_webhook_secret,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error("Не удалось зарегистрировать Telegram webhook: %s", data)

            # /new в меню бота (иконка "/" в клиенте) — чтобы не приходилось
            # помнить команду наизусть.
            resp = await client.post(
                _api_url("setMyCommands"),
                json={"commands": [{"command": "new", "description": "Начать новый диалог с ассистентом"}]},
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error("Не удалось зарегистрировать команды Telegram-бота: %s", data)
        except Exception:
            logger.exception("Ошибка при регистрации Telegram webhook")


async def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    payload: dict = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(_api_url("sendMessage"), json=payload)
        except Exception:
            logger.exception("Не удалось отправить сообщение в Telegram chat_id=%s", chat_id)


async def edit_message(chat_id: int, message_id: int, text: str, reply_markup: dict | None = None) -> None:
    """Перерисовать уже отправленное сообщение — текст и кнопки разом.

    Нужно утренней сводке: нажал «сделано» — пункт и его кнопка исчезают
    из ТОГО ЖЕ сообщения, а не копятся ответами «убрано» под ним.
    """
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    payload: dict = {"chat_id": chat_id, "message_id": message_id, "text": text}
    # Пустая клавиатура — явно: без reply_markup Telegram оставит старые
    # кнопки, и закрытый пункт можно было бы «закрыть» ещё раз.
    payload["reply_markup"] = reply_markup or {"inline_keyboard": []}
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(_api_url("editMessageText"), json=payload)
        except Exception:
            logger.exception("Не удалось отредактировать сообщение в Telegram chat_id=%s", chat_id)


async def delete_message(chat_id: int, message_id: int) -> None:
    """Убрать сообщение из чата. Сводка, в которой закрыли всё, не должна
    висеть — по просьбе владельца: неактуальное удаляется, актуальное
    остаётся."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(_api_url("deleteMessage"), json={"chat_id": chat_id, "message_id": message_id})
        except Exception:
            logger.exception("Не удалось удалить сообщение в Telegram chat_id=%s", chat_id)


async def send_photo(chat_id: int, photo_url: str) -> None:
    # photo — обычная URL-строка, Telegram сам её скачивает на своей
    # стороне (тот же приём, что для link-preview у обычных ссылок) — не
    # нужно самим качать/заливать байты картинки.
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(_api_url("sendPhoto"), json={"chat_id": chat_id, "photo": photo_url})
        except Exception:
            logger.exception("Не удалось отправить фото в Telegram chat_id=%s", chat_id)


async def send_media_group(chat_id: int, photo_urls: list[str]) -> None:
    # Без caption на группе — у sendMediaGroup общий лимит подписи на всё
    # альбом сразу, а не на каждую картинку, проще и безопаснее прислать
    # текстовый ответ отдельным сообщением следом (см. _handle_assistant_message).
    settings = get_settings()
    if not settings.telegram_bot_token or not photo_urls:
        return
    media = [{"type": "photo", "media": url} for url in photo_urls[:10]]
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(_api_url("sendMediaGroup"), json={"chat_id": chat_id, "media": media})
        except Exception:
            logger.exception("Не удалось отправить альбом в Telegram chat_id=%s", chat_id)


async def send_document_bytes(chat_id: int, filename: str, content: bytes, mime_type: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(
                _api_url("sendDocument"),
                data={"chat_id": str(chat_id)},
                files={"document": (filename, content, mime_type)},
            )
        except Exception:
            logger.exception("Не удалось отправить файл в Telegram chat_id=%s", chat_id)


async def answer_callback_query(callback_query_id: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(_api_url("answerCallbackQuery"), json={"callback_query_id": callback_query_id})
        except Exception:
            logger.exception("Не удалось подтвердить callback_query %s", callback_query_id)


async def _download_file(file_id: str) -> tuple[bytes, str] | None:
    """(содержимое, telegram file_path) или None, если файл больше 20 МБ —
    жёсткий потолок Bot API на getFile."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(_api_url("getFile"), params={"file_id": file_id})
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            logger.error("getFile не удался для %s: %s", file_id, data)
            return None
        result = data["result"]
        file_size = result.get("file_size", 0)
        if file_size and file_size > _MAX_DOWNLOAD_BYTES:
            return None
        file_path = result["file_path"]
        download_url = f"{TELEGRAM_API_BASE}/file/bot{settings.telegram_bot_token}/{file_path}"
        dl_resp = await client.get(download_url)
        dl_resp.raise_for_status()
        return dl_resp.content, file_path


async def _save_upload(
    db: AsyncSession, space_id: uuid.UUID, author_id: uuid.UUID, content: bytes, filename: str, content_type: str
) -> Upload:
    upload = Upload(space_id=space_id, author_id=author_id, filename=filename, content_type=content_type)
    db.add(upload)
    await db.flush()
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    _upload_path(upload.id).write_bytes(content)
    return upload


def _forward_sender_name(message: dict) -> str | None:
    """Автор пересланного сообщения — под этим именем создаётся/переиспользуется
    папка в Telegram-спейсе. Bot API 7.0+ даёт forward_origin (user/hidden_user/
    chat/channel — разная форма под каждый тип), более старые клиенты —
    forward_from/forward_from_chat/forward_sender_name (последнее — когда
    исходный автор скрыл атрибуцию форварда). Пробуем оба формата; None —
    не удалось определить (например, forward_date есть, а остальных полей
    нет — тоже бывает), тогда заметка остаётся в корне спейса, без папки."""
    origin = message.get("forward_origin")
    if origin:
        origin_type = origin.get("type")
        if origin_type == "user":
            u = origin.get("sender_user") or {}
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            if name:
                return name
        elif origin_type == "hidden_user":
            if origin.get("sender_user_name"):
                return origin["sender_user_name"]
        elif origin_type == "chat":
            chat = origin.get("sender_chat") or {}
            if chat.get("title"):
                return chat["title"]
        elif origin_type == "channel":
            chat = origin.get("chat") or {}
            if chat.get("title"):
                return chat["title"]

    forward_from = message.get("forward_from")
    if forward_from:
        name = f"{forward_from.get('first_name', '')} {forward_from.get('last_name', '')}".strip()
        if name:
            return name

    forward_from_chat = message.get("forward_from_chat")
    if forward_from_chat and forward_from_chat.get("title"):
        return forward_from_chat["title"]

    if message.get("forward_sender_name"):
        return message["forward_sender_name"]

    return None


async def _get_or_create_folder(db: AsyncSession, space_id: uuid.UUID, name: str) -> tuple[uuid.UUID, bool]:
    name = name.strip()[:255]
    existing = (
        await db.execute(
            select(Folder).where(Folder.space_id == space_id, Folder.parent_id.is_(None), Folder.name == name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id, False
    folder = Folder(space_id=space_id, parent_id=None, name=name)
    db.add(folder)
    await db.flush()
    return folder.id, True


async def _handle_start(chat_id: int, text: str) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await send_message(chat_id, "Чтобы подключить аккаунт, сгенерируйте ссылку в настройках приложения Notenotes.")
        return
    code = parts[1].strip()

    async with async_session() as db:
        by_chat = (await db.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).scalar_one_or_none()
        if by_chat is not None:
            await send_message(chat_id, "Этот Telegram-аккаунт уже подключён к Notenotes.")
            return

        link_code = await db.get(TelegramLinkCode, code)
        now = datetime.now(timezone.utc)
        if link_code is None or link_code.expires_at < now:
            if link_code is not None:
                await db.delete(link_code)
                await db.commit()
            await send_message(chat_id, "Код недействителен или устарел. Сгенерируйте новую ссылку в настройках приложения.")
            return

        user_id = link_code.user_id
        await db.delete(link_code)

        existing = await db.get(TelegramLink, user_id)
        if existing is not None:
            await db.commit()
            await send_message(
                chat_id, "К вашему аккаунту Notenotes уже привязан другой Telegram — сначала отключите его в настройках."
            )
            return

        space = Space(name="Telegram", owner_id=user_id)
        db.add(space)
        await db.flush()
        db.add(SpaceMember(space_id=space.id, user_id=user_id))
        db.add(TelegramLink(user_id=user_id, chat_id=chat_id, space_id=space.id))
        await db.commit()

    await send_message(chat_id, "Готово! Теперь всё, что вы присылаете сюда, будет сохраняться в Notenotes как заметки.")


async def _handle_photo(db: AsyncSession, message: dict, space_id: uuid.UUID, author_id: uuid.UUID) -> None:
    photos = message.get("photo") or []
    if not photos:
        return
    largest = max(photos, key=lambda p: p.get("file_size", 0))
    result = await _download_file(largest["file_id"])
    if result is None:
        await create_item_row(
            db,
            space_id=space_id,
            author_id=author_id,
            material_type="note",
            content="🖼 Фото больше 20 МБ — Telegram Bot API не отдаёт такие файлы, сохранить не удалось.",
        )
        return
    content_bytes, file_path = result
    filename = file_path.rsplit("/", 1)[-1]
    upload = await _save_upload(db, space_id, author_id, content_bytes, filename, "image/jpeg")
    # Реальный найденный баг: enqueue_vision кладёт upload_id только в
    # процесс-локальную очередь в памяти — если рестарт/деплой случится ДО
    # того, как воркер реально начал обработку, задача теряется молча, а
    # transcription_status всё ещё "none" (не "pending"/"processing"), так
    # что resume_pending() при старте её не находит и не переставляет в
    # очередь — плейсхолдер "обрабатывается…" остаётся навсегда.
    upload.transcription_status = "pending"
    placeholder = image_placeholder_text(upload.id)
    caption = _entities_to_markdown(message.get("caption", ""), message.get("caption_entities"))
    body = f"{caption}\n\n" if caption else ""
    content = f"{body}![](/api/uploads/{upload.id})\n\n{placeholder}\n"
    title = _derive_title(caption, fallback="Фото")
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", title=title, content=content)
    enqueue_vision(upload.id)


async def _handle_video(db: AsyncSession, message: dict, space_id: uuid.UUID, author_id: uuid.UUID) -> None:
    video = message["video"]
    file_size = video.get("file_size", 0)
    if file_size and file_size > _MAX_DOWNLOAD_BYTES:
        mb = file_size / (1024 * 1024)
        await create_item_row(
            db,
            space_id=space_id,
            author_id=author_id,
            material_type="note",
            content=(
                f"🎥 Видео ({mb:.0f} МБ) — Telegram Bot API не отдаёт файлы больше 20 МБ, сохранить не удалось. "
                "Само сообщение осталось у вас в чате с ботом в Telegram."
            ),
        )
        return
    result = await _download_file(video["file_id"])
    if result is None:
        await create_item_row(
            db,
            space_id=space_id,
            author_id=author_id,
            material_type="note",
            content="🎥 Видео больше 20 МБ — Telegram Bot API не отдаёт такие файлы, сохранить не удалось.",
        )
        return
    content_bytes, file_path = result
    filename = file_path.rsplit("/", 1)[-1]
    mime_type = video.get("mime_type", "video/mp4")
    upload = await _save_upload(db, space_id, author_id, content_bytes, filename, mime_type)
    # Тот же баг, что и у _handle_photo выше — resume_pending() ищет
    # "pending"/"processing", а не дефолтный "none".
    upload.transcription_status = "pending"
    placeholder = video_placeholder_text(upload.id)
    caption = _entities_to_markdown(message.get("caption", ""), message.get("caption_entities"))
    body = f"{caption}\n\n" if caption else ""
    content = (
        f'{body}<video src="/api/uploads/{upload.id}" controls preload="metadata" '
        f'style="max-width: 100%; max-height: 70vh;"></video>\n\n{placeholder}\n'
    )
    title = _derive_title(caption, fallback="Видео")
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", title=title, content=content)
    enqueue_transcription(upload.id)


async def _handle_document(db: AsyncSession, message: dict, space_id: uuid.UUID, author_id: uuid.UUID) -> None:
    document = message["document"]
    filename = document.get("file_name", "файл")
    file_size = document.get("file_size", 0)
    if file_size and file_size > _MAX_DOWNLOAD_BYTES:
        mb = file_size / (1024 * 1024)
        await create_item_row(
            db,
            space_id=space_id,
            author_id=author_id,
            material_type="note",
            content=f"📎 Файл «{filename}» ({mb:.0f} МБ) — больше 20 МБ, Telegram Bot API не отдаёт такие файлы.",
        )
        return
    result = await _download_file(document["file_id"])
    if result is None:
        await create_item_row(
            db,
            space_id=space_id,
            author_id=author_id,
            material_type="note",
            content=f"📎 Файл «{filename}» — больше 20 МБ, сохранить не удалось.",
        )
        return
    content_bytes, _file_path = result
    mime_type = document.get("mime_type", "application/octet-stream")
    upload = await _save_upload(db, space_id, author_id, content_bytes, filename, mime_type)
    caption = _entities_to_markdown(message.get("caption", ""), message.get("caption_entities"))
    body = f"{caption}\n\n" if caption else ""
    attachment_url = f"/api/uploads/{upload.id}"

    # PDF: текстовый слой вытаскиваем сразу — быстро, локально, бесплатно
    # (PyMuPDF, без сети). Реальная жалоба: раньше на время распознавания
    # (и текстового слоя — теперь он тоже причёсывается LLM-reflow'ом, см.
    # document_reflow.py, — и сканов) карточка файла целиком заменялась
    # отдельным текстовым плейсхолдером, пользователь терял доступ к
    # самому файлу до конца обработки. Теперь карточка вставляется сразу
    # (processing=True вместо отдельного плейсхолдера) — backend меняет
    # только этот флаг на готовый текст, url/filename никуда не деваются.
    pdf_ocr_queued = False
    is_pdf = mime_type == "application/pdf" or filename.lower().endswith(".pdf")
    if is_pdf:
        text_layer = extract_pdf_text(content_bytes)
        user = await db.get(User, author_id)
        auto = user is not None and user.auto_process_uploads
        if auto and (text_layer or len(content_bytes) <= AUTO_OCR_MAX_PDF_BYTES):
            content = f"{body}{serialize_document_attachment(attachment_url, filename, '', processing=True)}\n"
            pdf_ocr_queued = True
        elif text_layer:
            content = f"{body}{serialize_document_attachment(attachment_url, filename, text_layer)}\n"
        else:
            content = f"{body}{serialize_document_attachment(attachment_url, filename, '')}\n"
    else:
        # Реальная жалоба: docx/xlsx/pptx, присланные в Telegram, никогда не
        # распознавались — извлечение текста для этих форматов (python-docx/
        # openpyxl/python-pptx) уже было реализовано, но только для файлов,
        # загруженных через веб (routers/uploads.py::_extract_text_preview),
        # бот писал файл напрямую в обход этого кода. Тот же экстрактор,
        # тот же путь на диске (_upload_path — локальная копия в этом
        # модуле, но ссылается на тот же upload_dir/<id>, что и общий).
        text_preview = None
        try:
            text_preview = _extract_text_preview(_upload_path(upload.id), mime_type, filename)
        except Exception:
            logger.exception("Не удалось извлечь текст из %s (Telegram, id=%s)", filename, upload.id)
        content = f"{body}{serialize_document_attachment(attachment_url, filename, text_preview or '')}\n"

    title = _derive_title(caption, fallback=filename)
    item = await create_item_row(
        db, space_id=space_id, author_id=author_id, material_type="note", title=title, content=content
    )
    if pdf_ocr_queued:
        upload.transcription_status = "pending"
        await db.commit()
        enqueue_pdf_ocr(upload.id)


def _buffer_media_group_message(message: dict, group_id: str, chat_id: int) -> None:
    group = _media_groups.setdefault(group_id, {"messages": [], "chat_id": chat_id})
    group["messages"].append(message)
    group["last_seen"] = time.monotonic()
    if len(group["messages"]) == 1:
        _schedule_media_group_flush(group_id)


def _schedule_media_group_flush(group_id: str) -> None:
    async def _later() -> None:
        await asyncio.sleep(_MEDIA_GROUP_DEBOUNCE_SECONDS)
        enqueue_update({"_media_group_flush": group_id})

    asyncio.create_task(_later())


async def _flush_media_group(group_id: str) -> None:
    group = _media_groups.get(group_id)
    if group is None:
        return
    # Что-то прилетело в группу уже после того, как этот таймер был
    # запущен — ждём ещё, а не режем альбом на середине.
    if time.monotonic() - group["last_seen"] < _MEDIA_GROUP_DEBOUNCE_SECONDS - 0.05:
        _schedule_media_group_flush(group_id)
        return

    del _media_groups[group_id]
    messages = group["messages"]
    chat_id = group["chat_id"]

    first = messages[0]
    is_forwarded = "forward_origin" in first or "forward_date" in first
    sender_name = _forward_sender_name(first) if is_forwarded else None

    async with async_session() as db:
        link = (await db.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).scalar_one_or_none()
        if link is None:
            return
        try:
            saved = await _handle_forward_batch(db, messages, link.space_id, link.user_id, sender_name)
        except Exception:
            # Тот же принцип, что в _process — падение здесь раньше было
            # полностью тихим (альбом просто исчезал), теперь хотя бы ответ
            # в чат, чтобы отправитель знал, что что-то пошло не так.
            logger.exception("Не удалось обработать альбом из Telegram (chat_id=%s)", chat_id)
            await send_message(chat_id, "⚠️ Не получилось сохранить альбом. Попробуйте отправить ещё раз.")
            return

    if saved:
        await send_message(chat_id, "Сохранено ✅")


def _buffer_forward_message(message: dict, chat_id: int, sender_name: str | None) -> None:
    key = f"{chat_id}:{sender_name or ''}"
    batch = _forward_batches.setdefault(key, {"messages": [], "chat_id": chat_id, "sender_name": sender_name})
    batch["messages"].append(message)
    batch["last_seen"] = time.monotonic()
    if len(batch["messages"]) == 1:
        _schedule_forward_batch_flush(key)


def _schedule_forward_batch_flush(key: str) -> None:
    async def _later() -> None:
        await asyncio.sleep(_FORWARD_BATCH_DEBOUNCE_SECONDS)
        enqueue_update({"_forward_batch_flush": key})

    asyncio.create_task(_later())


async def _flush_forward_batch(key: str) -> None:
    batch = _forward_batches.get(key)
    if batch is None:
        return
    if time.monotonic() - batch["last_seen"] < _FORWARD_BATCH_DEBOUNCE_SECONDS - 0.05:
        _schedule_forward_batch_flush(key)
        return

    del _forward_batches[key]
    messages = batch["messages"]
    chat_id = batch["chat_id"]
    sender_name = batch["sender_name"]

    async with async_session() as db:
        link = (await db.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).scalar_one_or_none()
        if link is None:
            return
        try:
            saved = await _handle_forward_batch(db, messages, link.space_id, link.user_id, sender_name)
        except Exception:
            # Тот же принцип, что в _flush_media_group/_process — самый
            # вероятный путь для пересланного документа (реальная жалоба):
            # раньше падение здесь оставляло отправителя без единого
            # признака, что сообщение вообще дошло.
            logger.exception("Не удалось обработать пересланные сообщения из Telegram (chat_id=%s)", chat_id)
            await send_message(chat_id, "⚠️ Не получилось сохранить пересланное сообщение. Попробуйте отправить ещё раз.")
            return

    if saved:
        await send_message(chat_id, "Сохранено ✅")


async def _handle_forward_batch(
    db: AsyncSession,
    messages: list[dict],
    space_id: uuid.UUID,
    author_id: uuid.UUID,
    sender_name: str | None,
) -> bool:
    """Несколько сообщений одним постом (альбом, media_group_id) ИЛИ
    несколько сообщений, пересланных вручную одним действием (без
    media_group_id — буферизуются отдельно, см. _buffer_forward_message) —
    в обоих случаях одна заметка со всеми частями по порядку, а не заметка
    на сообщение. sender_name задан только когда пачка пришла форвардом
    (папка по автору пересылки создаётся/переиспользуется здесь же); прямой
    альбом от самого пользователя — как раньше, без папки.

    Побочные эффекты (enqueue_vision/enqueue_transcription/enqueue_pdf_ocr)
    откладываются до после итоговой заметки: пока идёт сборка, upload-записи
    только flush'нуты, не закоммичены — воркер, дёрнутый раньше времени, не
    найдёт их в БД."""
    folder_id: uuid.UUID | None = None
    folder_created = False
    if sender_name:
        folder_id, folder_created = await _get_or_create_folder(db, space_id, sender_name)

    deferred: list[tuple] = []
    parts: list[str] = []
    title = ""
    for m in messages:
        if m.get("text"):
            formatted = _entities_to_markdown(m["text"], m.get("entities"))
            if not title:
                title = _derive_title(formatted)
            parts.append(linkify_notes_content(formatted))
        elif "photo" in m:
            photos = m["photo"]
            largest = max(photos, key=lambda p: p.get("file_size", 0))
            result = await _download_file(largest["file_id"])
            if result is None:
                parts.append("🖼 Фото больше 20 МБ — сохранить не удалось.")
                continue
            content_bytes, file_path = result
            filename = file_path.rsplit("/", 1)[-1]
            upload = await _save_upload(db, space_id, author_id, content_bytes, filename, "image/jpeg")
            caption = _entities_to_markdown(m.get("caption", ""), m.get("caption_entities"))
            if caption and not title:
                title = _derive_title(caption)
            body = f"{caption}\n\n" if caption else ""
            parts.append(f"{body}![](/api/uploads/{upload.id})\n\n{image_placeholder_text(upload.id)}")
            deferred.append((enqueue_vision, upload.id))
        elif "video" in m:
            video = m["video"]
            file_size = video.get("file_size", 0)
            if file_size and file_size > _MAX_DOWNLOAD_BYTES:
                parts.append(f"🎥 Видео ({file_size / (1024 * 1024):.0f} МБ) — больше 20 МБ, сохранить не удалось.")
                continue
            result = await _download_file(video["file_id"])
            if result is None:
                parts.append("🎥 Видео больше 20 МБ — сохранить не удалось.")
                continue
            content_bytes, file_path = result
            filename = file_path.rsplit("/", 1)[-1]
            mime_type = video.get("mime_type", "video/mp4")
            upload = await _save_upload(db, space_id, author_id, content_bytes, filename, mime_type)
            caption = _entities_to_markdown(m.get("caption", ""), m.get("caption_entities"))
            if caption and not title:
                title = _derive_title(caption)
            body = f"{caption}\n\n" if caption else ""
            parts.append(
                f'{body}<video src="/api/uploads/{upload.id}" controls preload="metadata" '
                f'style="max-width: 100%; max-height: 70vh;"></video>\n\n{video_placeholder_text(upload.id)}'
            )
            deferred.append((enqueue_transcription, upload.id))
        elif "voice" in m or "audio" in m:
            voice = m.get("voice") or m.get("audio")
            result = await _download_file(voice["file_id"])
            if result is None:
                parts.append("🎤 Голосовое сообщение больше 20 МБ — сохранить не удалось.")
                continue
            content_bytes, _file_path = result
            mime_type = voice.get("mime_type", "audio/ogg")
            upload = await _save_upload(db, space_id, author_id, content_bytes, "voice.ogg", mime_type)
            transcript = ""
            settings = get_settings()
            if asr_available():
                try:
                    transcript = await get_asr_client().transcribe(content_bytes, mime_type)
                except Exception:
                    logger.exception("Ошибка распознавания голосового сообщения из Telegram")
            file_link = f"[voice.ogg](/api/uploads/{upload.id})"
            parts.append(f"{file_link}\n\n{transcript}" if transcript.strip() else file_link)
            if transcript.strip() and not title:
                title = _derive_title(transcript)
        elif "document" in m:
            document = m["document"]
            filename = document.get("file_name", "файл")
            file_size = document.get("file_size", 0)
            if file_size and file_size > _MAX_DOWNLOAD_BYTES:
                mb = file_size / (1024 * 1024)
                parts.append(f"📎 Файл «{filename}» ({mb:.0f} МБ) — больше 20 МБ, сохранить не удалось.")
                continue
            result = await _download_file(document["file_id"])
            if result is None:
                parts.append(f"📎 Файл «{filename}» — больше 20 МБ, сохранить не удалось.")
                continue
            content_bytes, _file_path = result
            mime_type = document.get("mime_type", "application/octet-stream")
            upload = await _save_upload(db, space_id, author_id, content_bytes, filename, mime_type)
            caption = _entities_to_markdown(m.get("caption", ""), m.get("caption_entities"))
            if caption and not title:
                title = _derive_title(caption)
            body = f"{caption}\n\n" if caption else ""
            attachment_url = f"/api/uploads/{upload.id}"
            is_pdf = mime_type == "application/pdf" or filename.lower().endswith(".pdf")
            if is_pdf:
                text_layer = extract_pdf_text(content_bytes)
                user = await db.get(User, author_id)
                auto = user is not None and user.auto_process_uploads
                if auto and (text_layer or len(content_bytes) <= AUTO_OCR_MAX_PDF_BYTES):
                    parts.append(f"{body}{serialize_document_attachment(attachment_url, filename, '', processing=True)}")
                    upload.transcription_status = "pending"
                    deferred.append((enqueue_pdf_ocr, upload.id))
                elif text_layer:
                    parts.append(f"{body}{serialize_document_attachment(attachment_url, filename, text_layer)}")
                else:
                    parts.append(f"{body}{serialize_document_attachment(attachment_url, filename, '')}")
            else:
                # Тот же экстрактор, что в _handle_document — реальная
                # жалоба касалась именно пересланных документов.
                text_preview = None
                try:
                    text_preview = _extract_text_preview(_upload_path(upload.id), mime_type, filename)
                except Exception:
                    logger.exception("Не удалось извлечь текст из %s (Telegram, id=%s)", filename, upload.id)
                parts.append(f"{body}{serialize_document_attachment(attachment_url, filename, text_preview or '')}")

    if not parts:
        return False
    content = "\n\n".join(parts)
    if not title:
        title = sender_name or ""
    await create_item_row(
        db,
        space_id=space_id,
        author_id=author_id,
        material_type="note",
        title=title,
        content=content,
        folder_id=folder_id,
    )
    if folder_created:
        await realtime.notify_space(space_id, "folders")
    for fn, upload_id in deferred:
        fn(upload_id)
    return True


async def _transcribe_voice_only(message: dict) -> str:
    """Как голосовая часть _handle_forward_batch, но без сохранения как
    Upload — это разговорная
    реплика ассистенту, не захват контента. Пустая строка — не удалось
    скачать/распознать, вызывающий код сам решает, что сказать пользователю."""
    voice = message.get("voice") or message.get("audio")
    result = await _download_file(voice["file_id"])
    if result is None:
        return ""
    content_bytes, _file_path = result
    mime_type = voice.get("mime_type", "audio/ogg")
    settings = get_settings()
    if not asr_available():
        return ""
    try:
        return await get_asr_client().transcribe(content_bytes, mime_type)
    except Exception:
        logger.exception("Ошибка распознавания голосовой команды из Telegram")
        return ""


# Веб (AssistantChat.tsx) после create_note/create_list/create_table рисует
# кнопку "Открыть «Title»", после create_maps_link — кнопку на Google Maps.
# Тот же результат тула уже есть в истории диалога (records роли "tool",
# content — JSON-строка) — просто раньше никто в Telegram-стороне его не
# читал. _ITEM_LINK_TOOLS — те, что возвращают {id, title} самостоятельного
# item'а, на который можно ссылаться через ?item= (тот же query-param,
# что уже читает AppShell.tsx для навигации).
_ITEM_LINK_TOOLS = {"create_note", "create_list", "create_table"}
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\((/api/uploads/[^)\s]+)\)")


def _build_action_buttons(new_records: list[dict], base_url: str) -> list[list[dict]]:
    tool_results: dict[str, dict] = {}
    for r in new_records:
        if r.get("role") == "tool" and r.get("tool_call_id"):
            try:
                tool_results[r["tool_call_id"]] = json.loads(r.get("content") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue

    rows: list[list[dict]] = []
    for r in new_records:
        if r.get("role") != "assistant":
            continue
        for tc in r.get("tool_calls", []):
            result = tool_results.get(tc.get("id"))
            if not isinstance(result, dict) or result.get("error"):
                continue
            name = tc.get("name")
            if name in _ITEM_LINK_TOOLS and result.get("id") and result.get("title"):
                rows.append(
                    [{"text": f"Открыть «{str(result['title'])[:60]}»", "url": f"{base_url}/?item={result['id']}"}]
                )
            elif name == "create_maps_link" and result.get("url"):
                rows.append([{"text": "Открыть в Google Maps", "url": result["url"]}])
    return rows


def _find_calendar_event(new_records: list[dict]) -> dict | None:
    for r in new_records:
        if r.get("role") != "tool" or r.get("name") != "create_calendar_event":
            continue
        try:
            result = json.loads(r.get("content") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(result, dict) and result.get("title") and result.get("start") and result.get("end"):
            return result
    return None


def _extract_image_paths(text: str) -> tuple[str, list[str]]:
    """Markdown-картинки (![](/api/uploads/<id>)) Telegram не разворачивает
    сам — вырезаем синтаксис из текста и возвращаем пути отдельно, чтобы
    отправить их настоящими фото (см. send_photo/send_media_group)."""
    paths = _IMAGE_MD_RE.findall(text)
    stripped = _IMAGE_MD_RE.sub("", text).strip()
    return stripped, paths


async def _handle_assistant_message(db: AsyncSession, link: TelegramLink, text: str) -> None:
    dialog: Item | None = None
    if link.active_dialog_id is not None:
        dialog = await db.get(Item, link.active_dialog_id)
        if dialog is None or dialog.material_type != "dialog" or dialog.deleted_at is not None:
            dialog = None

    if dialog is None:
        dialog = await create_item_row(
            db,
            space_id=link.space_id,
            author_id=link.user_id,
            material_type="dialog",
            title="Telegram",
            properties={"messages": []},
        )
        link.active_dialog_id = dialog.id
        await db.commit()

    user = await db.get(User, link.user_id)
    history_len = len(dialog.properties.get("messages", []))
    # Живого браузера у Telegram нет — лучшая доступная замена живому
    # поясу это домашний пояс того же пользователя (app/user_timezone.py).
    records = await run_dialog_turn(db, user, dialog, text, user.timezone)
    new_records = records[history_len:]

    last = records[-1] if records and records[-1]["role"] == "assistant" else None
    reply_text = ((last or {}).get("content") or "").strip() or "…"
    options = (last or {}).get("suggested_replies") or []

    settings = get_settings()
    base_url = settings.public_base_url.rstrip("/")

    reply_text, image_paths = _extract_image_paths(reply_text)
    if len(image_paths) == 1:
        await send_photo(link.chat_id, f"{base_url}{image_paths[0]}")
    elif len(image_paths) > 1:
        await send_media_group(link.chat_id, [f"{base_url}{p}" for p in image_paths])
    if not reply_text:
        reply_text = "…"

    # create_calendar_event не отдаёт готовую ссылку — веб сам собирает
    # .ics на фронтенде из структурированных данных тула. Ссылка на
    # /api/calendar/event.ics потребовала бы сессионную куку браузера,
    # которой у обычного клика в Telegram нет — собираем те же байты
    # (build_ics — общий код с routers/calendar.py) и шлём файлом.
    event = _find_calendar_event(new_records)
    if event is not None:
        ics = build_ics(
            str(event["title"]),
            str(event["start"]),
            str(event["end"]),
            bool(event.get("all_day", False)),
            str(event.get("location", "")),
            str(event.get("description", "")),
        )
        await send_document_bytes(link.chat_id, "event.ics", ics.encode("utf-8"), "text/calendar")

    action_rows = _build_action_buttons(new_records, base_url)
    reply_rows = [[{"text": opt[:64], "callback_data": f"sr:{i}"}] for i, opt in enumerate(options[:8])]
    keyboard = action_rows + reply_rows
    reply_markup = {"inline_keyboard": keyboard} if keyboard else None

    await send_message(link.chat_id, reply_text, reply_markup=reply_markup)


async def _handle_callback_query(callback: dict) -> None:
    await answer_callback_query(callback["id"])

    data = callback.get("data", "")

    # Кнопки утренней сводки («сделано» / «не актуально») — свой префикс,
    # чтобы не пересечься с вариантами ответа ассистента ниже.
    if data.startswith(daily_digest.CALLBACK_PREFIX):
        chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
        if chat_id is None:
            return
        message_id = ((callback.get("message") or {}).get("message_id"))
        async with async_session() as db:
            link = (await db.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).scalar_one_or_none()
            if link is None:
                return
            reply = await daily_digest.handle_callback(db, link.user_id, data)
            if reply is None:
                return
            # Перерисовываем сводку из текущего состояния базы: закрытый
            # пункт пропадает вместе с кнопкой. Когда всё закрыто — одна
            # строка без кнопок.
            user = await db.get(User, link.user_id)
            built = await daily_digest.build_digest(db, user) if user else None
        if message_id is not None:
            if built is None:
                # Закрыто всё — сводке в чате делать нечего. Неактуальное
                # удаляется, актуальное остаётся; когда актуального не
                # осталось, не остаётся и сообщения.
                await delete_message(chat_id, message_id)
            else:
                text, keyboard = built
                await edit_message(chat_id, message_id, text, {"inline_keyboard": keyboard})
        else:
            await send_message(chat_id, reply)
        return

    if not data.startswith("sr:"):
        return
    try:
        option_index = int(data.split(":", 1)[1])
    except ValueError:
        return

    chat = (callback.get("message") or {}).get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return

    async with async_session() as db:
        link = (await db.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).scalar_one_or_none()
        if link is None or link.active_dialog_id is None:
            return
        dialog = await db.get(Item, link.active_dialog_id)
        if dialog is None:
            return
        records = dialog.properties.get("messages", [])
        if not records or records[-1]["role"] != "assistant":
            return
        options = records[-1].get("suggested_replies") or []
        if option_index >= len(options):
            return
        chosen_text = options[option_index]

        await _handle_assistant_message(db, link, chosen_text)


async def _process(update: dict) -> None:
    if "_media_group_flush" in update:
        await _flush_media_group(update["_media_group_flush"])
        return

    if "_forward_batch_flush" in update:
        await _flush_forward_batch(update["_forward_batch_flush"])
        return

    if "callback_query" in update:
        await _handle_callback_query(update["callback_query"])
        return

    message = update.get("message")
    if not message:
        return

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return

    text = message.get("text", "") or ""

    if text.startswith("/start"):
        await _handle_start(chat_id, text)
        return

    async with async_session() as db:
        link = (await db.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).scalar_one_or_none()
        if link is None:
            await send_message(
                chat_id,
                "Сначала подключите аккаунт: в приложении Notenotes откройте настройки → «Подключить Telegram».",
            )
            return

        if text.startswith("/new"):
            link.active_dialog_id = None
            await db.commit()
            await send_message(chat_id, "Начат новый диалог с ассистентом.")
            return

        # Пересланное — всегда захват контента (заметка), напечатанное/
        # надиктованное прямо в чат — разговор с ассистентом. forward_origin
        # (Bot API 7.0+) и forward_date (более старый формат) проверяем оба,
        # чтобы не зависеть от версии клиента/API.
        is_forwarded = "forward_origin" in message or "forward_date" in message

        # Альбом (несколько фото/видео одним постом) — каждый файл приходит
        # отдельным апдейтом, буферизуем и собираем одну заметку по debounce'у
        # (см. _buffer_media_group_message), а не заметку на файл.
        media_group_id = message.get("media_group_id")
        if media_group_id and ("photo" in message or "video" in message):
            _buffer_media_group_message(message, media_group_id, chat_id)
            return

        # Пересланное вне альбома (текст, одиночное фото/видео/файл/голос,
        # или несколько сообщений, отправленных вручную одним "переслать")
        # — буферизуем по автору форварда: одна заметка на пачку, в папке
        # по имени отправителя (см. _buffer_forward_message).
        if is_forwarded:
            sender_name = _forward_sender_name(message)
            if sender_name is None:
                # Временная диагностика реального случая: пересланный
                # документ ушёл в корень спейса без папки — не удалось
                # определить отправителя форварда. Логируем сырые поля,
                # чтобы увидеть, какую форму на этот раз прислал Telegram
                # (двойная пересылка/приватность форвардов и т.п.). Убрать
                # после того, как причина найдена.
                logger.info(
                    "Пересланное сообщение без определённого sender_name: "
                    "forward_origin=%r forward_from=%r forward_from_chat=%r "
                    "forward_sender_name=%r keys=%r",
                    message.get("forward_origin"),
                    message.get("forward_from"),
                    message.get("forward_from_chat"),
                    message.get("forward_sender_name"),
                    list(message.keys()),
                )
            _buffer_forward_message(message, chat_id, sender_name)
            return

        if "photo" in message or "video" in message or "document" in message:
            # Реальная жалоба: файл, присланный в Telegram, иногда не
            # появлялся в заметках вообще — без объяснения, без карточки.
            # Причина — bare except в run_worker ниже: любое исключение при
            # скачивании/сохранении/распознавании (сеть, диск, битый файл)
            # проглатывалось целиком, пользователь не получал ни заметки,
            # ни ошибки. Теперь падение здесь — не тишина, а гарантированная
            # заметка с честной причиной + ответ в чат.
            try:
                if "photo" in message:
                    await _handle_photo(db, message, link.space_id, link.user_id)
                elif "video" in message:
                    await _handle_video(db, message, link.space_id, link.user_id)
                else:
                    await _handle_document(db, message, link.space_id, link.user_id)
            except Exception:
                logger.exception("Не удалось обработать файл из Telegram (chat_id=%s)", chat_id)
                # Отдельные try — секция скачивания/сохранения могла упасть
                # уже ПОСЛЕ записи в БД (испортив транзакцию этой же db-сессии),
                # тогда create_item_row тоже бросит исключение; неудача одного
                # шага не должна помешать хотя бы ответить в чат.
                try:
                    await create_item_row(
                        db,
                        space_id=link.space_id,
                        author_id=link.user_id,
                        material_type="note",
                        content="⚠️ Не удалось сохранить присланный файл — техническая ошибка на сервере. Попробуйте отправить ещё раз.",
                    )
                except Exception:
                    logger.exception("Не удалось даже сохранить заметку-заглушку об ошибке (chat_id=%s)", chat_id)
                try:
                    await send_message(chat_id, "⚠️ Не получилось сохранить файл. Попробуйте отправить ещё раз.")
                except Exception:
                    logger.exception("Не удалось отправить сообщение об ошибке в Telegram (chat_id=%s)", chat_id)
                return
        elif "voice" in message or "audio" in message:
            transcript = await _transcribe_voice_only(message)
            if transcript.strip():
                # Эхо распознанного ПЕРЕД ответом. Без него человек видит
                # только ответ ассистента и, если тот странный, не может
                # понять, ослышался ли ASR или ошиблась модель. В вебе
                # расшифровка видна в поле ввода, в боте её не видно
                # нигде.
                await send_message(chat_id, f"🎤 {transcript.strip()}")
                await _handle_assistant_message(db, link, transcript)
            elif not asr_available():
                # Отдельно от «не расслышал»: тут дело не в записи, и
                # переговаривать бесполезно.
                await send_message(
                    chat_id,
                    "Распознавание речи не настроено — напишите текстом или "
                    "попросите владельца добавить ключ ASR.",
                )
            else:
                await send_message(
                    chat_id,
                    "Не удалось распознать голосовое сообщение — попробуйте записать ещё раз, "
                    "ближе к микрофону.",
                )
            return
        elif text:
            await _handle_assistant_message(db, link, text)
            return
        else:
            return

    await send_message(chat_id, "Сохранено ✅")


async def run_worker() -> None:
    while True:
        update = await _queue.get()
        try:
            await _process(update)
        except Exception:
            logger.exception("Необработанная ошибка при обработке Telegram-апдейта")
        finally:
            _queue.task_done()
