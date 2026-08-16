from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app import realtime
from app.core.config import get_settings
from app.db import async_session
from app.llm.base import Message
from app.llm.factory import get_llm_client
from app.models import Item, ItemTag, Tag

logger = logging.getLogger(__name__)

# Авто-теги через LLM (ТЗ §8.2, CLAUDE.md — "предлагают, а не молча
# перекладывают"): визуально помечаются на фронте (ItemTag.auto) и легко
# удаляются, но сама простановка происходит в фоне без блокирующего
# подтверждения — то же решение, что уже принято для видео/картинок,
# только тут результат не текст в заметке, а сама пометка тега.
#
# Один воркер — один запрос к LLM за раз, тот же принцип троттлинга, что у
# transcription.py/vision.py. Только для заметок (не списков — у списков
# нет UI для тегов, автоматически размечать то, что нельзя посмотреть и
# убрать, противоречило бы самому смыслу правила).
_queue: "asyncio.Queue[uuid.UUID]" = asyncio.Queue()

_MAX_SUGGESTIONS = 5
_MAX_CONTENT_CHARS = 4000
_MAX_EVENTS = 5
_MAX_ADDRESSES = 5


def enqueue_autotag(item_id: uuid.UUID) -> None:
    _queue.put_nowait(item_id)


def _build_prompt(existing_tag_names: list[str], today: str) -> str:
    # Теги, события и адреса — в ОДНОМ вызове, не в трёх: реальная жалоба
    # на "разбухание", а тут это ещё и деньги — заметка и так уже гоняется
    # через LLM на каждое автосохранение ради тегов, отдельный вызов на
    # каждую новую задачу удваивал/утраивал бы стоимость без необходимости.
    existing = ", ".join(existing_tag_names) if existing_tag_names else "(тегов пока нет)"
    return (
        "Изучи заметку пользователя и ответь ТОЛЬКО одним JSON-объектом с "
        'тремя полями — без markdown-ограждений и пояснений.\n\n'
        '1) "tags": от 1 до 5 тегов по смыслу содержимого, коротких (1-2 '
        "слова), на языке заметки. Уже существующие теги пользователя: "
        f"{existing}. Если подходящий тег уже есть среди существующих — "
        "используй его дословно (то же написание), не создавай почти "
        "дубликат нового слова (например, если есть тег 'покупки' — не "
        "предлагай 'покупка' или 'shopping'). Новый тег предлагай, только "
        "если среди существующих действительно ничего подходящего нет. "
        "Если заметка слишком короткая/бессодержательная для осмысленных "
        "тегов — пустой массив.\n\n"
        '2) "events": конкретные даты/события из заметки — встречи, '
        "дедлайны, поездки, дни рождения, мероприятия и т.п. с определённой "
        f"датой, в том числе относительной (сегодня {today} — 'завтра', 'в "
        "пятницу', 'через неделю' переведи в абсолютную дату от этого дня). "
        'Каждый элемент — {"title": короткое (до 60 символов) описание '
        'события, "at": дата или дата-время в ISO 8601}. Не включай явно '
        "прошедшие, уже неактуальные даты, если заметка не исторический "
        "архив. Если дат/событий нет — пустой массив.\n\n"
        '3) "addresses": физические адреса (улица/дом, город и т.п. — не '
        "просто название города или страны само по себе, нужен адрес, по "
        'которому имеет смысл открыть карту). Каждый элемент — {"text": '
        "ДОСЛОВНО тот же фрагмент текста, СИМВОЛ В СИМВОЛ, как он "
        'записан в заметке (это критично — по нему потом ищут точное '
        'совпадение в тексте), "query": та же информация, приведённая в '
        'приличный вид одной строкой для поиска на карте}. Если в исходном '
        "тексте адрес разбит на несколько строк — text всё равно должен "
        "быть точной подстрокой заметки (со всеми переносами строк внутри "
        "как есть), а query можно склеить в одну строку. Если адресов нет "
        "— пустой массив.\n\n"
        'Пример: {"tags": ["рецепты"], "events": [{"title": "Встреча с '
        'врачом", "at": "2026-08-20T10:00:00"}], "addresses": '
        '[{"text": "ул. Ленина, 15", "query": "ул. Ленина, 15, Москва"}]}'
    )


def _parse_events(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    events: list[dict] = []
    for entry in raw[:_MAX_EVENTS]:
        if not isinstance(entry, dict):
            continue
        at_raw = entry.get("at")
        title = str(entry.get("title") or "").strip()[:60]
        if not at_raw or not title:
            continue
        try:
            at = datetime.fromisoformat(str(at_raw))
        except ValueError:
            continue
        # Как и tickets.py._add_event_notification — модель почти всегда
        # отдаёт наивную дату без пояса, трактуем как UTC (в проекте нигде
        # больше нет пользовательского часового пояса, ориентироваться
        # больше не на что).
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        events.append({"title": title, "at": at.isoformat()})
    return events


def _parse_addresses(raw: object, content: str) -> list[dict]:
    if not isinstance(raw, list):
        return []
    addresses: list[dict] = []
    for entry in raw[:_MAX_ADDRESSES]:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "")
        query = str(entry.get("query") or "").strip()[:200]
        if not text or not query:
            continue
        # "Дословно" в промпте — инструкция, не гарантия: модель иногда
        # слегка перефразирует. Точное вхождение в текст заметки —
        # обязательное условие (фронт находит и подсвечивает СТРОГО по
        # этой строке, DetectedAddressLinks.ts), иначе ссылка появится в
        # никуда не указывающем месте или не появится вовсе — отбрасываем
        # такие, а не подсвечиваем наугад.
        if text not in content:
            continue
        addresses.append({"text": text, "query": query})
    return addresses


async def _classify(
    title: str, content: str, existing_tag_names: list[str]
) -> tuple[list[str], list[dict], list[dict]]:
    settings = get_settings()
    if not settings.llm_api_key:
        return [], [], []

    client = get_llm_client()
    text = f"{title}\n\n{content}"[:_MAX_CONTENT_CHARS]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d, %A")
    response = await client.chat(
        [
            Message(role="system", content=_build_prompt(existing_tag_names, today)),
            Message(role="user", content=text),
        ],
        [],
    )
    raw = response.message.content.strip()
    # Та же привычка моделей заворачивать JSON в ```-блок, что уже ловили
    # в ai_text.py — здесь тоже не полагаемся на промпт-запрет, парсим
    # терпимо, а не падаем на первом же несовпадении.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Не удалось распарсить ответ автотегирования: %r", raw[:200])
        return [], [], []
    if not isinstance(parsed, dict):
        return [], [], []
    names = [str(n).strip() for n in parsed.get("tags") or [] if str(n).strip()][:_MAX_SUGGESTIONS]
    events = _parse_events(parsed.get("events"))
    addresses = _parse_addresses(parsed.get("addresses"), content)
    return names, events, addresses


async def _process(item_id: uuid.UUID) -> None:
    async with async_session() as db:
        item = await db.get(Item, item_id)
        if item is None or item.material_type != "note" or item.deleted_at is not None:
            return
        # Сейф — title/content зашифрованы на клиенте, бэкенд видит только
        # непрозрачный blob. Классифицировать нечего и незачем.
        from app.deps import is_vault_space

        if await is_vault_space(db, item.space_id):
            return

        existing = (await db.execute(select(Tag.name).where(Tag.user_id == item.author_id))).scalars().all()

        try:
            names, events, addresses = await _classify(item.title, item.content, list(existing))
        except Exception:
            logger.exception("Ошибка автотегирования для заметки %s", item_id)
            return

        changed = False

        # Даты/события — НЕ Notification (по решению пользователя): не
        # уходит в диспетчер/Telegram/push, только пассивно лежит на самой
        # заметке и подхватывается ActivityView (GET /api/items/detected-events).
        # Перезаписываем целиком при каждом прогоне, не копим — контент
        # заметки мог измениться, старые найденные даты могут быть уже не
        # актуальны.
        if events != item.properties.get("detected_events", []):
            item.properties = {**item.properties, "detected_events": events} if events else {
                k: v for k, v in item.properties.items() if k != "detected_events"
            }
            changed = True

        # Адреса — тоже не Notification, чисто визуальная фича: фронт
        # (extensions/DetectedAddressLinks.ts) ищет "text" дословно в
        # документе и подсвечивает ссылкой на карту, тем же decoration-
        # приёмом, что уже есть у телефонов/карт (DataRecognition.ts).
        # Свободный текст адреса — слишком гибкий формат для регулярки
        # (в отличие от строгих телефона/номера карты), поэтому здесь —
        # LLM, а не паттерн, как было решено раньше и явно пересмотрено
        # сейчас пользователем.
        if addresses != item.properties.get("detected_addresses", []):
            item.properties = {**item.properties, "detected_addresses": addresses} if addresses else {
                k: v for k, v in item.properties.items() if k != "detected_addresses"
            }
            changed = True

        if names:
            already_tagged = (
                (
                    await db.execute(
                        select(Tag.name)
                        .join(ItemTag, ItemTag.tag_id == Tag.id)
                        .where(ItemTag.item_id == item_id, ItemTag.user_id == item.author_id)
                    )
                )
                .scalars()
                .all()
            )
            already_lower = {n.lower() for n in already_tagged}

            for name in names:
                if name.lower() in already_lower:
                    continue
                existing_tag = (
                    await db.execute(select(Tag).where(Tag.user_id == item.author_id, Tag.name == name))
                ).scalar_one_or_none()
                if existing_tag is None:
                    existing_tag = Tag(user_id=item.author_id, name=name)
                    db.add(existing_tag)
                    await db.flush()
                db.add(ItemTag(item_id=item.id, tag_id=existing_tag.id, user_id=item.author_id, auto=True))
                already_lower.add(name.lower())
                changed = True

        if changed:
            await db.commit()
            await realtime.notify_space(item.space_id, "items")


async def suggest_tags_now(item_id: uuid.UUID) -> None:
    """Ручной запуск по кнопке «Предложить теги» — в обход очереди, чтобы
    пользователь увидел результат сразу, а не ждал своей позиции в фоновой
    обработке (тут это оправдано: запрос один и явно инициирован)."""
    await _process(item_id)


async def run_worker() -> None:
    while True:
        item_id = await _queue.get()
        try:
            await _process(item_id)
        except Exception:
            logger.exception("Необработанная ошибка при автотегировании %s", item_id)
        finally:
            _queue.task_done()
