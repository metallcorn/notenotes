from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.asr.factory import get_asr_client
from app.core.config import get_settings
from app.db import async_session
from app.models import Space, SpaceMember, TelegramLink, TelegramLinkCode, Upload
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


def _api_url(method: str) -> str:
    return f"{TELEGRAM_API_BASE}/bot{get_settings().telegram_bot_token}/{method}"


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def enqueue_update(update: dict) -> None:
    _queue.put_nowait(update)


async def register_webhook() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    url = f"{settings.public_base_url}/api/telegram/webhook"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                _api_url("setWebhook"),
                json={"url": url, "secret_token": settings.telegram_webhook_secret, "allowed_updates": ["message"]},
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error("Не удалось зарегистрировать Telegram webhook: %s", data)
        except Exception:
            logger.exception("Ошибка при регистрации Telegram webhook")


async def send_message(chat_id: int, text: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(_api_url("sendMessage"), json={"chat_id": chat_id, "text": text})
        except Exception:
            logger.exception("Не удалось отправить сообщение в Telegram chat_id=%s", chat_id)


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
    caption = message.get("caption", "")
    body = f"{caption}\n\n" if caption else ""
    content = f"{body}![](/api/uploads/{upload.id})\n\n{placeholder}\n"
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", content=content)
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

    link = f"[voice.ogg](/api/uploads/{upload.id})"
    content = f"{link}\n\n{transcript}" if transcript.strip() else link
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", content=content)


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
    caption = message.get("caption", "")
    body = f"{caption}\n\n" if caption else ""
    content = (
        f'{body}<video src="/api/uploads/{upload.id}" controls preload="metadata" '
        f'style="max-width: 100%; max-height: 70vh;"></video>\n\n{placeholder}\n'
    )
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", content=content)
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
    caption = message.get("caption", "")
    body = f"{caption}\n\n" if caption else ""
    content = f"{body}[{filename}](/api/uploads/{upload.id})\n"
    await create_item_row(db, space_id=space_id, author_id=author_id, material_type="note", content=content)


async def _process(update: dict) -> None:
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

        if "photo" in message:
            await _handle_photo(db, message, link.space_id, link.user_id)
        elif "voice" in message or "audio" in message:
            await _handle_voice(db, message, link.space_id, link.user_id)
        elif "video" in message:
            await _handle_video(db, message, link.space_id, link.user_id)
        elif "document" in message:
            await _handle_document(db, message, link.space_id, link.user_id)
        elif text:
            await create_item_row(db, space_id=link.space_id, author_id=link.user_id, material_type="note", content=text)
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
