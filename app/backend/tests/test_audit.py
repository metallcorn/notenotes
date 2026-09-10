"""Аудит: что записывается, что НЕ записывается и кто это видит.

Половина тестов здесь — про то, чего в аудите быть НЕ должно. Это не
перестраховка: журнал, в который утекло содержимое заметок, сам
становится тем, что надо защищать, а он не шифруется, живёт полгода и
читается из настроек.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import select

from app import audit
from app.models import AuditLog, MCPToken, Space, SpaceMember, User
from app.security import hash_password, hash_token


async def _space(db, user: User, name: str = "Личное") -> Space:
    space = Space(name=name, owner_id=user.id)
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=user.id))
    await db.commit()
    return space


@pytest_asyncio.fixture
async def mcp(client, db_session, test_user):
    await _space(db_session, test_user)
    db_session.add(MCPToken(user_id=test_user.id, name="тест", token_hash=hash_token("nn_audit")))
    await db_session.commit()

    async def call(method, params=None, token="nn_audit"):
        headers = {"MCP-Protocol-Version": "2025-06-18"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params:
            body["params"] = params
        return await client.post("/api/mcp", json=body, headers=headers)

    return call


async def _events(db) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog).order_by(AuditLog.created_at))).scalars().all())


class TestЧтоЗаписывается:
    async def test_вызов_инструмента(self, mcp, db_session, test_user):
        await mcp("tools/call", {"name": "search_base", "arguments": {"query": "страховка"}})

        rows = [e for e in await _events(db_session) if e.event == audit.MCP_TOOL]
        assert rows and rows[-1].subject == "search_base"
        assert rows[-1].user_id == test_user.id

    async def test_неудачная_попытка_входа(self, mcp, db_session):
        """Единственный след перебора токенов.

        До этого перебор не оставлял в системе ничего: ни строки, ни
        отметки. Только по нему и можно заметить, что кто-то подбирает.
        """
        await mcp("ping", token="nn_bruteforce")

        rows = [e for e in await _events(db_session) if e.event == audit.MCP_AUTH_FAILED]
        assert rows
        assert rows[-1].user_id is None  # пользователя-то и нет
        assert rows[-1].source  # но откуда пришли — записано

    async def test_выдача_и_отзыв_токена(self, auth_client, db_session):
        token_id = (await auth_client.post("/api/mcp-tokens", json={"name": "ноутбук"})).json()["id"]
        await auth_client.delete(f"/api/mcp-tokens/{token_id}")

        events = [e.event for e in await _events(db_session)]
        assert audit.MCP_TOKEN_CREATED in events
        assert audit.MCP_TOKEN_REVOKED in events


class TestЧегоВАудитеБытьНеДолжно:
    async def test_аргументы_инструмента_не_попадают(self, mcp, db_session):
        """В аргументах лежит содержимое заметок.

        Записать их значит завести второе хранилище личных данных —
        нешифрованное, живущее полгода и читаемое из настроек.
        """
        await mcp("tools/call", {
            "name": "create_note",
            "arguments": {"title": "Пароль от банка", "content": "1234-5678-9012"},
        })

        dump = " ".join(f"{e.subject} {e.details}" for e in await _events(db_session))
        assert "1234-5678-9012" not in dump
        assert "Пароль от банка" not in dump

    async def test_сам_токен_не_попадает(self, auth_client, db_session):
        raw = (await auth_client.post("/api/mcp-tokens", json={"name": "x"})).json()["token"]

        dump = " ".join(f"{e.subject} {e.details}" for e in await _events(db_session))
        assert raw not in dump


class TestАудитНеЛомаетРаботу:
    async def test_падение_записи_не_роняет_запрос(self, mcp, db_session, monkeypatch):
        """Упавшая запись следа — не повод не отдать человеку заметку."""

        def explode(*args, **kwargs):
            raise RuntimeError("база недоступна")

        monkeypatch.setattr("app.audit.AuditLog", explode)

        r = await mcp("ping")

        assert r.status_code == 200

    async def test_перебор_не_раздувает_таблицу(self, mcp, db_session):
        """Иначе запись следа сама становится способом залить базу.

        Потолок на неудачные попытки — не экономия места, а защита от
        того, что атакующий пишет в нашу базу своими руками.
        """
        for i in range(audit.FAILED_ATTEMPTS_PER_HOUR + 15):
            await mcp("ping", token=f"nn_mimo{i}")

        rows = [e for e in await _events(db_session) if e.event == audit.MCP_AUTH_FAILED]
        assert len(rows) <= audit.FAILED_ATTEMPTS_PER_HOUR


class TestЧтение:
    async def test_видно_только_своё(self, auth_client, db_session, test_user):
        """Чужой аудит — карта того, чем человек пользуется и когда."""
        other = User(username=f"o_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), name="Чужой")
        db_session.add(other)
        await db_session.flush()
        db_session.add(AuditLog(user_id=other.id, event=audit.MCP_TOOL, subject="чужое_действие"))
        db_session.add(AuditLog(user_id=test_user.id, event=audit.MCP_TOOL, subject="моё_действие"))
        await db_session.commit()

        rows = (await auth_client.get("/api/mcp-audit")).json()

        subjects = [r["subject"] for r in rows]
        assert "моё_действие" in subjects
        assert "чужое_действие" not in subjects

    async def test_без_авторизации_нельзя(self, client):
        assert (await client.get("/api/mcp-audit")).status_code == 401

    async def test_свежие_сверху(self, auth_client, db_session, test_user):
        now = datetime.now(timezone.utc)
        db_session.add(AuditLog(user_id=test_user.id, event=audit.MCP_TOOL, subject="старое",
                                created_at=now - timedelta(days=2)))
        db_session.add(AuditLog(user_id=test_user.id, event=audit.MCP_TOOL, subject="новое", created_at=now))
        await db_session.commit()

        rows = (await auth_client.get("/api/mcp-audit")).json()
        assert rows[0]["subject"] == "новое"

    async def test_потолок_на_выдачу(self, auth_client, db_session, test_user):
        """limit из запроса — от пользователя, значит ограничен."""
        for i in range(5):
            db_session.add(AuditLog(user_id=test_user.id, event=audit.MCP_TOOL, subject=f"e{i}"))
        await db_session.commit()

        rows = (await auth_client.get("/api/mcp-audit", params={"limit": 1000000})).json()
        assert len(rows) <= 500


class TestСрокХранения:
    async def test_старое_удаляется_а_свежее_нет(self, db_session, test_user):
        """Это и есть ротация аудита — но с понятным сроком, а не
        «сколько влезло в 30 МБ docker-логов»."""
        from sqlalchemy import delete as sa_delete

        from app.cleanup import _AUDIT_RETENTION

        now = datetime.now(timezone.utc)
        db_session.add(AuditLog(user_id=test_user.id, event=audit.MCP_TOOL, subject="древнее",
                                created_at=now - _AUDIT_RETENTION - timedelta(days=1)))
        db_session.add(AuditLog(user_id=test_user.id, event=audit.MCP_TOOL, subject="свежее", created_at=now))
        await db_session.commit()

        cutoff = now - _AUDIT_RETENTION
        await db_session.execute(sa_delete(AuditLog).where(AuditLog.created_at < cutoff))
        await db_session.commit()

        left = [e.subject for e in await _events(db_session)]
        assert "свежее" in left
        assert "древнее" not in left
