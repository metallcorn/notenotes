from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.asr.factory import get_asr_client
from app.core.config import get_settings
from app.db import async_session
from app.models import Item, Space, SpaceMember, TelegramLink, TelegramLinkCode, Upload, User
from app.pdf_processing import extract_text as extract_pdf_text
from app.routers.dialogs import run_dialog_turn
from app.routers.items import create_item_row
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


def _api_url(method: str) -> str:
    return f"{TELEGRAM_API_BASE}/bot{get_settings().telegram_bot_token}/{method}"


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def enqueue_update(update: dict) -> None:
    _queue.put_nowait(update)


_MARKDOWN_MARKS_RE = re.compile(r"[*_`~]")


def _derive_title(text: str, fallback: str = "") -> str:
    """Заметки из Telegram создавались без названия ("Без названия" в UI) —
    берём первую непустую строку контента, как заголовок пользователь чаще
    всего и держит там сам. lstrip("#") — заголовок markdown ("# Рецепт
    борща") решётке в названии заметки не нужен; сама строка уже могла
    получить **bold**/_italic_/`code` от _entities_to_markdown — эти
    маркеры тоже убираем, в названии заметки они не нужны, только мусор."""
    for line in text.splitlines():
        stripped = _MARKDOWN_MARKS_RE.sub("", line.strip().lstrip("#")).strip()
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
            parts.append(f"[{segment}]({e['url']})")
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
    placeholder = image_placeholder_text(upload.id)
    caption = _entities_to_markdown(message.get("caption", ""), message.get("caption_entities"))
    body = f"{caption}\n\n" if caption else ""
    content = f"{body}![](/api/uploads/{upload.id})\n\n{placeholder}\n"
    title = _derive_title(caption, fallback="Фото")
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", title=title, content=content)
    enqueue_vision(upload.id)


async def _handle_voice(db: AsyncSession, message: dict, space_id: uuid.UUID, author_id: uuid.UUID) -> None:
    voice = message.get("voice") or message.get("audio")
    result = await _download_file(voice["file_id"])
    if result is None:
        await create_item_row(
            db,
            space_id=space_id,
            author_id=author_id,
            material_type="note",
            content="🎤 Голосовое сообщение больше 20 МБ — сохранить не удалось.",
        )
        return
    content_bytes, _file_path = result
    mime_type = voice.get("mime_type", "audio/ogg")
    upload = await _save_upload(db, space_id, author_id, content_bytes, "voice.ogg", mime_type)

    transcript = ""
    settings = get_settings()
    if settings.deepgram_api_key or settings.whisper_api_key:
        try:
            transcript = await get_asr_client().transcribe(content_bytes, mime_type)
        except Exception:
            logger.exception("Ошибка распознавания голосового сообщения из Telegram")

    file_link = f"[voice.ogg](/api/uploads/{upload.id})"
    content = f"{file_link}\n\n{transcript}" if transcript.strip() else file_link
    title = _derive_title(transcript, fallback="Голосовое сообщение")
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", title=title, content=content)


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
    content = f"{body}[{filename}](/api/uploads/{upload.id})\n"

    # PDF: текстовый слой вытаскиваем сразу — быстро, локально, бесплатно
    # (PyMuPDF, без сети), сразу делает заметку находимой поиском. Сканы
    # без текста — OCR по кнопке в редакторе, не автоматически (может быть
    # долгим/дорогим для многостраничных документов, см. pdf_processing.py).
    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        pdf_text = extract_pdf_text(content_bytes)
        if pdf_text:
            content += f"\n**Текст из PDF:**\n\n{pdf_text}\n"
        else:
            content += "\n📄 PDF без текстового слоя (похоже на скан) — распознать текст можно в редакторе.\n"

    title = _derive_title(caption, fallback=filename)
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", title=title, content=content)


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

    async with async_session() as db:
        link = (await db.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).scalar_one_or_none()
        if link is None:
            return
        await _handle_media_group(db, messages, link.space_id, link.user_id)

    await send_message(chat_id, "Сохранено ✅")


async def _handle_media_group(db: AsyncSession, messages: list[dict], space_id: uuid.UUID, author_id: uuid.UUID) -> None:
    """Альбом (несколько фото/видео одним постом) — одна заметка со всеми
    файлами по порядку, а не по заметке на файл. Подпись Telegram кладёт
    только на одно сообщение группы (обычно первое) — ищем её по всем."""
    caption_raw, caption_entities = "", None
    for m in messages:
        if m.get("caption"):
            caption_raw, caption_entities = m["caption"], m.get("caption_entities")
            break
    caption = _entities_to_markdown(caption_raw, caption_entities)

    parts: list[str] = [caption] if caption else []
    has_photo = False
    for m in messages:
        if "photo" in m:
            has_photo = True
            photos = m["photo"]
            largest = max(photos, key=lambda p: p.get("file_size", 0))
            result = await _download_file(largest["file_id"])
            if result is None:
                parts.append("🖼 Фото больше 20 МБ — сохранить не удалось.")
                continue
            content_bytes, file_path = result
            filename = file_path.rsplit("/", 1)[-1]
            upload = await _save_upload(db, space_id, author_id, content_bytes, filename, "image/jpeg")
            parts.append(f"![](/api/uploads/{upload.id})\n\n{image_placeholder_text(upload.id)}")
            enqueue_vision(upload.id)
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
            parts.append(
                f'<video src="/api/uploads/{upload.id}" controls preload="metadata" '
                f'style="max-width: 100%; max-height: 70vh;"></video>\n\n{video_placeholder_text(upload.id)}'
            )
            enqueue_transcription(upload.id)

    content = "\n\n".join(parts)
    title = _derive_title(caption, fallback="Фото" if has_photo else "Видео")
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", title=title, content=content)


async def _transcribe_voice_only(message: dict) -> str:
    """Как в _handle_voice, но без сохранения как Upload — это разговорная
    реплика ассистенту, не захват контента. Пустая строка — не удалось
    скачать/распознать, вызывающий код сам решает, что сказать пользователю."""
    voice = message.get("voice") or message.get("audio")
    result = await _download_file(voice["file_id"])
    if result is None:
        return ""
    content_bytes, _file_path = result
    mime_type = voice.get("mime_type", "audio/ogg")
    settings = get_settings()
    if not (settings.deepgram_api_key or settings.whisper_api_key):
        return ""
    try:
        return await get_asr_client().transcribe(content_bytes, mime_type)
    except Exception:
        logger.exception("Ошибка распознавания голосовой команды из Telegram")
        return ""


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
    records = await run_dialog_turn(db, user, dialog, text)

    last = records[-1] if records and records[-1]["role"] == "assistant" else None
    reply_text = ((last or {}).get("content") or "").strip() or "…"
    options = (last or {}).get("suggested_replies") or []
    reply_markup = None
    if options:
        reply_markup = {
            "inline_keyboard": [[{"text": opt[:64], "callback_data": f"sr:{i}"}] for i, opt in enumerate(options[:8])]
        }
    await send_message(link.chat_id, reply_text, reply_markup=reply_markup)


async def _handle_callback_query(callback: dict) -> None:
    await answer_callback_query(callback["id"])

    data = callback.get("data", "")
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

        if "photo" in message:
            await _handle_photo(db, message, link.space_id, link.user_id)
        elif "voice" in message or "audio" in message:
            if is_forwarded:
                await _handle_voice(db, message, link.space_id, link.user_id)
            else:
                transcript = await _transcribe_voice_only(message)
                if transcript.strip():
                    await _handle_assistant_message(db, link, transcript)
                else:
                    await send_message(chat_id, "Не удалось распознать голосовое сообщение.")
                return
        elif "video" in message:
            await _handle_video(db, message, link.space_id, link.user_id)
        elif "document" in message:
            await _handle_document(db, message, link.space_id, link.user_id)
        elif text and not is_forwarded:
            await _handle_assistant_message(db, link, text)
            return
        elif text:
            formatted = _entities_to_markdown(text, message.get("entities"))
            title = _derive_title(formatted)
            await create_item_row(
                db, space_id=link.space_id, author_id=link.user_id, material_type="note", title=title, content=formatted
            )
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
