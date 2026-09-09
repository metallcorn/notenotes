from __future__ import annotations

import asyncio
import base64
import logging
import re
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select

from app import collab, realtime
from app.core.config import get_settings
from app.db import async_session
from app.document_reflow import reflow_document_text
from app.models import Item, ItemVersion, Upload
from app.rotation import correct_orientation

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
    "автобусный/на мероприятие, посадочный талон, электронный билет и т.п. — "
    "если в кратком описании ниже ты сам называешь это билетом, здесь тоже "
    "должно быть «да») — строго «БИЛЕТ: да» или «БИЛЕТ: нет», БЕЗ markdown-"
    "разметки (не заголовок, не жирный текст, без ** и #), больше ничего в "
    "этой строке. Затем с новой строки — "
    "опиши это изображение кратко (одно-два предложения, что на нём) и, если "
    "на изображении есть читаемый текст, приведи его дословно после описания "
    "под заголовком «Текст на изображении». В дословном тексте перепиши "
    "АБСОЛЮТНО ВСЕ строки подряд, включая мелкий/тонкий/светлый текст над или "
    "рядом с крупным заголовком (даты, время, подписи) — не пропускай их и не "
    "считай, что раз ты уже упомянул это в кратком описании выше, повторять в "
    "дословном тексте не нужно: дословный текст — самостоятельная полная "
    "копия, а не дополнение к описанию.\n\n"
    "Реальный найденный случай: официальный документ с ДВУМЯ визуально "
    "разными блоками на одном фото (сверху — рамка/таблица «для служебных "
    "отметок» со своими ФИО/датой/местом рождения, ниже — основной текст "
    "справки) — модель распознала только основной блок текста, а верхнюю "
    "рамку с датой и местом рождения пропустила целиком, как будто её не "
    "было. Если на изображении есть ЛЮБАЯ отдельная рамка, таблица, штамп, "
    "печать или блок в углу/сверху/снизу — это не оформление, а часть "
    "документа с собственным текстом, который тоже нужно перечислить "
    "дословно, даже если он визуально не связан с основным текстом и стоит "
    "особняком.\n\n"
    "Если на изображении есть чёткая сетка полей «подпись поля — значение» "
    "(билет/посадочный талон, паспорт, ID-карта, водительское "
    "удостоверение, регистрационное свидетельство, любая анкета/форма) — "
    "«Текст на изображении» оформи ГЛАВНЫМ ОБРАЗОМ markdown-таблицей из "
    "двух колонок «Поле» и «Значение», каждая пара подпись/значение — "
    "отдельная строка таблицы, а не текстом подряд построчно. Цель — чтобы "
    "результат в Markdown визуально был близок к оригиналу настолько, "
    "насколько это вообще возможно объективно, а не голым потоком строк, "
    "как если бы читали документ построчно сверху вниз не глядя на "
    "разметку. Реальная жалоба: распознанный текст паспорта/билета шёл "
    "сплошным потоком строк («подпись поля» на одной строке, «значение» на "
    "следующей, и так по кругу), хотя на самой картинке это чёткая таблица "
    "полей. Всё, что НЕ уложилось в таблицу (машиночитаемая зона паспорта, "
    "штрих/QR-код текстом, серийные номера, мелкие пометки) — перечисли "
    "строками под таблицей, ничего не пропуская, тот же принцип "
    "дословности, что и выше.\n\n"
    "Остальное отвечай только результатом, без вступлений и комментариев, в "
    "формате Markdown, на русском языке."
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
#
# Реальный найденный случай (дважды подряд, живые данные): посадочный
# талон LOT Polish Airlines и ещё несколько билетов модель в КРАТКОМ
# ОПИСАНИИ прямо назвала "билет"/"посадочный талон" словами, но строгий
# маркер первой строкой не сработал — вероятно, модель обернула его в
# markdown (**БИЛЕТ: да**) вместо голого текста, как просили. Регэксп
# терпим к markdown-обёртке и к паре пустых строк перед маркером; если
# маркера нет вообще, но текст СРАЗУ (в первом предложении, не где-то в
# середине) называет изображение билетом/посадочным талоном — тоже билет.
# Осознанно узкий фолбэк (только начало текста, только эти два слова) —
# не пытается угадывать billet по любому упоминанию где угодно в тексте,
# то давало бы ложные срабатывания на случайное упоминание слова "билет".
_TICKET_MARKER_RE = re.compile(r"^\**#{0,3}\s*БИЛЕТ:?\**\s*[:—-]?\s*(да|нет)\b", re.IGNORECASE)
_TICKET_FALLBACK_RE = re.compile(r"^.{0,40}?\b(билет|посадочный талон)\w*", re.IGNORECASE | re.DOTALL)


def _split_ticket_marker(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    m = _TICKET_MARKER_RE.match(stripped)
    if not m:
        if _TICKET_FALLBACK_RE.match(stripped):
            return True, text
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


def serialize_image_ocr_result(upload_id: uuid.UUID, text: str, content_type: str = "") -> str:
    """Тот же формат, что сериализует ImageOcrResult.ts на фронте — раньше
    результат распознавания вставлялся голым абзацем прямо в заметку
    (реальная жалоба: засоряет заметку, особенно у картинок с таблицами/
    длинным текстом), теперь сворачиваемая карточка, как у распознанного
    текста PDF. Сама картинка (обычный <img>) не трогается — этот узел
    просто занимает место старого текстового плейсхолдера рядом с ней.

    upload_id — реальная жалоба: карточка не знала, из какого upload она
    получена, поэтому не было ни кнопки "распознать заново", ни ручной
    правки текста, если распознавание ошиблось. content_type определяет
    data-can-reprocess: /api/uploads/{id}/reprocess сейчас умеет только
    image/video/pdf — для аудио (расшифровка голосовых записей,
    note_recording.py — отдельный пайплайн, не через этот эндпоинт) кнопку
    "распознать заново" не показываем, чтобы не предлагать нерабочее
    действие; ручная правка текста работает для всех одинаково."""

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("\n", "&#10;").replace('"', "&quot;")

    can_reprocess = content_type.startswith(("image/", "video/")) or content_type == "application/pdf"
    reprocess_attr = ' data-can-reprocess="1"' if can_reprocess else ""
    return f'<div data-image-ocr-result data-text="{esc(text)}" data-upload-id="{upload_id}"{reprocess_attr}></div>'


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


async def _replace_by_pattern(upload_id: uuid.UUID, pattern: re.Pattern, new: str, *, snapshot_version: bool = False) -> bool:
    for attempt in range(_REPLACE_RETRY_ATTEMPTS):
        async with async_session() as db:
            result = await db.execute(select(Item).where(Item.content.like(f"%{upload_id}%")))
            items = result.scalars().all()
            touched_spaces = set()
            touched_item_ids = []
            for item in items:
                # Замена ФУНКЦИЕЙ, а не строкой — см. pdf_processing.py:
                # re.subn разбирает строку замены как шаблон, где обратный
                # слэш особый, и падает на распознанном тексте, где он
                # обычный символ. В PDF это уже случилось живьём
                # ("bad escape \Z"), а сюда приходит текст ровно того же
                # происхождения — распознанный из чужого документа.
                new_content, n = pattern.subn(lambda _match: new, item.content)
                if n:
                    if snapshot_version:
                        db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=item.author_id))
                    item.content = new_content
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
                return True
        if attempt < _REPLACE_RETRY_ATTEMPTS - 1:
            await asyncio.sleep(_REPLACE_RETRY_DELAY_SECONDS)
    return False


async def _replace_in_referencing_items(upload_id: uuid.UUID, old: str, new: str) -> None:
    await _replace_by_pattern(upload_id, re.compile(re.escape(old)), new)


_IMAGE_OCR_CARD_RE_TEMPLATE = r'<div data-image-ocr-result[^>]*data-upload-id="{}"[^>]*></div>'


async def replace_recognized_text_card(
    upload_id: uuid.UUID, placeholder: str | None, new_card_html: str, *, snapshot_version: bool = False
) -> bool:
    """Заменяет карточку распознанного текста (общий тег data-image-ocr-result
    — используется одинаково vision.py/transcription.py/note_recording.py)
    — либо ЕЩЁ плейсхолдер "...обрабатывается…" (первая обработка, если он
    передан), либо УЖЕ существующую карточку этого upload_id, найденную по
    data-upload-id (повторное распознавание либо ручная правка текста —
    оба случая заменяют готовую карточку, а не плейсхолдер). Раньше замена
    умела искать только точный плейсхолдер — повторный запуск распознавания
    на уже готовой картинке молча ничего не находил и не обновлял заметку."""
    card_pattern = _IMAGE_OCR_CARD_RE_TEMPLATE.format(re.escape(str(upload_id)))
    pattern = re.compile(f"{re.escape(placeholder)}|{card_pattern}" if placeholder else card_pattern)
    return await _replace_by_pattern(upload_id, pattern, new_card_html, snapshot_version=snapshot_version)


async def _analyze(image_bytes: bytes, content_type: str, api_key: str) -> str:
    # Реальный найденный случай: повёрнутая на 90°/180°/270° страница —
    # vision-модель читает текст криво и путает содержимое (например,
    # регион в штампе). Tesseract OSD определяет угол механически, по
    # форме символов, до всякого обращения к LLM — дёшево и детерминированно.
    # Единая точка для всех вызывающих (фоновый воркер ниже, describe_upload_now,
    # pdf_processing.py — все идут через эту функцию).
    image_bytes = correct_orientation(image_bytes)
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


# Реальная жалоба ("постоянно что-то зависает в фоне"): все точки отказа
# ниже раньше молча оставляли плейсхолдер "⏳ ...обрабатывается…" висеть
# НАВСЕГДА — transcription_status уходил в "failed" в БД, а сама заметка
# продолжала показывать вечный "в процессе", неотличимый от настоящего
# зависания. pdf_processing.py эту дыру уже не имеет (сбрасывает карточку
# в "не обработано"); vision.py/transcription.py её унаследовали при
# копировании паттерна и никогда не получили тот же фикс.
_FAILURE_MESSAGE = "⚠️ Распознавание изображения не удалось."
_EMPTY_MESSAGE = "🔍 Не удалось ничего распознать на изображении."


async def _process(upload_id: uuid.UUID) -> None:
    settings = get_settings()

    async def _fail(message: str = _FAILURE_MESSAGE) -> None:
        async with async_session() as db:
            u = await db.get(Upload, upload_id)
            if u is not None:
                u.transcription_status = "failed"
                await db.commit()
        await replace_recognized_text_card(upload_id, placeholder_text(upload_id), message)

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

    # Билеты идут в tickets.py за структурированным извлечением — там
    # своя, ещё более конкретная раскладка по полям, причёсывать текстом
    # тут смысла нет. Для остального (в т.ч. сфотографированные документы —
    # реально частый случай, не реже PDF) — тот же проход причёсывания
    # вёрстки, что и у pdf_processing.py.
    if not is_ticket and description.strip():
        description = await reflow_document_text(description)

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
        await replace_recognized_text_card(upload_id, placeholder_text(upload_id), _EMPTY_MESSAGE)
        return

    formatted = serialize_image_ocr_result(upload_id, description, content_type)
    await replace_recognized_text_card(upload_id, placeholder_text(upload_id), formatted)


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


_STUCK_PLACEHOLDER_PREFIX = "⏳ Описание изображения "


async def resume_stuck_replacements() -> None:
    """Реальный найденный баг (живые данные): если процесс обрывается МЕЖДУ
    записью transcription_status="done" (_process, после успешного вызова
    Mistral) и вызовом _replace_in_referencing_items чуть ниже — распознавание
    полностью посчитано (upload.transcript заполнен), но плейсхолдер "⏳ ...
    обрабатывается…" в заметке так и остаётся навсегда: enqueue_vision
    вызывается только один раз, при загрузке файла, больше НИКТО не
    пытается доделать замену. resume_pending() (выше) эту ситуацию не
    ловит — статус уже "done", не "pending"/"processing". На старте —
    один проход: найти заметки, где плейсхолдер ещё виден, и доделать
    замену из уже посчитанного upload.transcript (без повторного дорогого
    запроса к Mistral)."""
    async with async_session() as db:
        stuck_items = (
            await db.execute(select(Item.content).where(Item.content.like(f"%{_STUCK_PLACEHOLDER_PREFIX}%")))
        ).scalars().all()
    if not stuck_items:
        return

    upload_ids: set[uuid.UUID] = set()
    id_re = re.compile(re.escape(_STUCK_PLACEHOLDER_PREFIX) + r"([0-9a-fA-F-]{36})")
    for content in stuck_items:
        upload_ids |= {uuid.UUID(m) for m in id_re.findall(content)}

    async with async_session() as db:
        uploads = (await db.execute(select(Upload).where(Upload.id.in_(upload_ids)))).scalars().all()

    for upload in uploads:
        if upload.transcription_status != "done" or not (upload.transcript or "").strip():
            continue
        logger.info("Довершаю зависшую замену плейсхолдера для %s (найдено при старте)", upload.id)
        formatted = serialize_image_ocr_result(upload.id, upload.transcript, upload.content_type)
        await replace_recognized_text_card(upload.id, placeholder_text(upload.id), formatted)
