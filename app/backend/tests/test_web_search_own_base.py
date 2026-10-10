"""Веб-поиск сообщает, если спрошенное есть в собственных записях.

ЖИВОЙ СЛУЧАЙ 10.10, и он показательный. Утренняя сводка написала человеку
про «Marsz Kejterka в Познани» — событие, распознанное в двух его же
заметках. Через пару часов он спросил бота: «А что такое Кейтерка?»
Ассистент ушёл в веб с запросом «Кейтерка что это», получил страницы про
КЕЙТЕРИНГ и выдал лекцию про «ресторан на выезд» — хотя ответ (собачий
марш, kejter — «пёс» на познанском) лежал в заметках, о которых ему же
утром и написали.

Правило «сначала ищи в базе» в описании web_search стоит первой строкой и
не помогло: модель не подозревала, что слово ей знакомо. Поэтому не
правило, а факт в результате.
"""

from __future__ import annotations

import httpx
import pytest_asyncio
from types import SimpleNamespace

from app.models import Item, Space, SpaceMember
from app.tools import web_search


def _tavily(monkeypatch, results):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": results})

    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(web_search.httpx, "AsyncClient", factory)
    monkeypatch.setattr(
        web_search, "get_settings", lambda: SimpleNamespace(tavily_api_key="test-key")
    )


@pytest_asyncio.fixture
async def ctx(db_session, test_user):
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()

    async def note(title, content):
        item = Item(
            space_id=space.id, author_id=test_user.id, title=title,
            content=content, material_type="note", properties={},
        )
        db_session.add(item)
        await db_session.flush()
        await db_session.commit()
        return item

    return SimpleNamespace(
        ctx=SimpleNamespace(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="Europe/Warsaw"),
        note=note,
        space=space,
    )


CATERING = [{"title": "Что такое кейтеринг", "url": "https://usta-catering.ru/x", "content": "ресторан на выезд"}]


async def test_своё_попадает_в_результат_рядом_с_вебом(ctx, monkeypatch):
    _tavily(monkeypatch, CATERING)
    own = await ctx.note("🐕 Marsz Kejterka уже в субботу", "В субботу в Познани пройдёт пятый Marsz Kejterka")

    result = await web_search.handle(ctx.ctx, {"query": "Marsz Kejterka"})

    assert result["results"], "веб-выдача остаётся на месте"
    hint = result["есть_в_базе_пользователя"]
    assert str(own.id) in [z["id"] for z in hint["записи"]]
    assert "get_note" in hint["подсказка"], "модели надо сказать, что делать дальше"


async def test_без_своего_поля_нет(ctx, monkeypatch):
    """Про погоду в базе ничего не найдётся — лишнего поля быть не должно."""
    _tavily(monkeypatch, CATERING)

    result = await web_search.handle(ctx.ctx, {"query": "погода в Познани на выходные"})

    assert "есть_в_базе_пользователя" not in result


async def test_сейф_не_подсказывается(ctx, db_session, test_user, monkeypatch):
    """Содержимое сейфа не попадает ни в промпт, ни в подсказки — ТЗ §16."""
    _tavily(monkeypatch, CATERING)
    vault = Space(name="Secret", owner_id=test_user.id, is_vault=True)
    db_session.add(vault)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=vault.id, user_id=test_user.id))
    db_session.add(Item(
        space_id=vault.id, author_id=test_user.id, title="Kejterka тайная",
        content="Marsz Kejterka", material_type="note", properties={},
    ))
    await db_session.commit()

    result = await web_search.handle(ctx.ctx, {"query": "Marsz Kejterka"})

    assert "есть_в_базе_пользователя" not in result


async def test_чужое_не_подсказывается(ctx, db_session, monkeypatch):
    from app.models import User
    from app.security import hash_password

    _tavily(monkeypatch, CATERING)
    other = User(username="other@example.com", name="Другой", password_hash=hash_password("x"))
    db_session.add(other)
    await db_session.flush()
    other_space = Space(name="Чужое", owner_id=other.id)
    db_session.add(other_space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=other_space.id, user_id=other.id))
    db_session.add(Item(
        space_id=other_space.id, author_id=other.id, title="Kejterka чужая",
        content="Marsz Kejterka", material_type="note", properties={},
    ))
    await db_session.commit()

    result = await web_search.handle(ctx.ctx, {"query": "Marsz Kejterka"})

    assert "есть_в_базе_пользователя" not in result


async def test_поломка_поиска_по_базе_не_роняет_веб_поиск(ctx, monkeypatch):
    """Подсказка не стоит того, чтобы отнять у человека ответ."""
    _tavily(monkeypatch, CATERING)

    async def boom(*a, **kw):
        raise RuntimeError("индекс недоступен")

    monkeypatch.setattr("app.routers.search.search_items", boom)

    result = await web_search.handle(ctx.ctx, {"query": "Marsz Kejterka"})

    assert result["results"]
    assert "есть_в_базе_пользователя" not in result


async def test_не_больше_трёх_записей(ctx, monkeypatch):
    """Это подсказка «посмотри сюда», а не выдача: полноценный поиск по
    базе у модели уже есть (search_base)."""
    _tavily(monkeypatch, CATERING)
    for i in range(5):
        await ctx.note(f"Kejterka {i}", "Marsz Kejterka в Познани")

    result = await web_search.handle(ctx.ctx, {"query": "Kejterka"})

    assert len(result["есть_в_базе_пользователя"]["записи"]) == web_search._OWN_HITS
