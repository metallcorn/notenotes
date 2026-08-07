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
        "его сразу для каждого вопроса), но копает глубже и релевантнее."
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

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TAVILY_API_URL,
            json={"api_key": settings.tavily_api_key, "query": query, "max_results": 20, "search_depth": depth},
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "results": [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in data.get("results", [])
        ]
    }
