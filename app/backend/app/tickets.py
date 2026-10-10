from __future__ import annotations

import asyncio
import re
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import zxingcpp
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import collab, realtime
from app.core.config import get_settings
from app.db import async_session
from app.llm.base import Message
from app.llm.factory import get_llm_client
from app.models import Item, Notification, Upload, User
from app.user_timezone import assume_default_timezone
from app.vision import _replace_in_referencing_items
from app.vision import placeholder_text as image_placeholder_text
from app.vision import serialize_image_ocr_result
from app.processing_status import STATUS_EMPTY

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
    '"flight_number": "номер рейса как на билете, например \'W6 1234\' или '
    '\'LO 123\' — только для авиабилетов, иначе null", '
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
        "flight_number": data.get("flight_number") or None,
        "code": code,
        "upload_id": str(upload_id),
    }


def _esc(s: str) -> str:
    # Тот же порядок экранирования, что serialize_document_attachment в
    # pdf_processing.py — весь тег должен остаться на одной строке
    # (markdown-it иначе оборвал бы html_block на первой пустой строке).
    return s.replace("&", "&amp;").replace("\n", "&#10;").replace('"', "&quot;")


# search_base — буквальный полнотекстовый поиск без понимания синонимов
# (см. промпт: "'купить'/'покупка'/'закупка' — разные слова"). OCR-описание
# билета говорит "посадочный талон"/"билет на автобус" и т.п., а реальный
# пользователь чаще спрашивает обиходным словом — "авиабилет", "жд билет" —
# которое буквально нигде в распознанном тексте не встречается. Реальный
# случай: "какие у меня авиабилеты" не нашёл НИ ОДНОГО реального билета
# (оба были в базе), модель полезла в теги вместо list_all_items и
# нафантазировала билеты из совершенно посторонних заметок. Тот же
# приём, что transliterate.py для транслитерации — закрываем словарный
# разрыв детерминированно на стороне данных, а не понадеявшись на то, что
# модель сама пойдёт по запасному пути.
_SEARCH_SYNONYMS: dict[str, str] = {
    "flight": "авиабилет самолёт рейс перелёт",
    "train": "жд билет поезд ЖД",
    "bus": "автобусный билет автобус",
    "event": "билет на мероприятие",
}

# Те же подписи, что TICKET_LABELS в TicketAttachmentCard.tsx (кнопка
# "Напомнить") — автоматическое уведомление ниже должно звучать так же,
# как уже сделанное вручную.
# За сколько до начала напоминать. Живой случай 15.09.2026: напоминание
# об авиарейсе пришло РОВНО в момент вылета — когда человек уже сидел в
# самолёте. Ноль опережения бессмыслен для всего, куда надо приехать
# заранее.
#
# Самолёт — три часа: регистрация, досмотр, дорога в аэропорт. Поезд и
# автобус — час: вокзал ближе и без досмотра. Мероприятие — два часа:
# собраться и доехать. «Другое» — час, как самое частое.
_LEAD_TIME: dict[str, timedelta] = {
    "flight": timedelta(hours=3),
    "train": timedelta(hours=1),
    "bus": timedelta(hours=1),
    "event": timedelta(hours=2),
    "other": timedelta(hours=1),
}

_FLIGHT_NUMBER_RE = re.compile(r"\b([A-Z][A-Z0-9]|[0-9][A-Z])\s?(\d{1,4})\b")


def extract_flight_number(*sources: str | None) -> str | None:
    """Номер рейса — из поля распознавания или, для старых билетов, из
    заголовка («Рейс W6 1234 Познань — Рим»). IATA-код авиакомпании —
    две буквы/цифры, дальше 1–4 цифры."""
    for src in sources:
        if not src:
            continue
        cleaned = src.strip().upper()
        found = _FLIGHT_NUMBER_RE.search(cleaned)
        if found:
            return f"{found.group(1)}{found.group(2)}"
    return None


def flight_tracking_url(flight_number: str) -> str:
    """Где смотреть статус рейса — задержан, отменён, с какого гейта.

    Flightradar24 понимает код рейса в адресе напрямую и показывает и
    сегодняшний вылет, и историю задержек этого рейса. Запрос владельца:
    если рейс отменяется, узнать об этом хочется из того же уведомления,
    а не искать сайт.
    """
    return f"https://www.flightradar24.com/data/flights/{flight_number.lower()}"


_TICKET_LABELS: dict[str, str] = {
    "train": "ЖД-билет",
    "flight": "Авиабилет",
    "bus": "Автобусный билет",
    "event": "Билет на мероприятие",
    "other": "Билет",
}


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
        # поиском по месту/дате/тексту. Синонимы (_SEARCH_SYNONYMS выше)
        # добавляем ПЕРЕД текстом, а не вместо него — сам OCR-текст всё
        # равно нужен для поиска по месту/имени/дате.
        synonyms = _SEARCH_SYNONYMS.get(ticket_type, "")
        text_for_index = f"{synonyms}\n\n{raw_text}" if synonyms else raw_text
        parts.append(f'data-text="{_esc(text_for_index)}"')
    return f"<div data-ticket-attachment {' '.join(parts)}></div>"


_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_SECONDS = 2.0


async def _add_event_notification(db: AsyncSession, item: Item, properties: dict, title: str | None) -> None:
    """Реальная жалоба: билет с датой сегодня/завтра распознавался и лежал
    в заметке, но пользователь узнавал о нём, только если сам догадывался
    зайти и посмотреть — колокольчик молчал, пока кто-то вручную не нажмёт
    "Напомнить" на карточке. Сразу при распознавании ставим уведомление на
    момент начала (datetime_start) — тем же путём, что и ручная кнопка
    (тот же Notification, тот же дальнейший dispatcher/Telegram/push), без
    отдельного "утреннего" сигнала (осознанно, по решению пользователя)."""
    raw_start = properties.get("datetime_start")
    if not raw_start:
        return
    try:
        trigger_at = datetime.fromisoformat(str(raw_start))
    except ValueError:
        return
    author = await db.get(User, item.author_id)
    # Реальный найденный баг: наивное время билета (без пояса) трактовалось
    # как UTC — время события в Польше летом (CEST, UTC+2) на экране
    # сдвигалось на 2 часа вперёд. assume_default_timezone трактует его как
    # ДОМАШНИЙ пояс автора заметки (билет описывает факт о конкретном рейсе/
    # мероприятии, не зависящий от того, где автор сейчас физически
    # находится), не UTC (app/user_timezone.py).
    trigger_at = assume_default_timezone(trigger_at, author.timezone if author else None)
    ticket_type = properties.get("ticket_type") or "other"
    # Напоминание — ЗАРАНЕЕ, не в момент начала. Если билет распознан уже
    # после этого момента (загрузили посадочный в аэропорту), шлём сразу:
    # trigger_at в прошлом диспетчер отправляет немедленно.
    trigger_at = trigger_at - _LEAD_TIME.get(ticket_type, _LEAD_TIME["other"])

    # Защита от дубля при повторном распознавании (кнопка "Распознать
    # снова" на карточке билета) — без неё пользователь получил бы второе
    # напоминание на то же самое событие.
    existing = await db.execute(
        select(Notification.id).where(
            Notification.type == "ticket_event",
            Notification.payload["item_id"].astext == str(item.id),
        )
    )
    if existing.first() is not None:
        return

    label = _TICKET_LABELS.get(ticket_type, _TICKET_LABELS["other"])
    location_from = properties.get("location_from") or ""
    location_to = properties.get("location_to") or ""
    body = f"{location_from}{' → ' if location_from and location_to else ''}{location_to}"
    lead = _LEAD_TIME.get(ticket_type, _LEAD_TIME["other"])
    hours = int(lead.total_seconds() // 3600)
    body = f"{body}\nЧерез {hours} ч" if body else f"Через {hours} ч"
    if ticket_type == "flight":
        flight = extract_flight_number(properties.get("flight_number"), title, item.title)
        if flight:
            # Ссылка — в тексте уведомления: Telegram и push покажут её
            # кликабельной, и статус рейса в одном касании от напоминания.
            body = f"{body}\nСтатус рейса: {flight_tracking_url(flight)}"

    db.add(
        Notification(
            user_id=item.author_id,
            type="ticket_event",
            title=f"{label}: {title or item.title or label}",
            body=body,
            payload={"item_id": str(item.id), "space_id": str(item.space_id), "material_type": "ticket"},
            trigger_at=trigger_at,
        )
    )


async def _finalize_ticket_item(upload_id: uuid.UUID, old: str, new: str, properties: dict, title: str | None) -> None:
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
            touched_item_ids = []
            for item in items:
                if old in item.content:
                    item.content = item.content.replace(old, new)
                    item.material_type = "ticket"
                    item.properties = {**item.properties, **properties}
                    # Раньше title не трогали вовсе — заметка так и оставалась
                    # с родовым названием исходного фото ("Фото"), хотя LLM
                    # уже извлёк нормальное короткое название ("Билет
                    # Дубай — Джакарта, 14.04"). Реальный найденный эффект:
                    # ассистент не мог найти собственные билеты пользователя
                    # ни по названию, ни по полнотекстовому поиску — заголовок
                    # ничего не говорил о содержимом.
                    if title and (not item.title or item.title == "Фото"):
                        item.title = title
                    await _add_event_notification(db, item, properties, title)
                    touched_spaces.add(item.space_id)
                    touched_item_ids.append(item.id)
            if touched_spaces:
                await db.commit()
                for space_id in touched_spaces:
                    await realtime.notify_space(space_id, "items")
                # Заметка могла быть открыта с живой коллаборацией — её
                # Y.Doc ничего не знает про эту прямую правку в БД, см.
                # collab.invalidate_room.
                for item_id in touched_item_ids:
                    await collab.invalidate_room(item_id)
                return
        if attempt < _REPLACE_RETRY_ATTEMPTS - 1:
            await asyncio.sleep(_REPLACE_RETRY_DELAY_SECONDS)


async def _fail_stuck_ticket(upload_id: uuid.UUID) -> None:
    # Тот же класс бага, что чинили в vision.py/transcription.py: билет
    # остаётся "processing" (см. vision.py._process) до тех пор, пока
    # ЭТА функция не проставит финальный статус — если она сама выходит
    # раньше срока, плейсхолдер "⏳ ...обрабатывается…" висит навсегда.
    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is not None:
            upload.transcription_status = "failed"
            await db.commit()
    await _replace_in_referencing_items(
        upload_id, image_placeholder_text(upload_id), "⚠️ Не удалось обработать билет."
    )


async def _process(upload_id: uuid.UUID) -> None:
    settings = get_settings()
    if not settings.llm_api_key:
        logger.error("LLM_API_KEY не задан — извлечение данных билета %s невозможно", upload_id)
        await _fail_stuck_ticket(upload_id)
        return

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is None:
            return
        transcript = upload.transcript or ""
        filename = upload.filename
        content_type = upload.content_type

    if not transcript.strip():
        logger.warning("Пустой transcript для билета %s — извлечение пропущено", upload_id)
        await _fail_stuck_ticket(upload_id)
        return

    try:
        data = await _extract(transcript)
    except Exception:
        logger.exception("Ошибка извлечения данных билета %s", upload_id)
        data = None

    async with async_session() as db:
        upload = await db.get(Upload, upload_id)
        if upload is not None:
            upload.transcription_status = "done" if data else STATUS_EMPTY
            await db.commit()

    if not data:
        # Не удалось извлечь структуру — не оставляем заметку висеть на
        # плейсхолдере вечно: показываем как обычное распознанное
        # изображение, тем же путём, что vision.py для не-билетов.
        formatted = serialize_image_ocr_result(upload_id, transcript, content_type)
        await _replace_in_referencing_items(upload_id, image_placeholder_text(upload_id), formatted)
        return

    code = _decode_code(upload_id)
    properties = _build_properties(upload_id, data, code)
    card = _serialize_ticket_card(f"/api/uploads/{upload_id}", filename, data, transcript, code)
    title = str(data.get("title") or "").strip()[:60] or None
    await _finalize_ticket_item(upload_id, image_placeholder_text(upload_id), card, properties, title)


async def run_worker() -> None:
    while True:
        upload_id = await _queue.get()
        try:
            await _process(upload_id)
        except Exception:
            logger.exception("Необработанная ошибка при извлечении данных билета %s", upload_id)
        finally:
            _queue.task_done()
