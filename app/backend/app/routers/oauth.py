"""OAuth 2.1 для MCP — чтобы базу можно было подключить к claude.ai.

Личного токена (routers/mcp.py) хватает Claude Code: там его вписывают
заголовком. claude.ai так не умеет — кастомные коннекторы подключаются
либо без авторизации вовсе, либо по OAuth. Отсюда всё, что ниже.

Мы одновременно и resource server, и authorization server: база
пользователей одна, своя, отдельному серверу авторизации взяться неоткуда.

Что здесь СОЗНАТЕЛЬНО строго, потому что регистрация клиентов открытая
(иначе claude.ai не подключится — он узнаёт про нас в момент подключения):

  * redirect_uri сверяется побуквенно со списком, зафиксированным при
    регистрации. Без этого открытая регистрация — это открытый
    редиректор для фишинга;
  * PKCE обязателен и только S256. Код проезжает через адресную строку
    браузера и его историю;
  * код одноразовый, а повторная попытка убивает уже выданные токены:
    повтор означает, что код у кого-то ещё;
  * refresh ротируется, и повторное использование потраченного убивает
    всю цепочку — иначе вор и владелец ротировали бы по очереди, и кража
    осталась бы незамеченной;
  * aud у access-токена обязателен и проверяется при каждом запросе.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.rate_limit import client_subnet, rate_limited
from app.models import OAuthClient, OAuthCode, OAuthRefreshToken, User
from app.security import create_mcp_access_token, hash_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])

# Коду хватает минут: клиент обменивает его сразу же. Чем короче, тем
# меньше окно, в которое перехваченный код ещё чего-то стоит.
CODE_TTL_SECONDS = 300
# Access живёт час. Отзыва у него нет (в базе не хранится), поэтому
# короткий срок — единственное, что ограничивает украденный токен.
ACCESS_TTL_SECONDS = 3600
REFRESH_TTL_DAYS = 60

# Единственный поддерживаемый способ. «plain» спека 2.1 запрещает, и
# принимать его «на всякий случай» значило бы оставить обход PKCE.
CODE_CHALLENGE_METHOD = "S256"

# Потолки на ОТКРЫТУЮ регистрацию. Строки в oauth_clients заводит кто
# угодно, без всякой авторизации — иначе claude.ai не подключится. Значит
# каждое поле должно быть ограничено, иначе одна регистрация кладёт в базу
# сколько захочет, а 4 ГБ VPS этого не переживёт (CLAUDE.md).
MAX_REDIRECT_URIS = 5
MAX_REDIRECT_URI_LENGTH = 2000
# Двадцать регистраций в час с подсети. Живому клиенту хватает ОДНОЙ:
# claude.ai регистрируется один раз при подключении коннектора.
REGISTER_MAX_PER_HOUR = 20
# Обмен токенов: перебирать 256-битные значения бессмысленно, но лимит
# отсекает и шум, и попытку залить базу мусорными запросами.
TOKEN_MAX_PER_MINUTE = 60


def public_base_url() -> str:
    return get_settings().public_base_url.rstrip("/")


def canonical_mcp_uri() -> str:
    """Канонический URI ресурса — он же aud токенов (RFC 8707).

    Без хвостового слэша: спека советует именно так, а сравнение потом
    идёт строкой, поэтому расхождение здесь означало бы, что ни один
    токен не проходит проверку.
    """
    return f"{public_base_url()}/api/mcp"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- метаданные ---------------------------------------------------------
#
# Оба документа обязаны лежать в КОРНЕ, не под /api: путь диктует RFC, и
# клиент ищет их именно там. Роутер подключается в main.py до catch-all
# SPA-роута, иначе сюда приедет index.html.


def _protected_resource_metadata() -> dict:
    return {
        "resource": canonical_mcp_uri(),
        "authorization_servers": [public_base_url()],
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata() -> JSONResponse:
    return JSONResponse(_protected_resource_metadata())


@router.get("/.well-known/oauth-protected-resource/api/mcp")
async def protected_resource_metadata_with_path() -> JSONResponse:
    """Тот же документ по пути с суффиксом ресурса.

    RFC 9728 разрешает обе формы, и клиенты пробуют разные: одни берут
    адрес прямо из заголовка WWW-Authenticate, другие достраивают путь
    ресурса к well-known. Отдаём по обоим, чтобы не зависеть от того,
    какой из них выберет конкретная реализация.
    """
    return JSONResponse(_protected_resource_metadata())


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata() -> JSONResponse:
    base = public_base_url()
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/api/oauth/authorize",
        "token_endpoint": f"{base}/api/oauth/token",
        "registration_endpoint": f"{base}/api/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        # Клиент публичный, секрета у него нет — вместо секрета PKCE.
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": [CODE_CHALLENGE_METHOD],
        "scopes_supported": ["mcp"],
    })


# --- регистрация клиента (RFC 7591) -------------------------------------


class ClientRegistration(BaseModel):
    client_name: str = ""
    redirect_uris: list[str] = []


@router.post("/api/oauth/register", status_code=status.HTTP_201_CREATED)
async def register_client(
    request: Request, payload: ClientRegistration, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    if rate_limited(f"oauth-register:{client_subnet(request)}", max_requests=REGISTER_MAX_PER_HOUR, window_seconds=3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много регистраций")

    uris = [u.strip() for u in payload.redirect_uris if u.strip()]
    if not uris:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен хотя бы один redirect_uri")
    if len(uris) > MAX_REDIRECT_URIS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Не больше {MAX_REDIRECT_URIS} адресов")
    for uri in uris:
        # Спека: только HTTPS или localhost. http://куда-угодно означал бы,
        # что код авторизации уедет по незащищённому каналу.
        if not (uri.startswith("https://") or uri.startswith("http://localhost") or uri.startswith("http://127.0.0.1")):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"redirect_uri должен быть https или localhost: {uri}")
        if "#" in uri:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "redirect_uri не может содержать фрагмент")
        if len(uri) > MAX_REDIRECT_URI_LENGTH:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "redirect_uri слишком длинный")

    client = OAuthClient(client_name=payload.client_name.strip()[:255], redirect_uris=uris)
    db.add(client)
    await db.commit()
    await db.refresh(client)
    logger.info("Зарегистрирован OAuth-клиент %s (%s)", client.id, client.client_name)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "client_id": str(client.id),
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )


# --- экран согласия -----------------------------------------------------


def _redirect_with_error(redirect_uri: str, state: str, error: str, description: str) -> RedirectResponse:
    """Ошибку возвращаем КЛИЕНТУ, а не показываем в браузере.

    Так требует спека — но только после того, как redirect_uri проверен.
    Ошибки, случившиеся ДО проверки (неизвестный client_id, чужой адрес),
    никуда не редиректим: именно на этом и строится открытый редиректор.
    """
    params = {"error": error, "error_description": description}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=status.HTTP_302_FOUND)


async def _load_client(db: AsyncSession, client_id: str) -> OAuthClient:
    try:
        parsed = uuid.UUID(client_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный client_id")
    client = await db.get(OAuthClient, parsed)
    if client is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный client_id")
    return client


@router.get("/api/oauth/authorize")
async def authorize_form(
    request: Request,
    client_id: str = "",
    redirect_uri: str = "",
    response_type: str = "code",
    code_challenge: str = "",
    code_challenge_method: str = "",
    state: str = "",
    scope: str = "",
    resource: str = "",
    db: AsyncSession = Depends(get_db),
):
    client = await _load_client(db, client_id)

    # Побуквенно и до всего остального. Всё, что зависит от этой проверки,
    # должно происходить ПОСЛЕ неё.
    if redirect_uri not in (client.redirect_uris or []):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "redirect_uri не совпадает с зарегистрированным")

    if response_type != "code":
        return _redirect_with_error(redirect_uri, state, "unsupported_response_type", "Поддерживается только code")
    if not code_challenge or code_challenge_method != CODE_CHALLENGE_METHOD:
        return _redirect_with_error(
            redirect_uri, state, "invalid_request", "Обязателен PKCE с методом S256"
        )

    # Вошёл ли человек. Согласие даёт ОН, а не клиент, поэтому нужна
    # сессионная кука; нет её — на логин и обратно сюда же.
    try:
        user = await get_current_user(request, db)
    except HTTPException:
        # next целиком кодируем как ОДНО значение. Без quote всё, что после
        # первого «&», отрывалось бы от next и становилось параметрами
        # самого /login — после входа возвращаться было бы некуда, и поток
        # подключения обрывался на пустом месте. Поймано живой проверкой.
        back = f"{request.url.path}?{urlencode(dict(request.query_params))}"
        return RedirectResponse(f"/login?next={quote(back, safe='')}", status_code=status.HTTP_302_FOUND)

    return HTMLResponse(_consent_page(client, user, dict(request.query_params)))


def _consent_page(client: OAuthClient, user: User, params: dict) -> str:
    import html
    from urllib.parse import urlparse

    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in params.items()
    )
    name = html.escape(client.client_name or "Внешнее приложение")
    # Имя приходит из ОТКРЫТОЙ регистрации, то есть от кого угодно, и
    # назваться можно как угодно. Домен подделать нельзя — он проверен по
    # списку из регистрации, — поэтому показываем именно его: это
    # единственное в этом окне, чему можно верить.
    host = html.escape(urlparse(params.get("redirect_uri", "")).netloc or "неизвестно куда")
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Доступ к Notenotes</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 34rem; margin: 3rem auto; padding: 0 1.25rem;
         line-height: 1.5; color: #0f172a; background: #fff; }}
  h1 {{ font-size: 1.25rem; margin-bottom: .25rem; }}
  .who {{ color: #475569; margin-bottom: 1.5rem; }}
  ul {{ padding-left: 1.1rem; }}
  li {{ margin: .3rem 0; }}
  .warn {{ background: #fef3c7; border: 1px solid #fcd34d; border-radius: .4rem;
           padding: .6rem .8rem; margin: 1.25rem 0; font-size: .9rem; }}
  .safe {{ color: #15803d; }}
  button {{ font: inherit; padding: .55rem 1.1rem; border-radius: .4rem; cursor: pointer; }}
  .allow {{ background: #2563eb; color: #fff; border: none; }}
  .deny {{ background: #fff; border: 1px solid #cbd5e1; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0f1417; color: #e2e8f0; }}
    .who {{ color: #94a3b8; }}
    .warn {{ background: #3a2f14; border-color: #7c5e1a; }}
    .deny {{ background: #1a2024; border-color: #3a4149; color: #e2e8f0; }}
  }}
</style></head><body>
<h1>{name} просит доступ к вашим заметкам</h1>
<div class="who">Вы вошли как {html.escape(user.name or user.username)}</div>
<div class="who">Данные уйдут на <b>{host}</b></div>
<p>Приложение сможет:</p>
<ul>
  <li>искать и читать заметки, списки, документы и напоминания</li>
  <li>создавать и изменять их</li>
  <li class="safe">зашифрованный сейф останется недоступен</li>
</ul>
<div class="warn">
  Содержимое заметок будет уходить этому приложению. Разрешайте, только
  если готовы показать ему базу целиком.
</div>
<form method="post" action="/api/oauth/authorize">
  {hidden}
  <button class="allow" type="submit" name="decision" value="allow">Разрешить</button>
  <button class="deny" type="submit" name="decision" value="deny">Отказать</button>
</form>
</body></html>"""


@router.post("/api/oauth/authorize")
async def authorize_decide(
    request: Request,
    decision: str = Form(""),
    client_id: str = Form(""),
    redirect_uri: str = Form(""),
    code_challenge: str = Form(""),
    code_challenge_method: str = Form(""),
    state: str = Form(""),
    resource: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    client = await _load_client(db, client_id)
    if redirect_uri not in (client.redirect_uris or []):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "redirect_uri не совпадает с зарегистрированным")
    if not code_challenge or code_challenge_method != CODE_CHALLENGE_METHOD:
        return _redirect_with_error(redirect_uri, state, "invalid_request", "Обязателен PKCE с методом S256")

    # Решение принимает вошедший человек. Тут кука обязана быть: без неё
    # кто угодно, подсунув форму, выдал бы себе код от чужого имени.
    user = await get_current_user(request, db)

    if decision != "allow":
        return _redirect_with_error(redirect_uri, state, "access_denied", "Пользователь отказал")

    raw_code = secrets.token_urlsafe(32)
    db.add(OAuthCode(
        code_hash=hash_token(raw_code),
        client_id=client.id,
        user_id=user.id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        resource=resource or canonical_mcp_uri(),
        expires_at=_now() + timedelta(seconds=CODE_TTL_SECONDS),
    ))
    await db.commit()
    logger.info("Выдан код авторизации клиенту %s для пользователя %s", client.id, user.id)

    params = {"code": raw_code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=status.HTTP_302_FOUND)


# --- обмен на токены ----------------------------------------------------


def _token_error(error: str, description: str, code: int = status.HTTP_400_BAD_REQUEST) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": error, "error_description": description})


def _verify_pkce(verifier: str, challenge: str) -> bool:
    """Проверка PKCE, устойчивая к мусору на входе.

    verifier приходит от кого угодно и в любом виде. Первая версия делала
    verifier.encode("ascii") — и падала с 500 на любом неASCII-символе,
    то есть эндпоинт роняла одна кириллическая буква в поле. Поймано
    собственным тестом, который просто передал «не-тот-verifier».

    По спеке verifier — это 43-128 символов из unreserved-набора, так что
    неASCII здесь всегда означает неверный verifier, а не нашу проблему:
    отвечаем «не подошёл», а не пятисоткой.
    """
    try:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
    except UnicodeEncodeError:
        return False
    expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return secrets.compare_digest(expected, challenge)


async def _issue_tokens(
    db: AsyncSession, *, user_id: uuid.UUID, client_id: uuid.UUID, resource: str, family_id: uuid.UUID
) -> dict:
    access = create_mcp_access_token(user_id, str(client_id), resource, ACCESS_TTL_SECONDS)
    raw_refresh = secrets.token_urlsafe(48)
    db.add(OAuthRefreshToken(
        token_hash=hash_token(raw_refresh),
        family_id=family_id,
        client_id=client_id,
        user_id=user_id,
        resource=resource,
        expires_at=_now() + timedelta(days=REFRESH_TTL_DAYS),
    ))
    await db.commit()
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL_SECONDS,
        "refresh_token": raw_refresh,
        "scope": "mcp",
    }


@router.post("/api/oauth/token")
async def token_endpoint(
    request: Request,
    grant_type: str = Form(""),
    code: str = Form(""),
    redirect_uri: str = Form(""),
    client_id: str = Form(""),
    code_verifier: str = Form(""),
    refresh_token: str = Form(""),
    resource: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if rate_limited(f"oauth-token:{client_subnet(request)}", max_requests=TOKEN_MAX_PER_MINUTE, window_seconds=60):
        return _token_error("invalid_request", "Слишком много запросов", status.HTTP_429_TOO_MANY_REQUESTS)
    if grant_type == "authorization_code":
        return await _grant_authorization_code(db, code, redirect_uri, client_id, code_verifier)
    if grant_type == "refresh_token":
        return await _grant_refresh(db, refresh_token, client_id)
    return _token_error("unsupported_grant_type", f"grant_type {grant_type!r} не поддерживается")


async def _grant_authorization_code(
    db: AsyncSession, code: str, redirect_uri: str, client_id: str, code_verifier: str
) -> JSONResponse:
    if not code or not code_verifier:
        return _token_error("invalid_request", "Нужны code и code_verifier")

    entry = (
        await db.execute(select(OAuthCode).where(OAuthCode.code_hash == hash_token(code)))
    ).scalar_one_or_none()
    if entry is None:
        return _token_error("invalid_grant", "Код не найден или истёк")

    if entry.used_at is not None:
        # Повторное предъявление означает, что код у кого-то ещё. Убиваем
        # всё, что по нему выдано: спека прямо это предписывает.
        await db.execute(
            update(OAuthRefreshToken)
            .where(OAuthRefreshToken.user_id == entry.user_id, OAuthRefreshToken.client_id == entry.client_id)
            .values(revoked_at=_now())
        )
        await db.commit()
        logger.warning("Повторное использование кода авторизации (клиент %s) — токены отозваны", entry.client_id)
        return _token_error("invalid_grant", "Код уже использован")

    if entry.expires_at <= _now():
        return _token_error("invalid_grant", "Код истёк")
    if str(entry.client_id) != client_id:
        return _token_error("invalid_grant", "Код выдан другому клиенту")
    if entry.redirect_uri != redirect_uri:
        return _token_error("invalid_grant", "redirect_uri не совпадает с тем, для которого выдан код")
    if not _verify_pkce(code_verifier, entry.code_challenge):
        return _token_error("invalid_grant", "code_verifier не соответствует code_challenge")

    entry.used_at = _now()
    await db.commit()

    tokens = await _issue_tokens(
        db, user_id=entry.user_id, client_id=entry.client_id, resource=entry.resource, family_id=uuid.uuid4()
    )
    return JSONResponse(tokens)


async def _grant_refresh(db: AsyncSession, refresh_token: str, client_id: str) -> JSONResponse:
    if not refresh_token:
        return _token_error("invalid_request", "Нужен refresh_token")

    entry = (
        await db.execute(select(OAuthRefreshToken).where(OAuthRefreshToken.token_hash == hash_token(refresh_token)))
    ).scalar_one_or_none()
    if entry is None:
        return _token_error("invalid_grant", "Refresh-токен не найден")

    if entry.used_at is not None or entry.revoked_at is not None:
        # Потраченный или отозванный предъявлен снова — значит есть копия.
        # Убиваем ВСЮ цепочку: иначе вор и владелец ротировали бы по
        # очереди, и кража осталась бы незамеченной.
        await db.execute(
            update(OAuthRefreshToken)
            .where(OAuthRefreshToken.family_id == entry.family_id)
            .values(revoked_at=_now())
        )
        await db.commit()
        logger.warning("Повторное использование refresh-токена — цепочка %s отозвана", entry.family_id)
        return _token_error("invalid_grant", "Refresh-токен уже использован")

    if entry.expires_at <= _now():
        return _token_error("invalid_grant", "Refresh-токен истёк")
    # client_id обязателен: публичный клиент обязан себя называть, и без
    # проверки украденный refresh подошёл бы любому клиенту.
    if not client_id or str(entry.client_id) != client_id:
        return _token_error("invalid_grant", "Токен выдан другому клиенту")

    entry.used_at = _now()
    await db.commit()

    tokens = await _issue_tokens(
        db, user_id=entry.user_id, client_id=entry.client_id, resource=entry.resource, family_id=entry.family_id
    )
    return JSONResponse(tokens)


# --- управление подключениями из настроек -------------------------------
#
# Без этого подключённый claude.ai нельзя было бы отключить ВООБЩЕ: в
# настройках лежали только личные токены, а OAuth-доступ жил сам по себе
# и продлевался ротацией refresh бесконечно. Возможность отобрать доступ
# — не удобство, а условие того, что доступ вообще можно давать.


class OAuthConnectionOut(BaseModel):
    client_id: uuid.UUID
    client_name: str
    connected_at: datetime
    last_refreshed_at: datetime | None


@router.get("/api/oauth/connections", response_model=list[OAuthConnectionOut])
async def list_connections(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[OAuthConnectionOut]:
    rows = (
        await db.execute(
            select(OAuthRefreshToken, OAuthClient)
            .join(OAuthClient, OAuthClient.id == OAuthRefreshToken.client_id)
            .where(OAuthRefreshToken.user_id == user.id, OAuthRefreshToken.revoked_at.is_(None))
            .order_by(OAuthRefreshToken.created_at)
        )
    ).all()

    # Одно подключение — это цепочка ротаций, а не строка. Показывать
    # человеку двадцать одинаковых «Claude» вместо одного было бы враньём
    # о том, сколько у него подключений.
    by_client: dict[uuid.UUID, OAuthConnectionOut] = {}
    for token, client in rows:
        existing = by_client.get(client.id)
        if existing is None:
            by_client[client.id] = OAuthConnectionOut(
                client_id=client.id,
                client_name=client.client_name or "Внешнее приложение",
                connected_at=token.created_at,
                last_refreshed_at=token.created_at,
            )
        else:
            existing.connected_at = min(existing.connected_at, token.created_at)
            existing.last_refreshed_at = max(existing.last_refreshed_at or token.created_at, token.created_at)
    return list(by_client.values())


@router.delete("/api/oauth/connections/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_connection(
    client_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        update(OAuthRefreshToken)
        .where(
            OAuthRefreshToken.user_id == user.id,
            OAuthRefreshToken.client_id == client_id,
            OAuthRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    if not result.rowcount:
        # Чужое подключение неотличимо от несуществующего — иначе по коду
        # ответа можно было бы проверять чужие client_id.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подключение не найдено")
    await db.commit()
    logger.info("Отозвано OAuth-подключение %s пользователем %s", client_id, user.id)
