from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

import zxingcpp
from PIL import Image
from sqlalchemy import select

from app import realtime
from app.core.config import get_settings
from app.db import async_session
from app.llm.base import Message
from app.llm.factory import get_llm_client
from app.models import Item, Upload
from app.vision import _replace_in_referencing_items
from app.vision import placeholder_text as image_placeholder_text

logger = logging.getLogger(__name__)

# Второй шаг пайплайна билетов (первый — классификация внутри vision.py).
# Один воркер, тот же принцип, что у остальных фоновых пайплайнов проекта.
_queue: "asyncio.Queue[uuid.UUID]" = asyncio.Queue()

_MAX_TEXT_CHARS = 4000
_TICKET_TYPES = {"train", "flight", "bus", "event", "other"}

# Вход — уже готовые description+OCR-текст из upload.transcript (их
# получил и сохранил vision.py при классификации), не картинка заново:
# извлечение полей — обычный текстовый LLM-вызов через существующую
# swappable-абстракцию (app.llm), как autotag.py, а не второй запрос к
# vision-API — дешевле и не завязано на конкретного vision-провайдера.
_PROMPT = (
    "Тебе дано описание и распознанный текст с изображения билета "
    "(жд/авиа/автобусного/на мероприятие, посадочный талон и т.п.). "
    "Извлеки структурированные данные и ответь ТОЛЬКО JSON-объектом (без "
    "markdown-ограждений и пояснений) со следующими полями:\n"
    '{"ticket_type": "train|flight|bus|event|other", '
    '"datetime_start": "дата или дата и время начала в формате ISO 8601, '
    'null если не удалось определить", '
    '"datetime_end": "то же самое для окончания/прибытия, null если не '
    'применимо или неизвестно", '
    '"location_from": "место отправления или название места проведения, '
    'null если не применимо", '
    '"location_to": "место назначения, null если не применимо (билеты на '
    'мероприятие обычно без этого поля)", '
    '"seat": "место/вагон/посадочная группа текстом, null если не '
    'указано", '
    '"title": "короткое (до 60 символов) название для заметки, например '
    "'Билет Москва — Тула, 15.08'\"}\n"
    "Если что-то не удаётся определить — используй null, не выдумывай "
    "значения."
)


def enqueue_ticket_extraction(upload_id: uuid.UUID) -> None:
    _queue.put_nowait(upload_id)


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


def _decode_code(upload_id: uuid.UUID) -> str | None:
    """QR/штрихкод с исходного файла — только для билетов-картинок; PDF
    этот шаг не проходят (вне рамок текущей фазы). Первый найденный код —
    билет обычно несёт один; если их несколько, остальные теряются, не то
    что здесь нужно усложнять.

    zxing-cpp, не pyzbar/zbar: авиабилеты (IATA BCBP) почти всегда кодируют
    посадочный талон в Aztec, не QR — реальный случай поймал на живом
    посадочном Lufthansa, zbar вернул пустой результат на чёткой, хорошо
    читаемой картинке. zxing-cpp декодирует Aztec корректно (и QR тоже,
    без регресса) — подтверждено на обоих форматах."""
    path = _upload_path(upload_id)
    if not path.is_file():
        return None
    try:
        with Image.open(path) as img:
            results = zxingcpp.read_barcodes(img)
    except Exception:
        logger.exception("Ошибка декодирования QR/штрихкода для %s", upload_id)
        return None
    if not results:
        return None
    return results[0].text


def _parse_json_response(raw: str) -> dict | None:
    raw = raw.strip()
    # Та же терпимость к ```json-ограждениям, что в autotag.py.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _extract(transcript: str) -> dict | None:
    client = get_llm_client()
    response = await client.chat(
        [
            Message(role="system", content=_PROMPT),
            Message(role="user", content=transcript[:_MAX_TEXT_CHARS]),
        ],
        [],
    )
    return _parse_json_response(response.message.content)


def _build_properties(upload_id: uuid.UUID, data: dict, code: str | None) -> dict:
    ticket_type = data.get("ticket_type")
    if ticket_type not in _TICKET_TYPES:
        ticket_type = "other"
    return {
        "ticket_type": ticket_type,
        "datetime_start": data.get("datetime_start") or None,
        "datetime_end": data.get("datetime_end") or None,
        "location_from": data.get("location_from") or None,
        "location_to": data.get("location_to") or None,
        "seat": data.get("seat") or None,
        "code": code,
        "upload_id": str(upload_id),
    }


def _esc(s: str) -> str:
    # Тот же порядок экранирования, что serialize_document_attachment в
    # pdf_processing.py — весь тег должен остаться на одной строке
    # (markdown-it иначе оборвал бы html_block на первой пустой строке).
    return s.replace("&", "&amp;").replace("\n", "&#10;").replace('"', "&quot;")


def _serialize_ticket_card(url: str, filename: str, data: dict, raw_text: str, code: str | None) -> str:
    parts = [f'data-url="{_esc(url)}"']
    if filename:
        parts.append(f'data-filename="{_esc(filename)}"')
    ticket_type = data.get("ticket_type") or "other"
    if ticket_type not in _TICKET_TYPES:
        ticket_type = "other"
    parts.append(f'data-ticket-type="{_esc(ticket_type)}"')
    for key, attr in (
        ("datetime_start", "data-datetime-start"),
        ("datetime_end", "data-datetime-end"),
        ("location_from", "data-location-from"),
        ("location_to", "data-location-to"),
        ("seat", "data-seat"),
        ("title", "data-title"),
    ):
        value = data.get(key)
        if value:
            parts.append(f'{attr}="{_esc(str(value))}"')
    if code:
        parts.append(f'data-code="{_esc(code)}"')
    if raw_text:
        # data-text, не data-raw-text: полнотекстовый поиск (миграция 0015,
        # notenotes_extract_attr_text) вытаскивает для индекса только
        # атрибут ИМЕННО с этим именем — тот же приём, что у карточки PDF
        # (DocumentAttachmentCard/data-text), билет тоже должен находиться
        # поиском по месту/дате/тексту.
        parts.append(f'data-text="{_esc(raw_text)}"')
    return f"<div data-ticket-attachment {' '.join(parts)}></div>"


_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_SECONDS = 2.0


async def _finalize_ticket_item(upload_id: uuid.UUID, old: str, new: str, properties: dict) -> None:
    # Как vision._replace_in_referencing_items (тот же retry — плейсхолдер
    # может ещё не долететь до сервера дебаунсом автосохранения), но
    # дополнительно проставляет material_type/properties на том же Item в
    # той же транзакции: реиспользовать generic-хелпер напрямую нельзя, у
    # него нет места передать эти поля, а отдельным запросом — гонка с
    # этим же commit.
    for attempt in range(_REPLACE_RETRY_ATTEMPTS):
        async with async_session() as db:
            result = await db.execute(select(Item).where(Item.content.like(f"%{upload_id}%")))
            items = result.scalars().all()
            touched_spaces = set()
            for item in items:
                if old in item.content:
                    item.content = item.content.replace(old, new)
                    item.material_type = "ticket"
                    item.properties = {**item.properties, **properties}
                    touched_spaces.add(item.space_id)
            if touched_spaces:
                await db.commit()
                for space_id in touched_spaces:
                    await realtime.notify_space(space_id, "items")
                return
        if attempt < _REPLACE_RETRY_ATTEMPTS - 1:
            await asyncio.sleep(_REPLACE_RETRY_DELAY_SECONDS)


async def _process(upload_id: uuid.UUID) -> None:
    settings = get_settings()
    if not settings.llm_api_key:
        logger.error("LLM_API_KEY не задан — извлечение данных билета %s невозможно", upload_id)
        return

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        transcript = upload.transcript or ""
        filename = upload.filename

    if not transcript.strip():
        logger.warning("Пустой transcript для билета %s — извлечение пропущено", upload_id)
        return

    try:
        data = await _extract(transcript)
    except Exception:
        logger.exception("Ошибка извлечения данных билета %s", upload_id)
        data = None

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is not None:
            upload.transcription_status = "done" if data else "failed"
            await db.commit()

    if not data:
        # Не удалось извлечь структуру — не оставляем заметку висеть на
        # плейсхолдере вечно: показываем как обычное распознанное
        # изображение, тем же путём, что vision.py для не-билетов.
        formatted = f"**Изображение:**\n\n{transcript}"
        await _replace_in_referencing_items(upload_id, image_placeholder_text(upload_id), formatted)
        return

    code = _decode_code(upload_id)
    properties = _build_properties(upload_id, data, code)
    card = _serialize_ticket_card(f"/api/uploads/{upload_id}", filename, data, transcript, code)
    await _finalize_ticket_item(upload_id, image_placeholder_text(upload_id), card, properties)


async def run_worker() -> None:
    while True:
        upload_id = await _queue.get()
        try:
            await _process(upload_id)
        except Exception:
            logger.exception("Необработанная ошибка при извлечении данных билета %s", upload_id)
        finally:
            _queue.task_done()
