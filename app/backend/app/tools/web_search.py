from __future__ import annotations

from typing import Any

import logging

import httpx

from app.core.config import get_settings
from app.llm.base import ToolDefinition
from app.tools.notes import item_url
from app.tools.registry import ToolContext

logger = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"

DEFINITION = ToolDefinition(
    name="web_search",
    description=(
        "Поиск в открытом интернете через Tavily. Используй только когда "
        "ответа точно нет в базе заметок пользователя (search_base) — "
        "вызовов на один ход диалога мало, они дороги. По умолчанию depth="
        "basic — быстрый и дешёвый, но иногда даёт только общие "
        "listicle-страницы ('топ-10 баров') без конкретики. Если результаты "
        "basic слишком общие, а вопрос требует точного/свежего факта "
        "(конкретное заведение, событие, время работы сегодня) — повтори "
        "тот же запрос с depth=advanced: он медленнее и дороже (не проси "
        "его сразу для каждого вопроса), но копает глубже и релевантнее.\n\n"
        "include_images=true — вернуть ещё и картинки по теме запроса "
        "(та же Tavily, без похода к другому провайдеру). Реальный запрос: "
        "как у гугл-ассистента — если ответ проще ПОКАЗАТЬ, чем "
        "пересказать словами (упражнение, схема, как выглядит "
        "устройство/место/растение), запроси картинки и вставь 1-2 самые "
        "релевантные через markdown ![]() в ответ. Для чисто текстовых "
        "фактов (адрес, время работы, цена) картинки не нужны — не проси "
        "их по умолчанию на каждый запрос."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Поисковый запрос"},
            "depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "description": "basic (по умолчанию) — быстро и дёшево; advanced — глубже и точнее, для повторного запроса, если basic не хватило",
            },
            "include_images": {
                "type": "boolean",
                "description": "true — вернуть подходящие по теме картинки (с описаниями), когда ответ лучше показать, а не только рассказать",
            },
        },
        "required": ["query"],
    },
)


async def handle(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.tavily_api_key:
        return {"error": "Веб-поиск не настроен"}

    query = str(args.get("query", "")).strip()
    if not query:
        return {"results": []}

    depth = str(args.get("depth", "basic")).strip().lower()
    if depth not in ("basic", "advanced"):
        depth = "basic"
    include_images = bool(args.get("include_images"))

    payload: dict[str, Any] = {
        "api_key": settings.tavily_api_key, "query": query, "max_results": 20, "search_depth": depth,
    }
    if include_images:
        payload["include_images"] = True
        payload["include_image_descriptions"] = True

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TAVILY_API_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

    result: dict[str, Any] = {
        "results": [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in data.get("results", [])
        ]
    }
    if include_images:
        # С include_image_descriptions=true Tavily отдаёт объекты
        # {url, description}; на случай расхождения версий API — если
        # вдруг придёт просто строка URL, не падаем, просто без описания.
        result["images"] = [
            {"url": img["url"], "description": img.get("description", "")} if isinstance(img, dict) else {"url": img, "description": ""}
            for img in data.get("images", []) or []
            if (isinstance(img, dict) and img.get("url")) or isinstance(img, str)
        ]

    own = await _also_in_user_base(ctx, query)
    if own:
        result["есть_в_базе_пользователя"] = own
    return result


# Сколько своих записей показывать. Три — это подсказка «посмотри сюда», а
# не выдача: полноценный поиск по базе у модели уже есть (search_base).
_OWN_HITS = 3


async def _also_in_user_base(ctx: ToolContext, query: str) -> dict[str, Any] | None:
    """Есть ли спрошенное в собственных записях человека.

    ЖИВОЙ СЛУЧАЙ 10.10, и он показательный. Утренняя сводка сообщила про
    «Marsz Kejterka в Познани» — распознано в двух его же заметках. Через
    пару часов человек спросил бота: «А что такое Кейтерка?» Ассистент
    пошёл в веб с запросом «Кейтерка что это», получил страницы про
    КЕЙТЕРИНГ и выдал лекцию про «ресторан на выезд» — при том что ответ
    (собачий марш в Познани, kejter — «пёс» на познанском) лежал в двух
    заметках, о которых ему же утром и написали.

    ПОЧЕМУ НЕ ПРАВИЛОМ В ПРОМПТЕ. Правило «сначала ищи в базе» там уже
    есть — в описании самого web_search, первой строкой. Оно не сработало,
    и это ожидаемо: промпт — самый слабый рычаг, а здесь модель вообще не
    подозревала, что слово ей знакомо. Добавлять ещё абзац значило бы
    повторять то, что уже не помогло.

    ПОЭТОМУ — ФАКТОМ В РЕЗУЛЬТАТЕ. Мы точно знаем, есть ли эти слова в
    его записях: один дешёвый полнотекстовый запрос. Если есть — кладём
    рядом с веб-выдачей, и модель видит не правило, а данные. Решение
    остаётся за ней: про погоду в базе ничего не найдётся, и поле просто
    не появится.

    Сейф исключён, потому что исключён в search_items (routers/search.py).
    """
    from app.routers.search import search_items

    try:
        items = await search_items(
            ctx.db, ctx.user_id, query, material_types=("note", "list", "ticket", "table"), limit=_OWN_HITS
        )
    except Exception:
        # Подсказка не стоит того, чтобы ронять из-за неё веб-поиск.
        logger.warning("Не удалось проверить базу пользователя по запросу веб-поиска", exc_info=True)
        return None
    if not items:
        return None
    return {
        "подсказка": (
            "Эти слова есть в собственных записях пользователя — возможно, вопрос про них, "
            "а не про общее понятие из интернета. Прочитай через get_note, прежде чем "
            "отвечать из общих знаний."
        ),
        "записи": [
            {"id": str(i.id), "title": i.title, "url": item_url(i.id), "excerpt": (i.content or "")[:200]}
            for i in items
        ],
    }
