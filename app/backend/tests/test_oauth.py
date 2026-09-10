"""OAuth 2.1 для MCP — прежде всего границы безопасности.

Регистрация клиентов здесь ОТКРЫТАЯ: claude.ai узнаёт про нас в момент
подключения, заранее завести его в админке невозможно. Всё, что ниже,
существует потому, что открытая регистрация без этих проверок превращает
сервер в открытый редиректор и раздатчик чужих токенов.

Каждый тест назван тем, что сломается, если проверку убрать.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import select

from app.models import OAuthClient, OAuthCode, OAuthRefreshToken, Space, SpaceMember, User
from app.security import create_session_token, hash_password, hash_token

VERIFIER = "verifier-" + "x" * 50
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


@pytest_asyncio.fixture
async def oauth(client, auth_client, db_session, test_user):
    """Зарегистрированный клиент плюс помощники на весь поток."""
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()

    reg = await client.post(
        "/api/oauth/register",
        json={"client_name": "Claude", "redirect_uris": [REDIRECT]},
    )
    client_id = reg.json()["client_id"]

    async def authorize(**overrides):
        params = {
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "state": "xyz",
            **overrides,
        }
        return await auth_client.get("/api/oauth/authorize", params=params)

    async def approve(**overrides):
        form = {
            "decision": "allow",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "state": "xyz",
            **overrides,
        }
        return await auth_client.post("/api/oauth/authorize", data=form)

    async def exchange(code: str, **overrides):
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": VERIFIER,
            **overrides,
        }
        return await client.post("/api/oauth/token", data=form)

    async def full_flow() -> dict:
        r = await approve()
        code = r.headers["location"].split("code=")[1].split("&")[0]
        return (await exchange(code)).json()

    return {
        "client_id": client_id,
        "authorize": authorize,
        "approve": approve,
        "exchange": exchange,
        "full_flow": full_flow,
        "space": space,
    }


class TestМетаданные:
    async def test_метаданные_ресурса_лежат_в_корне(self, client):
        # Путь диктует RFC 9728, клиент ищет строго там. Под /api его никто
        # не найдёт.
        r = await client.get("/.well-known/oauth-protected-resource")
        assert r.status_code == 200
        assert r.json()["resource"].endswith("/api/mcp")
        assert r.json()["authorization_servers"]

    async def test_метаданные_и_по_пути_с_суффиксом(self, client):
        # Клиенты пробуют обе формы: одни берут адрес из WWW-Authenticate,
        # другие достраивают путь ресурса. Отдаём по обоим.
        r = await client.get("/.well-known/oauth-protected-resource/api/mcp")
        assert r.status_code == 200

    async def test_метаданные_сервера_авторизации(self, client):
        meta = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert meta["authorization_endpoint"].endswith("/api/oauth/authorize")
        assert meta["token_endpoint"].endswith("/api/oauth/token")
        assert meta["registration_endpoint"].endswith("/api/oauth/register")
        # Только S256. Объявить «plain» значило бы разрешить обход PKCE.
        assert meta["code_challenge_methods_supported"] == ["S256"]

    async def test_метаданные_не_перехвачены_spa_роутом(self, client):
        # Catch-all отдаёт index.html на что угодно — эти пути обязаны
        # обрабатываться раньше.
        r = await client.get("/.well-known/oauth-authorization-server")
        assert "text/html" not in r.headers.get("content-type", "")


class TestРегистрация:
    async def test_регистрация_возвращает_client_id(self, client):
        r = await client.post("/api/oauth/register", json={"client_name": "X", "redirect_uris": [REDIRECT]})
        assert r.status_code == 201
        assert uuid.UUID(r.json()["client_id"])
        # Секрета нет: клиент публичный, спрятать секрет ему негде —
        # вместо секрета работает PKCE.
        assert "client_secret" not in r.json()

    async def test_без_redirect_uri_отказ(self, client):
        assert (await client.post("/api/oauth/register", json={"redirect_uris": []})).status_code == 400

    async def test_http_адрес_не_принимается(self, client):
        """Код авторизации не должен уезжать по незащищённому каналу."""
        r = await client.post("/api/oauth/register", json={"redirect_uris": ["http://evil.example/cb"]})
        assert r.status_code == 400

    async def test_localhost_разрешён(self, client):
        # Десктопные клиенты слушают локальный порт — это исключение из
        # правила выше, и спека его прямо допускает.
        r = await client.post("/api/oauth/register", json={"redirect_uris": ["http://localhost:5599/cb"]})
        assert r.status_code == 201

    async def test_фрагмент_в_адресе_запрещён(self, client):
        r = await client.post("/api/oauth/register", json={"redirect_uris": ["https://ok.example/cb#frag"]})
        assert r.status_code == 400


class TestОткрытыйРедиректор:
    """Главная опасность открытой регистрации."""

    async def test_чужой_redirect_uri_не_принимается(self, oauth):
        r = await oauth["authorize"](redirect_uri="https://evil.example/steal")
        # 400 в браузере, а НЕ редирект: редиректить на непроверенный адрес
        # и есть та самая дыра.
        assert r.status_code == 400

    async def test_почти_совпадающий_адрес_тоже_не_принимается(self, oauth):
        """Сверка побуквенная, без «префикс подошёл — и ладно»."""
        for near in (REDIRECT + "/..", REDIRECT + "?x=1", REDIRECT.replace("claude.ai", "claude.ai.evil.com")):
            assert (await oauth["authorize"](redirect_uri=near)).status_code == 400

    async def test_неизвестный_client_id(self, oauth):
        r = await oauth["authorize"](client_id=str(uuid.uuid4()))
        assert r.status_code == 400

    async def test_выдача_кода_тоже_сверяет_адрес(self, oauth):
        """Проверка на GET бесполезна, если POST её не повторяет."""
        r = await oauth["approve"](redirect_uri="https://evil.example/steal")
        assert r.status_code == 400


class TestPKCE:
    async def test_без_pkce_не_пускает(self, oauth):
        r = await oauth["authorize"](code_challenge="", code_challenge_method="")
        assert r.status_code in (302, 400)
        if r.status_code == 302:
            assert "error=invalid_request" in r.headers["location"]

    async def test_plain_не_принимается(self, oauth):
        """Спека 2.1 его запрещает; принять «на всякий случай» значило бы
        оставить обход PKCE целиком."""
        r = await oauth["authorize"](code_challenge_method="plain")
        assert r.status_code in (302, 400)

    async def test_неверный_verifier_не_меняется_на_токен(self, oauth):
        r = await oauth["approve"]()
        code = r.headers["location"].split("code=")[1].split("&")[0]

        bad = await oauth["exchange"](code, code_verifier="не-тот-verifier-" + "y" * 40)

        assert bad.status_code == 400
        assert bad.json()["error"] == "invalid_grant"

    async def test_правильный_verifier_работает(self, oauth):
        tokens = await oauth["full_flow"]()
        assert tokens["token_type"] == "Bearer"
        assert tokens["access_token"]
        assert tokens["refresh_token"]


class TestКодАвторизации:
    async def test_state_возвращается_клиенту(self, oauth):
        """Без него клиент не отличит свой ответ от подкинутого."""
        r = await oauth["approve"]()
        assert "state=xyz" in r.headers["location"]

    async def test_отказ_пользователя_доезжает_ошибкой(self, oauth):
        r = await oauth["approve"](decision="deny")
        assert "error=access_denied" in r.headers["location"]
        assert "code=" not in r.headers["location"]

    async def test_код_одноразовый(self, oauth):
        r = await oauth["approve"]()
        code = r.headers["location"].split("code=")[1].split("&")[0]

        assert (await oauth["exchange"](code)).status_code == 200
        assert (await oauth["exchange"](code)).status_code == 400

    async def test_повторный_код_отзывает_уже_выданное(self, oauth, db_session):
        """Повтор означает, что код у кого-то ещё — значит выданное по нему
        доверять больше нельзя. Спека прямо это предписывает."""
        r = await oauth["approve"]()
        code = r.headers["location"].split("code=")[1].split("&")[0]
        await oauth["exchange"](code)

        await oauth["exchange"](code)  # повтор

        tokens = (await db_session.execute(select(OAuthRefreshToken))).scalars().all()
        assert tokens and all(t.revoked_at is not None for t in tokens)

    async def test_код_другого_клиента_не_обменять(self, oauth, client):
        other = await client.post(
            "/api/oauth/register", json={"client_name": "Другой", "redirect_uris": [REDIRECT]}
        )
        r = await oauth["approve"]()
        code = r.headers["location"].split("code=")[1].split("&")[0]

        bad = await oauth["exchange"](code, client_id=other.json()["client_id"])

        assert bad.status_code == 400

    async def test_подменённый_redirect_uri_при_обмене(self, oauth, client):
        await client.post("/api/oauth/register", json={"redirect_uris": ["https://other.example/cb"]})
        r = await oauth["approve"]()
        code = r.headers["location"].split("code=")[1].split("&")[0]

        bad = await oauth["exchange"](code, redirect_uri="https://other.example/cb")

        assert bad.status_code == 400

    async def test_истёкший_код(self, oauth, db_session):
        r = await oauth["approve"]()
        code = r.headers["location"].split("code=")[1].split("&")[0]
        entry = (await db_session.execute(select(OAuthCode))).scalars().first()
        entry.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db_session.commit()

        assert (await oauth["exchange"](code)).status_code == 400

    async def test_код_хранится_хэшем(self, oauth, db_session):
        r = await oauth["approve"]()
        code = r.headers["location"].split("code=")[1].split("&")[0]

        entry = (await db_session.execute(select(OAuthCode))).scalars().first()
        assert entry.code_hash != code
        assert entry.code_hash == hash_token(code)


class TestСогласие:
    async def test_без_входа_ведёт_на_логин(self, client, oauth):
        """Согласие даёт человек. Без куки — на логин и обратно сюда же."""
        r = await client.get(
            "/api/oauth/authorize",
            params={
                "client_id": oauth["client_id"],
                "redirect_uri": REDIRECT,
                "response_type": "code",
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
            },
        )
        assert r.status_code == 302
        assert r.headers["location"].startswith("/login?next=")

    async def test_экран_говорит_что_именно_разрешают(self, oauth):
        page = (await oauth["authorize"]()).text
        assert "Claude" in page
        # Человек должен прочитать это ДО нажатия, а не узнать потом.
        assert "уходить" in page or "уходит" in page
        assert "сейф" in page.lower()

    async def test_имя_клиента_экранируется(self, client, auth_client):
        """Имя приходит из ОТКРЫТОЙ регистрации, то есть от кого угодно."""
        reg = await client.post(
            "/api/oauth/register",
            json={"client_name": "<script>alert(1)</script>", "redirect_uris": [REDIRECT]},
        )
        page = (await auth_client.get("/api/oauth/authorize", params={
            "client_id": reg.json()["client_id"],
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
        })).text

        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page

    async def test_выдать_код_без_куки_нельзя(self, client, oauth):
        """Иначе кто угодно, подсунув форму, получил бы код от чужого имени."""
        r = await client.post("/api/oauth/authorize", data={
            "decision": "allow",
            "client_id": oauth["client_id"],
            "redirect_uri": REDIRECT,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
        })
        assert r.status_code == 401


class TestРотацияRefresh:
    async def test_refresh_меняется_при_обмене(self, oauth, client):
        first = await oauth["full_flow"]()

        r = await client.post("/api/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": oauth["client_id"],
        })

        assert r.status_code == 200
        # Спека требует ротации для публичных клиентов.
        assert r.json()["refresh_token"] != first["refresh_token"]

    async def test_потраченный_refresh_убивает_всю_цепочку(self, oauth, client, db_session):
        """Иначе вор и владелец ротировали бы по очереди, и кража осталась
        бы незамеченной."""
        first = await oauth["full_flow"]()
        second = (await client.post("/api/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": oauth["client_id"],
        })).json()

        # Предъявляем СТАРЫЙ — как сделал бы укравший.
        replay = await client.post("/api/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": oauth["client_id"],
        })
        assert replay.status_code == 400

        # И теперь свежий тоже мёртв — вся семья отозвана.
        after = await client.post("/api/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": second["refresh_token"],
            "client_id": oauth["client_id"],
        })
        assert after.status_code == 400

    async def test_чужой_refresh_не_подходит(self, oauth, client):
        assert (await client.post("/api/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": "выдуманный",
            "client_id": oauth["client_id"],
        })).status_code == 400

    async def test_неизвестный_grant_type(self, client):
        r = await client.post("/api/oauth/token", data={"grant_type": "password"})
        assert r.json()["error"] == "unsupported_grant_type"


class TestТокеныНеПутаются:
    """Самая тихая из возможных дыр.

    Сессионная кука и OAuth-токен подписываются ОДНИМ ключом и одним
    алгоритмом. Пока их не различали явно, каждый годился вместо другого:
    токен, выданный claude.ai, работал бы как кука — с полным доступом ко
    всему API, включая эндпоинты сейфа, которых у MCP нет.
    """

    async def test_oauth_токен_не_работает_как_сессионная_кука(self, oauth, client):
        tokens = await oauth["full_flow"]()

        client.cookies.set("notenotes_session", tokens["access_token"])
        r = await client.get("/api/auth/me")

        assert r.status_code == 401

    async def test_сессионная_кука_не_работает_как_mcp_токен(self, client, test_user, db_session):
        space = Space(name="Личное", owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
        await db_session.commit()

        session = create_session_token(test_user.id)
        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {session}"},
        )

        assert r.status_code == 401

    async def test_разделение_держится_на_aud(self, test_user):
        """Проверяет МЕХАНИЗМ, а не только исход.

        Оба теста выше проходят и без поля typ — держит aud, и это важно
        знать: убрать aud, понадеявшись на typ, значит сломать границу,
        оставив тесты зелёными. Здесь зафиксировано, что именно работает.
        """
        from app.routers.oauth import canonical_mcp_uri
        from app.security import (
            create_mcp_access_token,
            create_session_token,
            decode_mcp_access_token,
            decode_session_token,
        )

        mcp_token = create_mcp_access_token(test_user.id, "c", canonical_mcp_uri(), 3600)
        session = create_session_token(test_user.id)

        # У MCP-токена aud есть — как кука он не читается.
        assert decode_session_token(mcp_token) is None
        # У куки aud нет — как MCP-токен она не читается.
        assert decode_mcp_access_token(session, canonical_mcp_uri()) is None
        # И каждый работает по своему назначению.
        assert decode_session_token(session) == test_user.id
        assert decode_mcp_access_token(mcp_token, canonical_mcp_uri()) == test_user.id

    async def test_старые_куки_без_поля_typ_продолжают_работать(self, client, test_user):
        """Поле добавлено задним числом — выкидывать всех было бы незачем."""
        import jwt

        from app.core.config import get_settings

        legacy = jwt.encode(
            {"sub": str(test_user.id), "exp": datetime.now(timezone.utc) + timedelta(days=1)},
            get_settings().secret_key,
            algorithm="HS256",
        )
        client.cookies.set("notenotes_session", legacy)

        assert (await client.get("/api/auth/me")).status_code == 200


class TestДоступПоOAuth:
    async def test_токен_открывает_mcp(self, oauth, client):
        tokens = await oauth["full_flow"]()

        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )

        assert r.status_code == 200
        assert len(r.json()["result"]["tools"]) > 20

    async def test_токен_для_чужого_ресурса_отвергается(self, client, test_user, db_session):
        """Спека: принимать только то, что выписано ИМЕННО ДЛЯ НАС.

        Иначе токен, полученный клиентом для другого сервиса, открывал бы
        нашу базу.
        """
        from app.security import create_mcp_access_token

        space = Space(name="Личное", owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
        await db_session.commit()

        foreign = create_mcp_access_token(test_user.id, "client", "https://другой.сервис/mcp", 3600)

        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {foreign}"},
        )
        assert r.status_code == 401

    async def test_истёкший_токен_отвергается(self, client, test_user, db_session):
        from app.routers.oauth import canonical_mcp_uri
        from app.security import create_mcp_access_token

        space = Space(name="Личное", owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
        await db_session.commit()

        expired = create_mcp_access_token(test_user.id, "client", canonical_mcp_uri(), -10)

        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert r.status_code == 401

    async def test_подделанная_подпись_отвергается(self, oauth, client):
        tokens = await oauth["full_flow"]()
        head, payload, _sig = tokens["access_token"].split(".")
        forged = f"{head}.{payload}.{'A' * 43}"

        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert r.status_code == 401

    async def test_токен_видит_только_свои_записи(self, oauth, client, db_session):
        from app.models import Item

        other = User(username=f"o_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), name="Чужой")
        db_session.add(other)
        await db_session.flush()
        other_space = Space(name="Чужое", owner_id=other.id)
        db_session.add(other_space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=other_space.id, user_id=other.id))
        db_session.add(Item(
            space_id=other_space.id, author_id=other.id, title="Секрет соседа",
            content="пароль", material_type="note", properties={},
        ))
        await db_session.commit()

        tokens = await oauth["full_flow"]()
        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "search_base", "arguments": {"query": "секрет соседа"}}},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )

        import json as _json

        found = _json.loads(r.json()["result"]["content"][0]["text"])
        assert all(i["title"] != "Секрет соседа" for i in found.get("results", []))


class TestХранение:
    async def test_refresh_хранится_хэшем(self, oauth, db_session):
        tokens = await oauth["full_flow"]()

        row = (await db_session.execute(select(OAuthRefreshToken))).scalars().first()
        assert row.token_hash != tokens["refresh_token"]
        assert row.token_hash == hash_token(tokens["refresh_token"])

    async def test_access_токен_в_базе_не_лежит(self, oauth, db_session):
        """Намеренно: подпись самодостаточна, а короткий срок жизни
        заменяет отзыв. Отзывается refresh — он и в таблице."""
        await oauth["full_flow"]()
        clients = (await db_session.execute(select(OAuthClient))).scalars().all()
        assert clients  # клиент есть
        # А таблицы под access-токены нет вовсе — проверяем, что мы её не
        # завели по инерции.
        from app import models

        assert not hasattr(models, "OAuthAccessToken")
