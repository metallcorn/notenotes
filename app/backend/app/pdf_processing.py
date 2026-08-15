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

# OCR сканов PDF — текстовый слой extract_text() вытаскивает сразу при
# загрузке бесплатно и локально через PyMuPDF, без сети; а прогонять
# каждую страницу скана через Mistral vision может быть долго и
# небесплатно для многостраничных документов, поэтому это отдельная
# очередь. Автоматически запускается только для небольших файлов
# (см. AUTO_OCR_MAX_PDF_BYTES в routers/uploads.py/telegram_bot.py) —
# для остальных только по кнопке «Распознать». Один воркер — тот же
# принцип, что у vision.py/transcription.py/autotag.py.
_queue: "asyncio.Queue[uuid.UUID]" = asyncio.Queue()

# Меньше этого на весь документ — считаем, что текстового слоя нет (скан),
# не то что разумно ожидать даже от одной читаемой страницы.
_MIN_TEXT_LEN = 40
_MAX_TEXT_CHARS = 20000
_MAX_OCR_PAGES = 20  # защита от сканов на многие сотни страниц

# Выше этого — скан-PDF без текстового слоя не распознаётся автоматически
# при загрузке, только по кнопке: постраничная vision-OCR многостраничного
# скана может быть долгой и не бесплатной, не то, что нужно без явного
# запроса пользователя на каждой загрузке.
AUTO_OCR_MAX_PDF_BYTES = 5 * 1024 * 1024


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def placeholder_text(upload_id: uuid.UUID) -> str:
    # Без квадратных скобок — см. transcription.placeholder_text: они
    # экранируются в \[ \] при автосохранении WYSIWYG-редактора и ломают
    # поиск-замену плейсхолдера на готовую карточку.
    return f"⏳ Распознавание PDF {upload_id} обрабатывается…"


def serialize_document_attachment(url: str, filename: str, text: str) -> str:
    """Тот же формат (один самодостаточный тег на одной строке, текст в
    атрибуте), что сериализует фронтенд-нода DocumentAttachment.ts —
    чтобы карточка после автоматического OCR выглядела так же, как у
    файлов, распознанных сразу при загрузке. Экранирование в том же
    порядке: & -> &amp;, реальные переносы строк -> &#10; (чтобы весь тег
    остался на одной строке — иначе markdown-it оборвал бы html_block на
    первой пустой строке внутри многостраничного текста), потом " ->
    &quot;. Браузерный DOMParser декодирует сущности обратно при чтении
    атрибута, ничего вручную на фронте разбирать не нужно."""

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("\n", "&#10;").replace('"', "&quot;")

    parts = [f'data-url="{esc(url)}"']
    if filename:
        parts.append(f'data-filename="{esc(filename)}"')
    if text:
        parts.append(f'data-text="{esc(text)}"')
    return f"<div data-doc-attachment {' '.join(parts)}></div>"


def _extract_page_text_with_tables(page: "pymupdf.Page") -> str:
    """Реальная жалоба: обычный page.get_text() читает таблицу построчно
    слева направо как плоский текст — колонки разъезжаются, реальная
    табличная структура (расценки, характеристики) теряется полностью.
    PyMuPDF умеет находить таблицы отдельно (find_tables(), по линиям
    разметки/выравниванию колонок) и отдавать их уже готовым Markdown —
    локально, без единого обращения к LLM. Не полагаемся на угадывание:
    достаём таблицы отдельно, вырезаем их текст из обычного потока (иначе
    продублировался бы дважды — один раз как таблица, второй раз как
    плоский текст блоков, из которых она состоит), и вставляем markdown
    таблицы туда же по вертикали, где они были на странице."""
    try:
        tables = list(page.find_tables().tables)
    except Exception:
        tables = []
    if not tables:
        return page.get_text()

    table_rects = [pymupdf.Rect(t.bbox) for t in tables]
    pieces: list[tuple[float, str]] = []

    for block in page.get_text("blocks"):
        rect = pymupdf.Rect(block[:4])
        text = block[4].strip()
        if not text or any(rect.intersects(tr) for tr in table_rects):
            continue
        pieces.append((rect.y0, text))

    for table, rect in zip(tables, table_rects):
        try:
            md = table.to_markdown()
        except Exception:
            continue
        if md.strip():
            pieces.append((rect.y0, md.strip()))

    pieces.sort(key=lambda p: p[0])
    return "\n\n".join(p[1] for p in pieces)


def extract_text(pdf_bytes: bytes) -> str:
    """Синхронно и локально (PyMuPDF, без внешнего API) — вытаскивает
    текстовый слой, если он есть. Пустая строка — в PDF нет текста (скан),
    вызывающий код сам решает, что делать (не пытаемся угадывать OCR)."""
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            text = "\n\n".join(_extract_page_text_with_tables(page) for page in doc)
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
        filename = upload.filename
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

    formatted = serialize_document_attachment(f"/api/uploads/{upload_id}", filename, result)
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
