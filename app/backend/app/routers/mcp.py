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
import re
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import MCPToken, OAuthRefreshToken, Space, SpaceMember, User
from app.rate_limit import client_subnet, rate_limited
from app.security import hash_token
from app.tools.registry import ToolContext, dispatch, get_tool_definitions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["mcp"])

# Версии протокола, которые мы понимаем. Спека требует отвечать 400 на
# неизвестную и, при отсутствии заголовка вовсе, считать 2025-03-26.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = "2025-03-26"
PREFERRED_PROTOCOL_VERSION = "2025-06-18"

TOKEN_PREFIX = "nn_"

_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _acceptable_protocol_version(version: str) -> bool:
    """Заголовок MCP-Protocol-Version: отвергать ли запрос по нему.

    Первая версия отвергала всё, чего нет в SUPPORTED_PROTOCOL_VERSIONS.
    Живой claude.ai шлёт server/discover с версией 2026-07-28 — новее, чем
    мы знаем, — получает 400 и откатывается на 2025-06-18. Работает, но
    это отказ на каждом подключении, и держится только на том, что клиент
    откатывается сам.

    Настоящее место для договора о версии — initialize: там клиент
    называет свою, а мы отвечаем той, что поддерживаем, и дальше он
    обязан слать её. Заголовок же до initialize — только проба. Поэтому
    отвергаем лишь то, что заведомо мусор или СТАРШЕ самого старого из
    поддерживаемых; новее — пропускаем, договоримся в initialize.
    """
    if version in SUPPORTED_PROTOCOL_VERSIONS:
        return True
    if not _VERSION_RE.match(version):
        return False
    # Даты в ISO сравниваются как строки.
    return version > min(SUPPORTED_PROTOCOL_VERSIONS)

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

# Два разных лимита, и порядок между ними важен.
#
# По ПОДСЕТИ — до аутентификации: иначе каждый запрос с мусорным токеном
# всё равно идёт в базу, и защита от перебора сама становится нагрузкой.
# Строгий, потому что легальный клиент сюда без токена не ходит вовсе.
#
# По ПОЛЬЗОВАТЕЛЮ — после: у настоящего клиента один ход это несколько
# вызовов подряд, и резать его на уровне подсети было бы неверно.
ANON_MAX_PER_MINUTE = 30
USER_MAX_PER_MINUTE = 120


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


def _public_base_url() -> str:
    """Публичный адрес, а не то, что видит приложение.

    request.base_url брать НЕЛЬЗЯ: приложение стоит за Caddy и получает
    запрос по http внутри docker-сети — в заголовке оказывался бы
    «http://notenotes.metallcorn.online», проверено живьём после первого
    деплоя. Для OAuth это не косметика: спека требует HTTPS у всех
    эндпоинтов авторизации, и клиент по http-ссылке либо откажется, либо
    уйдёт по незащищённому каналу.

    settings.public_base_url для этого в проекте и заведён — им же
    Telegram-бот строит ссылки на заметки.
    """
    return get_settings().public_base_url.rstrip("/")


def _unauthorized(request: Request) -> HTTPException:
    """401 с WWW-Authenticate, как требует спека.

    Заголовок указывает клиенту, где взять метаданные ресурса, чтобы он мог
    начать OAuth-поток. Пока OAuth не сделан, значение всё равно
    осмысленно: клиент увидит, что сервер защищён, а не сломан.
    """
    base = _public_base_url()
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

    # Два способа войти, оба живут здесь рядом.
    #
    # Личный токен «nn_...» — для Claude Code, где его вписывают
    # заголовком руками. OAuth-токен — для claude.ai, который простой
    # токен вписать не даёт и требует полноценный поток (routers/oauth.py).
    #
    # Разбирать их по префиксу нельзя: подделать префикс ничего не стоит.
    # Поэтому проверяем оба пути честно, а решает подпись/хэш.
    token: MCPToken | None = None
    user: User | None = None
    space_id: uuid.UUID | None = None

    if raw.startswith(TOKEN_PREFIX):
        # sha256 детерминирован, поэтому один индексированный запрос
        # вместо перебора всех строк (см. security.hash_token — почему не
        # bcrypt).
        #
        # Отозванные тоже ищем, а НЕ отсекаем условием в запросе. Раньше
        # отсекали — и использование отозванного токена было неотличимо от
        # случайного мусора. А это разные вещи: отозванный токен не может
        # «случайно» оказаться у клиента, значит копию сохранили и пробуют.
        # Единственный шанс это заметить.
        found = (
            await db.execute(select(MCPToken).where(MCPToken.token_hash == hash_token(raw)))
        ).scalar_one_or_none()
        if found is not None and found.revoked_at is not None:
            await audit.alert(
                db,
                event=audit.MCP_TOKEN_REVOKED_USED,
                user_id=found.user_id,
                subject=found.name or str(found.id),
                source=client_subnet(request),
            )
            await db.commit()
            raise _unauthorized(request)
        token = found
        if token is not None:
            user = await db.get(User, token.user_id)
            space_id = token.space_id
    else:
        # aud обязателен и сверяется с каноническим URI: спека требует
        # принимать только токены, выписанные ИМЕННО ДЛЯ НАС. Заодно это
        # отсекает сессионную куку — у неё aud нет вовсе.
        from app.routers.oauth import canonical_mcp_uri
        from app.security import decode_mcp_access_token, mcp_access_token_client

        user_id = decode_mcp_access_token(raw, canonical_mcp_uri())
        if user_id is not None:
            # Отзыв подключения обязан действовать СРАЗУ. Сам access-токен
            # отозвать нельзя — он не хранится, подпись самодостаточна, и
            # без этой проверки отключённый claude.ai продолжал бы читать
            # заметки ещё час. Для кнопки «отключить» это негодно.
            #
            # Поэтому смотрим, жива ли цепочка refresh у этого клиента:
            # отзыв гасит её всю, и токен мгновенно перестаёт работать.
            client_id = mcp_access_token_client(raw, canonical_mcp_uri())
            alive = (
                await db.execute(
                    select(OAuthRefreshToken.id).where(
                        OAuthRefreshToken.user_id == user_id,
                        OAuthRefreshToken.client_id == client_id,
                        OAuthRefreshToken.revoked_at.is_(None),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if alive is not None:
                user = await db.get(User, user_id)

    if user is None:
        # Единственный след перебора токенов. Пишется с потолком (см.
        # app/audit.py), иначе сам перебор раздувал бы базу.
        await audit.record(
            db,
            event=audit.MCP_AUTH_FAILED,
            source=client_subnet(request),
            details={"scheme": "personal" if raw.startswith(TOKEN_PREFIX) else "oauth"},
            # Следом полетит 401, обычного коммита не будет — а сохранить
            # надо ИМЕННО этот случай.
            commit=True,
        )
        raise _unauthorized(request)

    if space_id is None:
        space_id = await _home_space_id(db, user.id)
    if space_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У пользователя нет ни одного спейса")

    if token is not None:
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
    # След в логах — обязателен именно здесь. Через MCP базой пользуется
    # не человек, а внешняя модель, и по last_used_at видно только «кто-то
    # ходил», а не ЧТО он делал. Аргументы не пишем: там содержимое
    # заметок, и логи стали бы вторым местом, где лежат личные данные.
    logger.info("MCP: %s (пользователь %s)", name, principal.user.id)
    await audit.record(db, event=audit.MCP_TOOL, user_id=principal.user.id, subject=name)
    result = await dispatch(name, ctx, arguments, disabled=principal.disabled)

    # MCP отдаёт результат блоками контента. Наши инструменты возвращают
    # dict — кладём его JSON'ом в текстовый блок: модель на том конце
    # разберёт, а протокол не требует структуры.
    #
    # Исключение — картинка. Класть её base64 в текст бессмысленно: модель
    # увидит простыню символов вместо изображения. Протокол для этого и
    # держит отдельный тип блока, а инструмент помечает такой результат
    # ключом _mcp_image (см. tools/files.py).
    image = result.pop("_mcp_image", None)
    resource = result.pop("_mcp_resource", None)
    content: list[dict] = [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=None)}]
    if isinstance(image, dict) and image.get("data"):
        content.append({
            "type": "image",
            "data": image["data"],
            "mimeType": image.get("mime_type") or "application/octet-stream",
        })
    if isinstance(resource, dict) and resource.get("data"):
        # Блок resource — протокольный способ передать двоичный файл:
        # клиент может сохранить его или предложить человеку скачать, а
        # модель не пытается «прочитать» байты как текст.
        content.append({
            "type": "resource",
            "resource": {
                "uri": resource.get("uri") or f"file:///{resource.get('filename', 'file')}",
                "mimeType": resource.get("mime_type") or "application/octet-stream",
                "blob": resource["data"],
            },
        })
    return {
        "content": content,
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
    if origin and origin.rstrip("/") != _public_base_url():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недопустимый Origin")

    version = request.headers.get("mcp-protocol-version", DEFAULT_PROTOCOL_VERSION)
    if not _acceptable_protocol_version(version):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Версия протокола {version} не поддерживается")

    # ДО аутентификации: иначе перебор токенов бесплатно нагружает базу.
    if rate_limited(f"mcp-anon:{client_subnet(request)}", max_requests=ANON_MAX_PER_MINUTE, window_seconds=60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много запросов")

    principal = await _authenticate(request, db)

    if rate_limited(f"mcp-user:{principal.user.id}", max_requests=USER_MAX_PER_MINUTE, window_seconds=60):
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
        # Коммит здесь, а не только внутри инструментов: пишущие коммитят
        # сами, а get_file/list_files/search_base — нет, и строка аудита,
        # добавленная в ту же сессию, терялась вместе с ней. Поймано 12.09:
        # восемь живых get_file — и ни одной записи в audit_log.
        await db.commit()
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
    token = MCPToken(user_id=user.id, name=payload.name.strip()[:255], token_hash=hash_token(raw))
    db.add(token)
    await db.commit()
    await db.refresh(token)
    logger.info("Создан MCP-токен %s для пользователя %s", token.id, user.id)
    await audit.record(db, event=audit.MCP_TOKEN_CREATED, user_id=user.id, subject=str(token.id),
                       details={"name": token.name})
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
    await audit.record(db, event=audit.MCP_TOKEN_REVOKED, user_id=user.id, subject=str(token_id),
                       details={"name": token.name})


# --- аудит: показать человеку, что делали с его базой --------------------


class AuditEntryOut(BaseModel):
    event: str
    subject: str
    created_at: datetime


@router.get("/mcp-audit", response_model=list[AuditEntryOut])
async def read_audit(
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AuditEntryOut]:
    """Последние события ПО СВОЕЙ базе.

    Только свои: user_id в запросе жёстко, без параметра. Чужой аудит —
    это карта того, чем человек пользуется и когда, и отдавать её нельзя
    даже «на посмотреть».

    Неудачные попытки входа сюда не попадают: у них нет user_id (токен-то
    не подошёл), и приписывать их кому-то было бы враньём. Они лежат в
    таблице и видны в логах — на случай, когда придётся разбираться.
    """
    from app.models import AuditLog

    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user.id)
            .order_by(AuditLog.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).scalars().all()
    return [AuditEntryOut(event=r.event, subject=r.subject, created_at=r.created_at) for r in rows]
