from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select

from app import realtime
from app.core.config import get_settings
from app.db import async_session
from app.models import Item, Upload

logger = logging.getLogger(__name__)

# Классификация/OCR картинок через Mistral vision — по просьбе, чтобы
# изображения тоже находились полнотекстовым поиском. Тот же принцип, что
# у app/transcription.py: одна asyncio-очередь, один воркер — картинки
# обрабатываются строго по одной ("без спешки, без превышения лимитов"),
# без отдельного rate-limiter'а. Переиспользует поля transcription_status/
# transcript на Upload — по смыслу это то же самое "фоновая расшифровка
# содержимого файла", отдельная таблица ради этого не нужна.
_queue: "asyncio.Queue[uuid.UUID]" = asyncio.Queue()

MISTRAL_VISION_MODEL = "mistral-small-latest"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

_PROMPT = (
    "Опиши это изображение кратко (одно-два предложения, что на нём) и, если на "
    "изображении есть читаемый текст, приведи его дословно после описания под "
    "заголовком «Текст на изображении». Отвечай только результатом, без вступлений "
    "и комментариев, в формате Markdown, на русском языке."
)

# Не гоняем на анализ огромные фото без нужды (тот же принцип, что 10 МБ
# звука для видео) — 8 МБ с запасом хватает на любое реалистичное фото с
# телефона в разумном качестве.
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def placeholder_text(upload_id: uuid.UUID) -> str:
    return f"[Описание изображения {upload_id} обрабатывается…]"


def enqueue_vision(upload_id: uuid.UUID) -> None:
    _queue.put_nowait(upload_id)


async def _replace_in_referencing_items(upload_id: uuid.UUID, old: str, new: str) -> None:
    async with async_session() as db:
        result = await db.execute(select(Item).where(Item.content.like(f"%{upload_id}%")))
        items = result.scalars().all()
        touched_spaces = set()
        for item in items:
            if old in item.content:
                item.content = item.content.replace(old, new)
                touched_spaces.add(item.space_id)
        if touched_spaces:
            await db.commit()
            for space_id in touched_spaces:
                await realtime.notify_space(space_id, "items")


async def _analyze(image_bytes: bytes, content_type: str, api_key: str) -> str:
    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:{content_type};base64,{b64}"
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            MISTRAL_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MISTRAL_VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _PROMPT},
                            {"type": "image_url", "image_url": data_url},
                        ],
                    }
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


async def _process(upload_id: uuid.UUID) -> None:
    settings = get_settings()

    async def _fail() -> None:
        async with async_session() as db:
            u = await db.get(Upload, upload_id)
            if u is not None:
                u.transcription_status = "failed"
                await db.commit()

    if not settings.llm_api_key:
        logger.error("LLM_API_KEY не задан — анализ изображения %s невозможен", upload_id)
        await _fail()
        return

    image_path = _upload_path(upload_id)
    if not image_path.is_file():
        logger.error("Файл изображения для %s не найден на диске", upload_id)
        await _fail()
        return

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        upload.transcription_status = "processing"
        await db.commit()
        content_type = upload.content_type

    image_bytes = image_path.read_bytes()
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        logger.warning(
            "Изображение %s больше %d МБ — анализ пропущен", upload_id, _MAX_IMAGE_BYTES // (1024 * 1024)
        )
        await _fail()
        return

    try:
        description = await _analyze(image_bytes, content_type, settings.llm_api_key)
    except Exception:
        logger.exception("Ошибка Mistral vision при анализе %s", upload_id)
        await _fail()
        return

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        upload.transcript = description
        upload.transcription_status = "done" if description.strip() else "failed"
        await db.commit()

    if not description.strip():
        logger.warning("Mistral vision вернул пустой результат для %s", upload_id)
        return

    formatted = f"**Изображение:**\n\n{description}"
    await _replace_in_referencing_items(upload_id, placeholder_text(upload_id), formatted)


async def run_worker() -> None:
    while True:
        upload_id = await _queue.get()
        try:
            await _process(upload_id)
        except Exception:
            logger.exception("Необработанная ошибка при анализе изображения %s", upload_id)
        finally:
            _queue.task_done()


async def resume_pending() -> None:
    async with async_session() as db:
        result = await db.execute(
            select(Upload.id).where(
                Upload.content_type.like("image/%"),
                Upload.transcription_status.in_(["pending", "processing"]),
            )
        )
        for row in result.all():
            enqueue_vision(row[0])
