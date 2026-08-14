from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.base import ToolDefinition
from app.tools.registry import ToolContext

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
    return result
