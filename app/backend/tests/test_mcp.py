"""MCP-сервер: протокол, доступ и границы.

Главное, что здесь проверяется, — не «работает ли», а «не даёт ли лишнего».
MCP выносит содержимое базы наружу, к внешнему ассистенту, поэтому каждая
граница закрыта отдельным тестом: сейф, чужие записи, отозванный токен,
исключённые инструменты.
"""

from __future__ import annotations

import json
import uuid

import pytest_asyncio
from sqlalchemy import select

from app.models import Item, MCPToken, Space, SpaceMember, User
from app.routers.mcp import MCP_EXCLUDED_TOOLS
from app.security import hash_password, hash_token


async def _make_space(db, user: User, name: str, *, is_vault: bool = False) -> Space:
    space = Space(name=name, owner_id=user.id, is_vault=is_vault)
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=user.id))
    await db.flush()
    await db.commit()
    return space


async def _make_note(db, space: Space, title: str, content: str = "") -> Item:
    item = Item(
        space_id=space.id,
        author_id=space.owner_id,
        title=title,
        content=content,
        material_type="note",
        properties={},
    )
    db.add(item)
    await db.flush()
    await db.commit()
    return item


async def _issue_token(db, user: User, raw: str = "nn_testtoken") -> MCPToken:
    token = MCPToken(user_id=user.id, name="тест", token_hash=hash_token(raw))
    db.add(token)
    await db.flush()
    await db.commit()
    return token


@pytest_asyncio.fixture
async def mcp(client, db_session, test_user):
    """Клиент, ходящий в /api/mcp готовым токеном."""
    await _make_space(db_session, test_user, "Личное")
    await _issue_token(db_session, test_user)

    async def call(method: str, params: dict | None = None, *, token: str | None = "nn_testtoken", request_id=1):
        headers = {"MCP-Protocol-Version": "2025-06-18"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        body: dict = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            body["id"] = request_id
        if params is not None:
            body["params"] = params
        return await client.post("/api/mcp", json=body, headers=headers)

    return call


def _tool_result(response) -> dict:
    """Распаковывает наш dict из текстового блока MCP."""
    return json.loads(response.json()["result"]["content"][0]["text"])


class TestПротокол:
    async def test_initialize_договаривается_о_версии(self, mcp):
        r = await mcp("initialize", {"protocolVersion": "2025-06-18"})
        assert r.status_code == 200
        result = r.json()["result"]
        assert result["protocolVersion"] == "2025-06-18"
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == "notenotes"
        # Инструкция клиенту обязана предупредить про сейф: внешняя модель
        # иначе решит, что «ничего не нашлось» — это про базу целиком.
        assert "сейф" in result["instructions"].lower()

    async def test_tools_list_отдаёт_схемы(self, mcp):
        r = await mcp("tools/list")
        tools = r.json()["result"]["tools"]
        assert len(tools) > 20
        by_name = {t["name"]: t for t in tools}
        assert "search_base" in by_name
        # inputSchema — это ровно наш ToolDefinition.parameters, уже JSON
        # Schema; ради этого MCP здесь и получился переходником.
        assert by_name["search_base"]["inputSchema"]["properties"]["query"]["type"] == "string"

    async def test_неизвестный_метод(self, mcp):
        r = await mcp("tools/nonexistent")
        assert r.json()["error"]["code"] == -32601

    async def test_битый_json(self, client, db_session, test_user):
        await _make_space(db_session, test_user, "Личное")
        await _issue_token(db_session, test_user)
        r = await client.post(
            "/api/mcp",
            content=b"{not json",
            headers={"Authorization": "Bearer nn_testtoken", "Content-Type": "application/json"},
        )
        assert r.json()["error"]["code"] == -32700

    async def test_уведомление_без_id_получает_202(self, mcp):
        r = await mcp("notifications/initialized", request_id=None)
        assert r.status_code == 202
        assert not r.content

    async def test_неподдерживаемая_версия_протокола(self, client, db_session, test_user):
        await _make_space(db_session, test_user, "Личное")
        await _issue_token(db_session, test_user)
        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer nn_testtoken", "MCP-Protocol-Version": "1999-01-01"},
        )
        assert r.status_code == 400

    async def test_get_не_открывает_sse(self, client):
        # Спека разрешает 405, если сервер не шлёт ничего по своей
        # инициативе. У нас нечего слать.
        assert (await client.get("/api/mcp")).status_code == 405


class TestДоступ:
    async def test_без_токена_401_с_подсказкой_где_метаданные(self, mcp):
        r = await mcp("ping", token=None)
        assert r.status_code == 401
        # Без этого заголовка клиент не сможет начать OAuth-поток и решит,
        # что сервер просто сломан.
        assert "resource_metadata" in r.headers.get("www-authenticate", "")

    async def test_неверный_токен(self, mcp):
        assert (await mcp("ping", token="nn_wrongtoken")).status_code == 401

    async def test_отозванный_токен_не_работает(self, mcp, db_session, test_user):
        token = (await db_session.execute(select(MCPToken))).scalars().first()
        from datetime import datetime, timezone

        token.revoked_at = datetime.now(timezone.utc)
        await db_session.commit()

        assert (await mcp("ping")).status_code == 401

    async def test_использование_отмечается(self, mcp, db_session):
        await mcp("ping")
        token = (await db_session.execute(select(MCPToken))).scalars().first()
        await db_session.refresh(token)
        # Единственный способ заметить забытый или утёкший токен.
        assert token.last_used_at is not None

    async def test_чужие_записи_не_видны(self, mcp, db_session):
        other = User(username=f"other_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), name="Чужой")
        db_session.add(other)
        await db_session.flush()
        other_space = await _make_space(db_session, other, "Чужое личное")
        await _make_note(db_session, other_space, "Секрет соседа", "пароль от сейфа")

        r = await mcp("tools/call", {"name": "search_base", "arguments": {"query": "секрет соседа"}})

        titles = [item["title"] for item in _tool_result(r).get("results", [])]
        assert "Секрет соседа" not in titles


class TestГраницы:
    async def test_сейф_не_попадает_в_выдачу(self, mcp, db_session, test_user):
        """Главный инвариант всего этого файла.

        Сейф зашифрован на клиенте, бэкенд не видит его содержимого — но
        заголовки и сам факт существования записей отдавать наружу тоже
        нельзя. Исключение живёт внутри инструментов (routers/search.py,
        tools/notes.py, embeddings.py), здесь проверяется, что MCP его не
        обходит.
        """
        vault = await _make_space(db_session, test_user, "Мои Документы", is_vault=True)
        await _make_note(db_session, vault, "Паспорт", "серия и номер")

        r = await mcp("tools/call", {"name": "search_base", "arguments": {"query": "паспорт"}})

        titles = [item["title"] for item in _tool_result(r).get("results", [])]
        assert "Паспорт" not in titles

    async def test_исключённых_инструментов_нет_в_списке(self, mcp):
        names = {t["name"] for t in (await mcp("tools/list")).json()["result"]["tools"]}
        assert not (names & MCP_EXCLUDED_TOOLS)

    async def test_web_search_отказывает_и_при_прямом_вызове(self, mcp):
        """Отсутствия в списке мало.

        Модель на том конце иногда зовёт то, чего ей не объявляли — живьём
        наблюдали с run_python (см. комментарий в registry.py::dispatch).
        Здесь цена промаха прямая: квота Tavily 1000 запросов в месяц, а
        предохранителя в 5 вызовов на ход снаружи диалога нет.
        """
        r = await mcp("tools/call", {"name": "web_search", "arguments": {"query": "что угодно"}})

        assert r.json()["result"]["isError"] is True
        assert "отключён" in _tool_result(r)["error"]

    async def test_выключенное_в_настройках_выключено_и_здесь(self, mcp, db_session, test_user):
        """Одна настройка, а не две расходящиеся."""
        test_user.disabled_tools = ["create_reminder"]
        await db_session.commit()

        names = {t["name"] for t in (await mcp("tools/list")).json()["result"]["tools"]}
        assert "create_reminder" not in names


class TestЗаписьИПоиск:
    async def test_чтение_находит_заметку(self, mcp, db_session, test_user):
        space = (await db_session.execute(select(Space).where(Space.name == "Личное"))).scalar_one()
        await _make_note(db_session, space, "PZU Страховка", "полис действует до 20.12.2026")

        r = await mcp("tools/call", {"name": "search_base", "arguments": {"query": "PZU"}})

        assert any(i["title"] == "PZU Страховка" for i in _tool_result(r)["results"])

    async def test_запись_ложится_в_домашний_спейс(self, mcp, db_session, test_user):
        """Без выбора при создании токена — тот же спейс, что у Telegram-бота.

        «Домашний» = самый старый не-сейф. Заводить выбор было бы лишним
        решением на пустом месте: у пользователя может быть девять спейсов,
        и угадывать за него не нужно — механизм уже есть и обкатан.
        """
        home = (await db_session.execute(select(Space).where(Space.name == "Личное"))).scalar_one()
        # Спейс поновее и сейф — оба НЕ должны стать местом записи.
        await _make_space(db_session, test_user, "Закупки")
        await _make_space(db_session, test_user, "Secret", is_vault=True)

        r = await mcp("tools/call", {"name": "create_note", "arguments": {"title": "Из MCP", "content": "текст"}})
        assert r.json()["result"]["isError"] is False

        created = (await db_session.execute(select(Item).where(Item.title == "Из MCP"))).scalar_one()
        assert created.space_id == home.id


class TestУправлениеТокенами:
    async def test_создание_показывает_плейнтекст_один_раз(self, auth_client):
        r = await auth_client.post("/api/mcp-tokens", json={"name": "ноутбук"})
        assert r.status_code == 201
        assert r.json()["token"].startswith("nn_")

        # В списке его уже нет — только метаданные.
        listed = (await auth_client.get("/api/mcp-tokens")).json()
        assert listed[0]["name"] == "ноутбук"
        assert "token" not in listed[0]

    async def test_выданный_токен_работает(self, auth_client, client, db_session, test_user):
        await _make_space(db_session, test_user, "Личное")
        raw = (await auth_client.post("/api/mcp-tokens", json={"name": "x"})).json()["token"]

        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 200

    async def test_отзыв(self, auth_client):
        token_id = (await auth_client.post("/api/mcp-tokens", json={"name": "x"})).json()["id"]

        assert (await auth_client.delete(f"/api/mcp-tokens/{token_id}")).status_code == 204
        assert (await auth_client.get("/api/mcp-tokens")).json() == []
        # Повторный отзыв — 404, а не 500.
        assert (await auth_client.delete(f"/api/mcp-tokens/{token_id}")).status_code == 404

    async def test_чужой_токен_не_отозвать(self, auth_client, _client_factory, db_session):
        other = User(username=f"other_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), name="Чужой")
        db_session.add(other)
        await db_session.flush()
        await db_session.commit()
        token = await _issue_token(db_session, other, raw="nn_othertoken")

        # 404, а не 403: по коду ответа не должно быть видно, существует ли
        # чужой токен.
        assert (await auth_client.delete(f"/api/mcp-tokens/{token.id}")).status_code == 404

    async def test_без_авторизации_список_недоступен(self, client):
        assert (await client.get("/api/mcp-tokens")).status_code == 401


class TestПубличныйАдрес:
    async def test_www_authenticate_указывает_https_а_не_внутреннюю_схему(self, mcp, monkeypatch):
        """Поймано живьём после первого деплоя.

        Приложение стоит за Caddy и получает запрос по http внутри
        docker-сети, поэтому request.base_url давал
        «http://notenotes.metallcorn.online». Для OAuth это не косметика:
        спека требует HTTPS у всех эндпоинтов авторизации, и клиент по
        http-ссылке либо откажется, либо уйдёт по незащищённому каналу.
        """
        from app.core.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://notenotes.metallcorn.online")
        try:
            r = await mcp("ping", token=None)
            header = r.headers["www-authenticate"]
            assert "https://notenotes.metallcorn.online" in header
            assert "http://notenotes" not in header
        finally:
            get_settings.cache_clear()


class TestОграничениеЧастоты:
    async def test_перебор_токенов_режется_ДО_обращения_к_базе(self, client):
        """Порядок здесь и есть смысл проверки.

        Если лимит стоит после аутентификации, каждый запрос с мусорным
        токеном всё равно идёт в базу — и защита от перебора сама
        становится нагрузкой.
        """
        import app.rate_limit as rl
        from app.routers.mcp import ANON_MAX_PER_MINUTE

        codes = []
        for _ in range(ANON_MAX_PER_MINUTE + 2):
            r = await client.post(
                "/api/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                headers={"Authorization": "Bearer nn_perebor"},
            )
            codes.append(r.status_code)

        assert 429 in codes


class TestПередачаФайлов:
    async def test_картинка_уходит_блоком_image(self, mcp, db_session, test_user):
        """base64 в тексте модель увидит простынёй символов, а не картинкой."""
        import base64 as b64
        from pathlib import Path

        from sqlalchemy import select as sa_select

        from app.core.config import get_settings
        from app.models import Space as Sp, Upload

        space = (await db_session.execute(sa_select(Sp).where(Sp.name == "Личное"))).scalar_one()
        png = b64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        upload = Upload(space_id=space.id, author_id=test_user.id, filename="ф.png", content_type="image/png")
        db_session.add(upload)
        await db_session.flush()
        await db_session.commit()
        d = Path(get_settings().upload_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / str(upload.id)).write_bytes(png)

        r = await mcp("tools/call", {"name": "get_file", "arguments": {"file_id": str(upload.id)}})

        blocks = r.json()["result"]["content"]
        image = next(b for b in blocks if b["type"] == "image")
        assert b64.b64decode(image["data"]) == png
        assert image["mimeType"] == "image/png"

    async def test_документ_уходит_блоком_resource(self, mcp, db_session, test_user):
        """Тот самый случай: «нет инструмента для передачи вложений».

        Блок resource — протокольный способ отдать двоичный файл, чтобы
        клиент мог его сохранить.
        """
        import base64 as b64
        from pathlib import Path

        from sqlalchemy import select as sa_select

        from app.core.config import get_settings
        from app.models import Space as Sp, Upload

        space = (await db_session.execute(sa_select(Sp).where(Sp.name == "Личное"))).scalar_one()
        pdf = b"%PDF-1.4 paszport"
        upload = Upload(space_id=space.id, author_id=test_user.id,
                        filename="паспорт.pdf", content_type="application/pdf")
        db_session.add(upload)
        await db_session.flush()
        await db_session.commit()
        d = Path(get_settings().upload_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / str(upload.id)).write_bytes(pdf)

        r = await mcp("tools/call", {"name": "get_file", "arguments": {"file_id": str(upload.id)}})

        blocks = r.json()["result"]["content"]
        res = next(b for b in blocks if b["type"] == "resource")["resource"]
        assert b64.b64decode(res["blob"]) == pdf
        assert res["mimeType"] == "application/pdf"
        assert res["uri"].endswith(str(upload.id))


class TestВерсияПротокола:
    """Живой claude.ai шлёт server/discover с версией новее, чем мы знаем.

    Отвергать её по заголовку — лишний 400 на каждом подключении, который
    держится только на том, что клиент откатывается сам. Договор о версии
    — в initialize.
    """

    async def test_более_новая_версия_проходит(self, client, db_session, test_user):
        await _make_space(db_session, test_user, "Личное")
        await _issue_token(db_session, test_user)
        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer nn_testtoken", "MCP-Protocol-Version": "2026-07-28"},
        )
        assert r.status_code == 200

    async def test_initialize_с_новой_версией_договаривается_вниз(self, mcp, client, db_session):
        r = await client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2026-07-28"}},
            headers={"Authorization": "Bearer nn_testtoken", "MCP-Protocol-Version": "2026-07-28"},
        )
        assert r.status_code == 200
        # Отвечаем той, что поддерживаем, — дальше клиент обязан слать её.
        assert r.json()["result"]["protocolVersion"] == "2025-06-18"

    async def test_старше_самой_старой_и_мусор_отвергаются(self, client, db_session, test_user):
        await _make_space(db_session, test_user, "Личное")
        await _issue_token(db_session, test_user)
        for bad in ("2020-01-01", "latest", "1.0", "2026-7-28"):
            r = await client.post(
                "/api/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                headers={"Authorization": "Bearer nn_testtoken", "MCP-Protocol-Version": bad},
            )
            assert r.status_code == 400, bad

    async def test_неизвестный_метод_это_ошибка_jsonrpc_а_не_http(self, mcp):
        """server/discover мы не знаем — но это -32601 со статусом 200,
        клиент такое обрабатывает штатно. HTTP 400 он читает как «сервер
        сломан»."""
        r = await mcp("server/discover")
        assert r.status_code == 200
        assert r.json()["error"]["code"] == -32601
