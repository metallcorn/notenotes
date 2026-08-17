from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path

import pymupdf
from sqlalchemy import select

from app import realtime
from app.core.config import get_settings
from app.db import async_session
from app.document_reflow import reflow_document_text
from app.models import Item, Upload
from app.vision import _analyze as _vision_analyze
from app.vision import _split_ticket_marker

logger = logging.getLogger(__name__)

# Распознавание PDF — асинхронная очередь для ОБОИХ случаев: и текстовый
# слой (extract_text() сама по себе бесплатна и локальна через PyMuPDF, но
# результат теперь ещё причёсывается отдельным LLM-вызовом,
# document_reflow.py — реальная жалоба на "кашу" в вёрстке при прямом
# извлечении, особенно на многоколоночных/табличных документах), и скан
# без текстового слоя (постраничный vision-OCR + тот же reflow на каждую
# страницу — дороже и медленнее для многостраничных документов, поэтому
# именно этот случай ограничен размером файла, см. AUTO_OCR_MAX_PDF_BYTES
# ниже — для больших сканов нужен явный клик «Распознать»). Один воркер —
# тот же принцип, что у vision.py/transcription.py/autotag.py.
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


def serialize_document_attachment(url: str, filename: str, text: str, processing: bool = False) -> str:
    """Тот же формат (один самодостаточный тег на одной строке, текст в
    атрибуте), что сериализует фронтенд-нода DocumentAttachment.ts —
    чтобы карточка после автоматического OCR выглядела так же, как у
    файлов, распознанных сразу при загрузке. Экранирование в том же
    порядке: & -> &amp;, реальные переносы строк -> &#10; (чтобы весь тег
    остался на одной строке — иначе markdown-it оборвал бы html_block на
    первой пустой строке внутри многостраничного текста), потом " ->
    &quot;. Браузерный DOMParser декодирует сущности обратно при чтении
    атрибута, ничего вручную на фронте разбирать не нужно.

    processing — реальная жалоба: раньше на время распознавания карточка
    файла целиком заменялась отдельным текстовым плейсхолдером
    "⏳ ... обрабатывается…" — пользователь терял доступ к самому файлу
    (открыть/скачать) до конца обработки. Теперь карточка — ОДИН и тот же
    узел (url/filename стабильны) во всех состояниях, меняется только этот
    флаг; см. _replace_document_card ниже, который заменяет тег ЦЕЛИКОМ по
    совпадению data-url, а не ищет отдельный плейсхолдер рядом."""

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("\n", "&#10;").replace('"', "&quot;")

    parts = [f'data-url="{esc(url)}"']
    if filename:
        parts.append(f'data-filename="{esc(filename)}"')
    if text:
        parts.append(f'data-text="{esc(text)}"')
    if processing:
        parts.append('data-processing=""')
    return f"<div data-doc-attachment {' '.join(parts)}></div>"


_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_SECONDS = 2.0


async def _replace_document_card(upload_id: uuid.UUID, new_card_html: str) -> None:
    """Находит ТЕКУЩУЮ карточку файла (в любом её состоянии — processing
    или уже с текстом, см. serialize_document_attachment) по data-url и
    заменяет тег целиком — не отдельный текст-плейсхолдер рядом, как было
    раньше (vision._replace_in_referencing_items): карточка с первой же
    вставки больше не пропадает на время обработки. Тот же retry, что и у
    того хелпера — плейсхолдер/карточка может ещё не долететь до бэкенда
    дебаунсом автосохранения."""
    url = f"/api/uploads/{upload_id}"
    pattern = re.compile(rf'<div data-doc-attachment[^>]*data-url="{re.escape(url)}"[^>]*></div>')
    for attempt in range(_REPLACE_RETRY_ATTEMPTS):
        async with async_session() as db:
            result = await db.execute(select(Item).where(Item.content.like(f"%{upload_id}%")))
            items = result.scalars().all()
            touched_spaces = set()
            for item in items:
                new_content, n = pattern.subn(new_card_html, item.content)
                if n:
                    item.content = new_content
                    touched_spaces.add(item.space_id)
            if touched_spaces:
                await db.commit()
                for space_id in touched_spaces:
                    await realtime.notify_space(space_id, "items")
                return
        if attempt < _REPLACE_RETRY_ATTEMPTS - 1:
            await asyncio.sleep(_REPLACE_RETRY_DELAY_SECONDS)


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
    url = f"/api/uploads/{upload_id}"

    async def _fail(filename: str = "") -> None:
        # Сбрасываем карточку обратно в "не обработано" (processing=false,
        # без текста) — иначе она застряла бы в состоянии "Распознаём…"
        # навсегда без всякого способа повторить попытку из интерфейса.
        async with async_session() as db:
            u = await db.get(Upload, upload_id)
            if u is not None:
                u.transcription_status = "failed"
                fname = filename or u.filename
                await db.commit()
            else:
                fname = filename
        if fname:
            await _replace_document_card(upload_id, serialize_document_attachment(url, fname, ""))

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
        pdf_bytes = pdf_path.read_bytes()
        text_layer = extract_text(pdf_bytes)
        if text_layer:
            # Реальный текстовый слой (не скан) — один reflow-вызов на весь
            # документ (extract_text уже склеивает страницы), не постранично:
            # дёшево независимо от числа страниц, в отличие от vision ниже.
            result = await reflow_document_text(text_layer)
        else:
            page_texts: list[str] = []
            with pymupdf.open(pdf_path) as doc:
                for i, page in enumerate(doc):
                    if i >= _MAX_OCR_PAGES:
                        break
                    png_bytes = page.get_pixmap(dpi=150).tobytes("png")
                    description = await _vision_analyze(png_bytes, "image/png", settings.llm_api_key)
                    # Реальная жалоба: маркер классификации ("БИЛЕТ: да/нет" —
                    # первая строка ответа vision.py, нужна только чтобы решить,
                    # звать ли tickets.py; PDF-страницы туда не идут вовсе, см.
                    # ниже) утекал в видимый пользователю текст. vision.py._process
                    # для отдельных картинок его уже вырезает — здесь тот же приём.
                    _, description = _split_ticket_marker(description)
                    description = await reflow_document_text(description)
                    if description.strip():
                        page_texts.append(f"**Страница {i + 1}:**\n\n{description.strip()}")
            result = "\n\n---\n\n".join(page_texts)
    except Exception:
        logger.exception("Ошибка распознавания PDF %s", upload_id)
        await _fail(filename)
        return

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        upload.transcript = result
        upload.transcription_status = "done" if result.strip() else "failed"
        await db.commit()

    if not result.strip():
        logger.warning("OCR PDF %s не дал результата", upload_id)
        await _fail(filename)
        return

    formatted = serialize_document_attachment(url, filename, result)
    await _replace_document_card(upload_id, formatted)


async def run_worker() -> None:
    while True:
        upload_id = await _queue.get()
        try:
            await _process(upload_id)
        except Exception:
            logger.exception("Необработанная ошибка при OCR PDF %s", upload_id)
        finally:
            _queue.task_done()
