from __future__ import annotations

import asyncio
import base64
import logging
import re
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
    "Сначала одной строкой ответь, похоже ли изображение на билет (жд/авиа/"
    "автобусный/на мероприятие, посадочный талон и т.п.) — строго «БИЛЕТ: да» "
    "или «БИЛЕТ: нет», больше ничего в этой строке. Затем с новой строки — "
    "опиши это изображение кратко (одно-два предложения, что на нём) и, если "
    "на изображении есть читаемый текст, приведи его дословно после описания "
    "под заголовком «Текст на изображении». В дословном тексте перепиши "
    "АБСОЛЮТНО ВСЕ строки подряд, включая мелкий/тонкий/светлый текст над или "
    "рядом с крупным заголовком (даты, время, подписи) — не пропускай их и не "
    "считай, что раз ты уже упомянул это в кратком описании выше, повторять в "
    "дословном тексте не нужно: дословный текст — самостоятельная полная "
    "копия, а не дополнение к описанию. Остальное отвечай только "
    "результатом, без вступлений и комментариев, в формате Markdown, на "
    "русском языке."
)

# Билеты — отдельный пайплайн (tickets.py) со своим структурированным
# извлечением полей, но классификация "это билет?" встроена в этот же
# vision-вызов, а не отдельный LLM-запрос — эта проверка почти всегда
# отрицательная (подавляющее большинство загрузок не билеты), так что
# отдельный запрос "не билет ли это" на каждую картинку был бы чистым
# расходом. Маркер первой строкой, не JSON — существующий формат ответа
# уже свободный текст (markdown-описание), переводить весь вызов на
# строгий JSON рискованно сломать обычные описания; терпимый парсинг той
# же строки (как ```json-ограждения в autotag.py) — тот же принцип.
_TICKET_MARKER_RE = re.compile(r"^БИЛЕТ:\s*(да|нет)\b", re.IGNORECASE)


def _split_ticket_marker(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    m = _TICKET_MARKER_RE.match(stripped)
    if not m:
        return False, text
    is_ticket = m.group(1).lower() == "да"
    rest = stripped[m.end() :].lstrip(" \n")
    return is_ticket, rest

# Не гоняем на анализ огромные фото без нужды (тот же принцип, что 10 МБ
# звука для видео) — 8 МБ с запасом хватает на любое реалистичное фото с
# телефона в разумном качестве.
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def placeholder_text(upload_id: uuid.UUID) -> str:
    # Без квадратных скобок — см. transcription.placeholder_text: они
    # экранируются в \[ \] при автосохранении WYSIWYG-редактора и ломают
    # поиск-замену плейсхолдера на готовый результат.
    return f"⏳ Описание изображения {upload_id} обрабатывается…"


def serialize_image_ocr_result(text: str) -> str:
    """Тот же формат, что сериализует ImageOcrResult.ts на фронте — раньше
    результат распознавания вставлялся голым абзацем прямо в заметку
    (реальная жалоба: засоряет заметку, особенно у картинок с таблицами/
    длинным текстом), теперь сворачиваемая карточка, как у распознанного
    текста PDF. Сама картинка (обычный <img>) не трогается — этот узел
    просто занимает место старого текстового плейсхолдера рядом с ней."""

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("\n", "&#10;").replace('"', "&quot;")

    return f'<div data-image-ocr-result data-text="{esc(text)}"></div>'


def enqueue_vision(upload_id: uuid.UUID) -> None:
    _queue.put_nowait(upload_id)


# Обработка (эта функция) запускается сразу при загрузке файла — на
# сервере, синхронно с созданием Upload — а плейсхолдер в content заметки
# появляется на клиенте позже и сохраняется только после debounce
# автосохранения (NoteEditor.tsx, 1200мс). Для маленького файла
# распознавание иногда успевает закончиться раньше, чем текст с
# плейсхолдером вообще долетит до бэкенда — первая попытка замены тогда
# видит заметку ещё без плейсхолдера и заменять нечего. Несколько попыток
# с паузой перекрывают этот зазор с запасом, не перестраивая сам поток.
_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_SECONDS = 2.0


async def _replace_in_referencing_items(upload_id: uuid.UUID, old: str, new: str) -> None:
    for attempt in range(_REPLACE_RETRY_ATTEMPTS):
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
                return
        if attempt < _REPLACE_RETRY_ATTEMPTS - 1:
            await asyncio.sleep(_REPLACE_RETRY_DELAY_SECONDS)


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
        raw = await _analyze(image_bytes, content_type, settings.llm_api_key)
    except Exception:
        logger.exception("Ошибка Mistral vision при анализе %s", upload_id)
        await _fail()
        return

    is_ticket, description = _split_ticket_marker(raw)

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        upload.transcript = description
        # Билет остаётся "processing" — финальный статус (done/failed)
        # проставит tickets.py, когда закончит структурированное
        # извлечение; плейсхолдер в заметке (тот же самый) висит до тех пор.
        upload.transcription_status = "processing" if is_ticket else ("done" if description.strip() else "failed")
        await db.commit()

    if is_ticket and description.strip():
        # Локальный импорт: tickets.py импортирует _replace_in_referencing_items
        # и placeholder_text отсюда на уровне модуля (как pdf_processing.py) —
        # обычный top-level импорт друг друга дал бы цикл, поэтому обратное
        # направление (vision → tickets) — отложенный импорт по месту вызова.
        from app import tickets

        tickets.enqueue_ticket_extraction(upload_id)
        return

    if not description.strip():
        logger.warning("Mistral vision вернул пустой результат для %s", upload_id)
        return

    formatted = serialize_image_ocr_result(description)
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
