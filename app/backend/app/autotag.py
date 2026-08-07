from __future__ import annotations

import asyncio
import json
import logging
import uuid

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


def enqueue_autotag(item_id: uuid.UUID) -> None:
    _queue.put_nowait(item_id)


def _build_prompt(existing_tag_names: list[str]) -> str:
    existing = ", ".join(existing_tag_names) if existing_tag_names else "(тегов пока нет)"
    return (
        "Предложи от 1 до 5 тегов для заметки пользователя — по смыслу содержимого, "
        "коротких (1-2 слова), на языке заметки. Уже существующие теги пользователя: "
        f"{existing}. Если подходящий тег уже есть среди существующих — используй "
        "его дословно (то же написание), не создавай почти дубликат нового слова "
        "(например, если есть тег 'покупки' — не предлагай 'покупка' или 'shopping'). "
        "Новый тег предлагай, только если среди существующих действительно ничего "
        "подходящего нет. Ответь ТОЛЬКО JSON-массивом строк, без пояснений, например: "
        '["рецепты", "ужин"]. Если заметка слишком короткая/бессодержательная для '
        "осмысленных тегов — верни пустой массив []."
    )


async def _classify(title: str, content: str, existing_tag_names: list[str]) -> list[str]:
    settings = get_settings()
    if not settings.llm_api_key:
        return []

    client = get_llm_client()
    text = f"{title}\n\n{content}"[:_MAX_CONTENT_CHARS]
    response = await client.chat(
        [
            Message(role="system", content=_build_prompt(existing_tag_names)),
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
        return []
    if not isinstance(parsed, list):
        return []
    names = [str(n).strip() for n in parsed if str(n).strip()]
    return names[:_MAX_SUGGESTIONS]


async def _process(item_id: uuid.UUID) -> None:
    async with async_session() as db:
        item = await db.get(Item, item_id)
        if item is None or item.material_type != "note" or item.deleted_at is not None:
            return

        existing = (await db.execute(select(Tag.name).where(Tag.user_id == item.author_id))).scalars().all()

        try:
            names = await _classify(item.title, item.content, list(existing))
        except Exception:
            logger.exception("Ошибка автотегирования для заметки %s", item_id)
            return

        if not names:
            return

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

        added = False
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
            added = True

        if added:
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
