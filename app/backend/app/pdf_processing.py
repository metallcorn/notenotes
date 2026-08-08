from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import pymupdf

from app.core.config import get_settings
from app.db import async_session
from app.models import Upload
from app.vision import _analyze as _vision_analyze
from app.vision import _replace_in_referencing_items

logger = logging.getLogger(__name__)

# Ручной OCR сканов PDF — только по кнопке, не автоматически (по просьбе:
# текстовый слой extract_text() вытаскивает сразу при загрузке бесплатно и
# локально через PyMuPDF, без сети; а прогонять каждую страницу скана
# через Mistral vision может быть долго и небесплатно для многостраничных
# документов, поэтому только по явному запросу). Один воркер — тот же
# принцип, что у vision.py/transcription.py/autotag.py.
_queue: "asyncio.Queue[uuid.UUID]" = asyncio.Queue()

# Меньше этого на весь документ — считаем, что текстового слоя нет (скан),
# не то что разумно ожидать даже от одной читаемой страницы.
_MIN_TEXT_LEN = 40
_MAX_TEXT_CHARS = 20000
_MAX_OCR_PAGES = 20  # защита от сканов на многие сотни страниц


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def placeholder_text(upload_id: uuid.UUID) -> str:
    return f"[Распознавание PDF {upload_id} обрабатывается…]"


def extract_text(pdf_bytes: bytes) -> str:
    """Синхронно и локально (PyMuPDF, без внешнего API) — вытаскивает
    текстовый слой, если он есть. Пустая строка — в PDF нет текста (скан),
    вызывающий код сам решает, что делать (не пытаемся угадывать OCR)."""
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            text = "\n\n".join(page.get_text() for page in doc)
    except Exception:
        logger.exception("Не удалось прочитать PDF")
        return ""
    text = text.strip()
    if len(text) < _MIN_TEXT_LEN:
        return ""
    return text[:_MAX_TEXT_CHARS]


def enqueue_ocr(upload_id: uuid.UUID) -> None:
    _queue.put_nowait(upload_id)


async def _process(upload_id: uuid.UUID) -> None:
    settings = get_settings()

    async def _fail() -> None:
        async with async_session() as db:
            u = await db.get(Upload, upload_id)
            if u is not None:
                u.transcription_status = "failed"
                await db.commit()

    if not settings.llm_api_key:
        logger.error("LLM_API_KEY не задан — OCR PDF %s невозможен", upload_id)
        await _fail()
        return

    pdf_path = _upload_path(upload_id)
    if not pdf_path.is_file():
        logger.error("Файл PDF для %s не найден на диске", upload_id)
        await _fail()
        return

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        upload.transcription_status = "processing"
        await db.commit()

    try:
        page_texts: list[str] = []
        with pymupdf.open(pdf_path) as doc:
            for i, page in enumerate(doc):
                if i >= _MAX_OCR_PAGES:
                    break
                png_bytes = page.get_pixmap(dpi=150).tobytes("png")
                description = await _vision_analyze(png_bytes, "image/png", settings.llm_api_key)
                if description.strip():
                    page_texts.append(f"**Страница {i + 1}:**\n\n{description.strip()}")
    except Exception:
        logger.exception("Ошибка распознавания PDF %s", upload_id)
        await _fail()
        return

    result = "\n\n---\n\n".join(page_texts)

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        upload.transcript = result
        upload.transcription_status = "done" if result.strip() else "failed"
        await db.commit()

    if not result.strip():
        logger.warning("OCR PDF %s не дал результата", upload_id)
        return

    formatted = f"**Распознанный текст PDF:**\n\n{result}"
    await _replace_in_referencing_items(upload_id, placeholder_text(upload_id), formatted)


async def run_worker() -> None:
    while True:
        upload_id = await _queue.get()
        try:
            await _process(upload_id)
        except Exception:
            logger.exception("Необработанная ошибка при OCR PDF %s", upload_id)
        finally:
            _queue.task_done()
