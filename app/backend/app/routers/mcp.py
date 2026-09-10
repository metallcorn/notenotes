"""MCP-сервер: база Notenotes как набор инструментов для внешнего ассистента.

Зачем. Попасть в свою базу можно было только через веб и Telegram-бота.
MCP открывает её Claude Code и claude.ai — то есть можно спросить «что у
меня записано про страховку» там, где работаешь, не переключаясь.

Почему это мало кода. Слой инструментов давно вынесен и ровно той формы,
какую требует протокол: ToolDefinition уже несёт JSON Schema, dispatch —
единая точка вызова, права и исключение сейфа живут внутри каждого
инструмента. Здесь только переходник, новой логики нет.

Транспорт — Streamable HTTP БЕЗ СЕССИЙ. Спека это прямо разрешает:
на JSON-RPC запрос можно отвечать application/json вместо SSE,
Mcp-Session-Id опционален, на GET допустим 405. SSE нам не нужен —
серверных уведомлений у нас нет, отвечать нечем.

JSON-RPC разобран руками, без SDK — тем же выбором, что три LLM-клиента
(llm/mistral.py, gemini.py, groq.py). Методов ровно пять, зависимость
ради них тянуть не за что.
"""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import MCPToken, Space, SpaceMember, User
from app.security import hash_password, verify_password
from app.tools.registry import ToolContext, dispatch, get_tool_definitions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["mcp"])

# Версии протокола, которые мы понимаем. Спека требует отвечать 400 на
# неизвестную и, при отсутствии заголовка вовсе, считать 2025-03-26.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = "2025-03-26"
PREFERRED_PROTOCOL_VERSION = "2025-06-18"

TOKEN_PREFIX = "nn_"

# Инструменты, которые наружу не отдаём.
#
# web_search — не «поиска не будет», а наоборот. Искать будет тот Claude,
# с которым идёт разговор: своим поиском и не тратя наши лимиты. Отдавать
# СВОЙ нельзя — он жжёт квоту Tavily (1000 запросов в месяц), а
# предохранитель в 5 вызовов на ход живёт внутри диалогового цикла
# (routers/dialogs.py) и снаружи не действует вовсе. Исключение здесь
# ничего не отнимает, только экономит.
#
# suggest_replies — разметка UI (чипы под ответом), вне нашего чата
# бессмысленна.
#
# run_python — другая граница доверия: внешний клиент не проходил тот же
# путь согласия, что пользователь в своём чате. Обсуждать отдельно.
#
# dialog_history/get_compacted_history — привязаны к конкретному диалогу,
# которого у MCP-клиента нет.
MCP_EXCLUDED_TOOLS = frozenset({
    "web_search",
    "suggest_replies",
    "run_python",
    "get_compacted_history",
})

# Ограничение частоты — по образцу routers/debug_log.py. Счётчик модульный,
# переживает запросы в пределах процесса.
_RATE_WINDOW_SECONDS = 60
_RATE_MAX_REQUESTS = 120
_recent_requests: dict[str, list[float]] = defaultdict(list)


def _rate_limited(key: str) -> bool:
    now = time.monotonic()
    hits = _recent_requests[key]
    hits[:] = [t for t in hits if now - t < _RATE_WINDOW_SECONDS]
    hits.append(now)
    return len(hits) > _RATE_MAX_REQUESTS


# --- аутентификация -----------------------------------------------------


class MCPPrincipal:
    """Кто пришёл и в каких границах ему можно."""

    def __init__(self, user: User, space_id: uuid.UUID, disabled: set[str]) -> None:
        self.user = user
        self.space_id = space_id
        self.disabled = disabled


async def _home_space_id(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    """«Домашний» спейс — тот же, что у Telegram-бота.

    Повторяет _default_space_id из routers/dialogs.py: самый старый
    не-сейф спейс, детерминированно и стабильно между запросами.
    Дублируется намеренно — импортировать из routers/dialogs.py значило бы
    тянуть весь диалоговый модуль (и его импорт LLM-клиентов) ради одного
    запроса; расхождение здесь безопасно, потому что оба места закрыты
    тестом на одинаковый выбор.
    """
    return (
        await db.execute(
            select(Space.id)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(SpaceMember.user_id == user_id, Space.is_vault.is_(False))
            .order_by(Space.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


def _unauthorized(request: Request) -> HTTPException:
    """401 с WWW-Authenticate, как требует спека.

    Заголовок указывает клиенту, где взять метаданные ресурса, чтобы он мог
    начать OAuth-поток. Пока OAuth не сделан, значение всё равно
    осмысленно: клиент увидит, что сервер защищён, а не сломан.
    """
    base = str(request.base_url).rstrip("/")
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Нужен токен доступа",
        headers={
            "WWW-Authenticate": (
                f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource"'
            )
        },
    )


async def _authenticate(request: Request, db: AsyncSession) -> MCPPrincipal:
    header = request.headers.get("authorization") or ""
    scheme, _, raw = header.partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        raise _unauthorized(request)
    raw = raw.strip()

    # Хэш неизвестен заранее, поэтому ищем перебором активных токенов и
    # сверяем каждый — их единицы. Отозванные не проверяем вовсе.
    rows = (await db.execute(select(MCPToken).where(MCPToken.revoked_at.is_(None)))).scalars().all()
    token = next((t for t in rows if verify_password(raw, t.token_hash)), None)
    if token is None:
        raise _unauthorized(request)

    user = await db.get(User, token.user_id)
    if user is None:
        raise _unauthorized(request)

    space_id = token.space_id
    if space_id is None:
        space_id = await _home_space_id(db, user.id)
    if space_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У пользователя нет ни одного спейса")

    token.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    # Умения, выключенные пользователем в настройках, выключены и здесь:
    # одна настройка, а не две расходящиеся.
    disabled = set(MCP_EXCLUDED_TOOLS) | set(user.disabled_tools or [])
    return MCPPrincipal(user=user, space_id=space_id, disabled=disabled)


# --- протокол -----------------------------------------------------------


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_list(disabled: set[str]) -> list[dict]:
    return [
        {"name": d.name, "description": d.description, "inputSchema": d.parameters}
        for d in get_tool_definitions(disabled)
    ]


async def _call_tool(principal: MCPPrincipal, db: AsyncSession, params: dict) -> dict:
    import json

    name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}

    ctx = ToolContext(
        db=db,
        user_id=principal.user.id,
        space_id=principal.space_id,
        # Пояс внешнего клиента нам неизвестен — берём домашний, как это
        # делает Telegram-бот по той же причине (см. ToolContext).
        client_timezone=principal.user.timezone or None,
    )
    result = await dispatch(name, ctx, arguments, disabled=principal.disabled)

    # MCP отдаёт результат блоками контента. Наши инструменты возвращают
    # dict — кладём его JSON'ом в текстовый блок: модель на том конце
    # разберёт, а протокол не требует структуры.
    text = json.dumps(result, ensure_ascii=False, indent=None)
    return {
        "content": [{"type": "text", "text": text}],
        # Ошибку инструмента помечаем как ошибку ВЫЗОВА, а не протокола:
        # клиент должен показать её модели, чтобы та исправилась, а не
        # считать сервер сломанным. Это тот же приём, что внутри нашего
        # диалога — подсказка в ошибке единственное, что надёжно
        # исправляет модель.
        "isError": bool(result.get("error")),
    }


@router.post("/mcp")
async def mcp_endpoint(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    import json as _json

    # Origin проверяем до всего: спека требует этого против DNS rebinding.
    # Нам подходит любой Origin ИЛИ его отсутствие — MCP-клиенты обычно не
    # браузеры и заголовка не шлют; запрещаем только чужой сайт, который
    # пытался бы ходить сюда из браузера пользователя.
    origin = request.headers.get("origin")
    if origin and not origin.startswith(str(request.base_url).rstrip("/")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недопустимый Origin")

    version = request.headers.get("mcp-protocol-version", DEFAULT_PROTOCOL_VERSION)
    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Версия протокола {version} не поддерживается")

    principal = await _authenticate(request, db)
    if _rate_limited(str(principal.user.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много запросов")

    try:
        payload = _json.loads(await request.body())
    except ValueError:
        return Response(
            content=_json.dumps(_error(None, -32700, "Не разобрал JSON"), ensure_ascii=False),
            media_type="application/json",
        )
    if not isinstance(payload, dict):
        return Response(
            content=_json.dumps(_error(None, -32600, "Ожидался один JSON-RPC объект"), ensure_ascii=False),
            media_type="application/json",
        )

    method = str(payload.get("method") or "")
    request_id = payload.get("id")
    params = payload.get("params") or {}

    # Уведомление (нет id) — по спеке отвечаем 202 без тела.
    if request_id is None:
        logger.info("MCP уведомление %s (пользователь %s)", method, principal.user.id)
        return Response(status_code=status.HTTP_202_ACCEPTED)

    if method == "initialize":
        client_version = str(params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION)
        agreed = client_version if client_version in SUPPORTED_PROTOCOL_VERSIONS else PREFERRED_PROTOCOL_VERSION
        body = _result(request_id, {
            "protocolVersion": agreed,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "notenotes", "version": "1"},
            "instructions": (
                "База заметок, списков, документов и напоминаний пользователя. "
                "Ищи в ней перед тем, как отвечать на вопрос о его делах, "
                "документах или планах. search_base ищет и по словам, и по "
                "смыслу. Зашифрованный сейф пользователя недоступен намеренно "
                "и в выдаче не появится."
            ),
        })
    elif method == "tools/list":
        body = _result(request_id, {"tools": _tool_list(principal.disabled)})
    elif method == "tools/call":
        body = _result(request_id, await _call_tool(principal, db, params))
    elif method == "ping":
        body = _result(request_id, {})
    else:
        body = _error(request_id, -32601, f"Метод {method} не поддерживается")

    return Response(content=_json.dumps(body, ensure_ascii=False), media_type="application/json")


@router.get("/mcp")
async def mcp_no_sse() -> Response:
    """405 — спека прямо разрешает так ответить, если сервер не открывает
    SSE-поток. Нам нечего слать по своей инициативе."""
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)


# --- управление токенами из настроек ------------------------------------


class MCPTokenOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


class MCPTokenCreated(MCPTokenOut):
    # Единственный раз, когда плейнтекст покидает сервер.
    token: str


class MCPTokenCreate(BaseModel):
    name: str = ""


@router.get("/mcp-tokens", response_model=list[MCPTokenOut])
async def list_tokens(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(MCPToken)
            .where(MCPToken.user_id == user.id, MCPToken.revoked_at.is_(None))
            .order_by(MCPToken.created_at.desc())
        )
    ).scalars().all()
    return [MCPTokenOut(id=t.id, name=t.name, created_at=t.created_at, last_used_at=t.last_used_at) for t in rows]


@router.post("/mcp-tokens", response_model=MCPTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    payload: MCPTokenCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = MCPToken(user_id=user.id, name=payload.name.strip()[:255], token_hash=hash_password(raw))
    db.add(token)
    await db.commit()
    await db.refresh(token)
    logger.info("Создан MCP-токен %s для пользователя %s", token.id, user.id)
    return MCPTokenCreated(
        id=token.id, name=token.name, created_at=token.created_at, last_used_at=None, token=raw
    )


@router.delete("/mcp-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token = await db.get(MCPToken, token_id)
    # Чужой токен для нас неотличим от несуществующего — 404 в обоих
    # случаях, чтобы по коду ответа нельзя было проверять чужие id.
    if token is None or token.user_id != user.id or token.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Токен не найден")
    token.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Отозван MCP-токен %s пользователем %s", token_id, user.id)
