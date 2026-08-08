from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select

from app import realtime
from app.asr.deepgram import DeepgramClient
from app.core.config import get_settings
from app.db import async_session
from app.models import Item, Upload

logger = logging.getLogger(__name__)

# Очередь на распознавание речи из видео (Deepgram, с диаризацией — по
# просьбе пользователя). Один backend-процесс, один воркер — обрабатывает
# видео строго по одному ("без спешки, без превышения лимитов" — прямая
# просьба): не параллелим вызовы Deepgram, естественный троттлинг без
# отдельного rate-limiter'а. In-memory asyncio.Queue не переживает рестарт
# процесса — resume_pending() на старте подхватывает недоделанное по
# статусу в БД, а не теряет его молча.
_queue: "asyncio.Queue[uuid.UUID]" = asyncio.Queue()

_TARGET_AUDIO_BYTES = 10 * 1024 * 1024
_AUDIO_BITRATE_KBPS = 64  # речь моно — этого достаточно; ~480 КБ/мин, 10 МБ ≈ 20 минут


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def placeholder_text(upload_id: uuid.UUID) -> str:
    # Без квадратных скобок: tiptap-markdown при автосохранении экранирует
    # [ и ] в обычном тексте как \[ \] (чтобы не спутать с markdown-ссылкой),
    # и плейсхолдер переставал совпадать с этой строкой при поиске-замене
    # (реально пойманный баг — карточка так и оставалась плейсхолдером
    # навсегда после WYSIWYG-загрузки).
    return f"⏳ Расшифровка {upload_id} обрабатывается…"


def enqueue_transcription(upload_id: uuid.UUID) -> None:
    _queue.put_nowait(upload_id)


def _extract_audio(video_path: Path, audio_path: Path) -> None:
    # -vn — без видеопотока, дальше не нужен. Отдельным потоком (см.
    # asyncio.to_thread ниже) — subprocess.run блокирующий, а воркер
    # обслуживает очередь на весь backend-процесс.
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-b:a",
            f"{_AUDIO_BITRATE_KBPS}k",
            "-f",
            "mp3",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )


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


async def _process(upload_id: uuid.UUID) -> None:
    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        upload.transcription_status = "processing"
        await db.commit()

    video_path = _upload_path(upload_id)
    settings = get_settings()

    async def _fail() -> None:
        async with async_session() as db2:
            u = await db2.get(Upload, upload_id)
            if u is not None:
                u.transcription_status = "failed"
                await db2.commit()

    if not video_path.is_file():
        logger.error("Файл видео для %s не найден на диске (%s)", upload_id, video_path)
        await _fail()
        return
    if not settings.deepgram_api_key:
        logger.error("DEEPGRAM_API_KEY не задан — расшифровка %s невозможна", upload_id)
        await _fail()
        return

    with tempfile.TemporaryDirectory(prefix="transcribe-") as tmp:
        audio_path = Path(tmp) / "audio.mp3"
        try:
            await asyncio.to_thread(_extract_audio, video_path, audio_path)
            audio_bytes = audio_path.read_bytes()
        except Exception:
            logger.exception("Не удалось извлечь звук из видео %s", upload_id)
            await _fail()
            return

    if len(audio_bytes) > _TARGET_AUDIO_BYTES:
        logger.warning(
            "Извлечённый звук для %s больше целевых 10 МБ (%d байт) — отправляем как есть",
            upload_id,
            len(audio_bytes),
        )

    client = DeepgramClient(api_key=settings.deepgram_api_key)
    try:
        transcript = await client.transcribe_with_speakers(audio_bytes, "audio/mpeg")
    except Exception:
        logger.exception("Ошибка Deepgram при распознавании %s", upload_id)
        await _fail()
        return

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        upload.transcript = transcript
        upload.transcription_status = "done" if transcript.strip() else "failed"
        await db.commit()

    if not transcript.strip():
        logger.warning("Deepgram не распознал речь в %s (пустой транскрипт, аудио %d байт)", upload_id, len(audio_bytes))

    if transcript.strip():
        formatted = f"**Расшифровка речи:**\n\n{transcript}"
        await _replace_in_referencing_items(upload_id, placeholder_text(upload_id), formatted)


async def run_worker() -> None:
    while True:
        upload_id = await _queue.get()
        try:
            await _process(upload_id)
        except Exception:
            logger.exception("Необработанная ошибка при расшифровке %s", upload_id)
        finally:
            _queue.task_done()


async def resume_pending() -> None:
    async with async_session() as db:
        # content_type-фильтр обязателен: transcription_status/transcript
        # теперь общие поля с app/vision.py (картинки же) — без фильтра
        # тут подхватились бы и незавершённые задачи анализа изображений.
        result = await db.execute(
            select(Upload.id).where(
                Upload.content_type.like("video/%"),
                Upload.transcription_status.in_(["pending", "processing"]),
            )
        )
        for row in result.all():
            enqueue_transcription(row[0])
