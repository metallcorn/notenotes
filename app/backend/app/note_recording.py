from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from app import realtime
from app.asr.deepgram import DeepgramClient
from app.core.config import get_settings
from app.db import async_session
from app.models import Item, Upload
from app.vision import serialize_image_ocr_result

logger = logging.getLogger(__name__)

# Запись встречи/длинной заметки прямо в редакторе (кнопка-микрофон,
# NoteEditor.tsx/RecordingPanel.tsx) — чанки летят на сервер по ходу записи
# (routers/uploads.py: /uploads/recording/{start,chunk,finish}), а
# распознавание запускается только здесь, уже на готовый файл, тем же
# принципом очереди, что у transcription.py/vision.py — один воркер,
# запись обрабатывается строго по одной.
_queue: "asyncio.Queue[uuid.UUID]" = asyncio.Queue()

# Меньше — почти наверняка случайный старт/стоп без реальной речи (пара
# сотен мс аудио + оверхед контейнера webm), не стоит тратить на это
# вызов Deepgram.
_MIN_RECORDING_BYTES = 2000


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def placeholder_text(upload_id: uuid.UUID) -> str:
    # Без квадратных скобок — см. transcription.placeholder_text: они
    # экранируются в \[ \] при автосохранении WYSIWYG-редактора и ломают
    # поиск-замену плейсхолдера на готовый результат.
    return f"⏳ Запись {upload_id} расшифровывается…"


def enqueue_recording(upload_id: uuid.UUID) -> None:
    _queue.put_nowait(upload_id)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;")


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
    settings = get_settings()

    async def _fail() -> None:
        async with async_session() as db:
            u = await db.get(Upload, upload_id)
            if u is not None:
                u.transcription_status = "failed"
                await db.commit()

    if not settings.deepgram_api_key:
        logger.error("DEEPGRAM_API_KEY не задан — расшифровка записи %s невозможна", upload_id)
        await _fail()
        return

    path = _upload_path(upload_id)
    if not path.is_file():
        logger.error("Файл записи %s не найден на диске", upload_id)
        await _fail()
        return

    audio_bytes = path.read_bytes()
    if len(audio_bytes) < _MIN_RECORDING_BYTES:
        logger.info("Запись %s слишком короткая (%d байт) — распознавание пропущено", upload_id, len(audio_bytes))
        await _fail()
        return

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        upload.transcription_status = "processing"
        await db.commit()
        filename = upload.filename
        content_type = upload.content_type

    client = DeepgramClient(api_key=settings.deepgram_api_key)
    try:
        # language=None — авто-определение: в отличие от остального
        # приложения (по умолчанию русскоязычного), запись встречи может
        # быть не на русском.
        transcript = await client.transcribe_with_speakers(audio_bytes, content_type, language=None)
    except Exception:
        logger.exception("Ошибка Deepgram при расшифровке записи %s", upload_id)
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
        logger.warning("Deepgram не распознал речь в записи %s (пустой транскрипт, %d байт)", upload_id, len(audio_bytes))
        return

    url = f"/api/uploads/{upload_id}"
    # Тот же плеер, что у обычного загруженного аудио (Audio.ts), плюс
    # сворачиваемая расшифровка — тот же узел/карточка, что у OCR картинок
    # (ImageOcrResult.ts/ImageOcrResultCard.tsx): формат карточки ничего
    # не знает про картинки конкретно, просто сворачиваемый текст, поэтому
    # переиспользуем как есть, без нового узла на фронте.
    card = f'<audio src="{url}" data-filename="{_esc(filename)}"></audio>\n\n{serialize_image_ocr_result(transcript)}'
    await _replace_in_referencing_items(upload_id, placeholder_text(upload_id), card)


async def run_worker() -> None:
    while True:
        upload_id = await _queue.get()
        try:
            await _process(upload_id)
        except Exception:
            logger.exception("Необработанная ошибка при расшифровке записи %s", upload_id)
        finally:
            _queue.task_done()


async def resume_pending() -> None:
    # "recording" — сессия, у которой ещё не было /finish (обрыв
    # страницы/крашнутая вкладка) — сюда намеренно НЕ попадает: полное
    # восстановление записи после краша не входит в эту версию (решение
    # явно обсуждено), запись просто остаётся в БД недописанной, безвредно.
    async with async_session() as db:
        result = await db.execute(
            select(Upload.id).where(
                # content_type — то, что реально выбрал MediaRecorder в
                # браузере (RecordingPanel.tsx), с суффиксом кодека
                # ("audio/webm;codecs=opus") — не точное совпадение.
                Upload.content_type.like("audio/webm%") | Upload.content_type.like("audio/ogg%"),
                Upload.transcription_status.in_(["pending", "processing"]),
            )
        )
        for row in result.all():
            enqueue_recording(row[0])
