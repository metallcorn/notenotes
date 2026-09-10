"""list_agenda — «что у меня впереди».

Дыра нашлась вопросом «увидит ли Клод мою адженду». Оказалось, что не
увидит её и наш собственный ассистент, и Telegram-бот: распознанные в
заметках события (даты вылетов, приёмов, сроков документов) жили вообще
без инструмента — только в ActivityView.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest_asyncio

from app.models import Item, Notification, Space, SpaceMember, User
from app.security import hash_password
from app.tools import agenda


def _iso(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest_asyncio.fixture
async def base(db_session, test_user):
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()

    async def note_with_events(events, *, title="Билет", in_space=None, vault=False):
        target = in_space
        if target is None:
            target = space
        item = Item(
            space_id=target.id, author_id=target.owner_id, title=title, content="",
            material_type="note", properties={"detected_events": events},
        )
        db_session.add(item)
        await db_session.flush()
        await db_session.commit()
        return item

    async def reminder(title, at, *, resolved=False):
        n = Notification(
            user_id=test_user.id, type="reminder", title=title, body="",
            trigger_at=datetime.fromisoformat(at),
            resolved_at=datetime.now(timezone.utc) if resolved else None,
        )
        db_session.add(n)
        await db_session.flush()
        await db_session.commit()
        return n

    ctx = SimpleNamespace(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="Europe/Warsaw")
    return SimpleNamespace(space=space, ctx=ctx, note_with_events=note_with_events, reminder=reminder)


class TestЧтоПопадает:
    async def test_напоминания_и_распознанные_события_вместе(self, base):
        """Ради этого инструмент и заводился: раньше вторые не видел никто."""
        await base.reminder("Купить корм коту", _iso(2))
        await base.note_with_events([{"at": _iso(3), "title": "Вылет в Тбилиси"}])

        out = await agenda.handle(base.ctx, {})

        kinds = {e["kind"] for e in out["entries"]}
        assert kinds == {"напоминание", "распознано в заметке"}

    async def test_отсортировано_по_времени(self, base):
        await base.reminder("Позже", _iso(5))
        await base.note_with_events([{"at": _iso(1), "title": "Раньше"}])

        titles = [e["title"] for e in (await agenda.handle(base.ctx, {}))["entries"]]

        assert titles == ["Раньше", "Позже"]

    async def test_у_распознанного_видно_откуда_оно(self, base):
        """Событие распознала модель. Человек имеет право проверить
        источник, а ассистент — сослаться на него, а не утверждать от себя.
        """
        await base.note_with_events([{"at": _iso(2), "title": "Приём у врача"}], title="Письмо из клиники")

        entry = (await agenda.handle(base.ctx, {}))["entries"][0]

        assert entry["source_note"] == "Письмо из клиники"
        assert entry["url"]

    async def test_у_напоминания_есть_id_для_закрытия(self, base):
        """Иначе ассистенту пришлось бы искать его отдельным вызовом."""
        await base.reminder("Оплатить счёт", _iso(1))

        entry = (await agenda.handle(base.ctx, {}))["entries"][0]

        assert uuid.UUID(entry["reminder_id"])


class TestЧтоНеПопадает:
    async def test_прошедшее(self, base):
        await base.reminder("Вчерашнее", _iso(-3))
        await base.note_with_events([{"at": _iso(-10), "title": "Давно было"}])

        assert (await agenda.handle(base.ctx, {}))["entries"] == []

    async def test_сегодняшнее_утро_ещё_считается(self, base):
        """Событие в 9 утра, о котором спрашивают в 11, из ответа выпадать
        не должно — поэтому нижняя граница это начало дня, а не «сейчас».
        """
        today_morning = datetime.now(timezone.utc).replace(hour=0, minute=30, second=0, microsecond=0)
        await base.note_with_events([{"at": today_morning.isoformat(), "title": "Утренний рейс"}])

        titles = [e["title"] for e in (await agenda.handle(base.ctx, {}))["entries"]]

        assert "Утренний рейс" in titles

    async def test_дальше_горизонта(self, base):
        await base.note_with_events([{"at": _iso(60), "title": "Через два месяца"}])

        assert (await agenda.handle(base.ctx, {}))["entries"] == []
        # А если спросили явно — попадает.
        far = await agenda.handle(base.ctx, {"days": 90})
        assert [e["title"] for e in far["entries"]] == ["Через два месяца"]

    async def test_закрытое_напоминание(self, base):
        await base.reminder("Уже сделано", _iso(2), resolved=True)

        assert (await agenda.handle(base.ctx, {}))["entries"] == []

    async def test_события_из_СЕЙФА(self, base, db_session, test_user):
        """Главный инвариант. Сейф зашифрован на клиенте, и даже заголовок
        события оттуда наружу отдавать нельзя."""
        vault = Space(name="Мои Документы", owner_id=test_user.id, is_vault=True)
        db_session.add(vault)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=vault.id, user_id=test_user.id))
        await db_session.commit()
        await base.note_with_events([{"at": _iso(2), "title": "Срок действия паспорта"}], in_space=vault)

        titles = [e["title"] for e in (await agenda.handle(base.ctx, {}))["entries"]]

        assert "Срок действия паспорта" not in titles

    async def test_чужие_события(self, base, db_session):
        other = User(username=f"o_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), name="Чужой")
        db_session.add(other)
        await db_session.flush()
        other_space = Space(name="Чужое", owner_id=other.id)
        db_session.add(other_space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=other_space.id, user_id=other.id))
        await db_session.commit()
        await base.note_with_events([{"at": _iso(2), "title": "Чужая свадьба"}], in_space=other_space)

        titles = [e["title"] for e in (await agenda.handle(base.ctx, {}))["entries"]]

        assert "Чужая свадьба" not in titles


class TestУстойчивость:
    async def test_кривая_дата_не_роняет_весь_ответ(self, base):
        """Даты распознаёт модель, и формат она соблюдает не всегда.

        Одна кривая запись не должна отнимать у человека остальные.
        """
        await base.note_with_events([
            {"at": "как-нибудь на неделе", "title": "Мусор"},
            {"at": _iso(2), "title": "Нормальное событие"},
        ])

        titles = [e["title"] for e in (await agenda.handle(base.ctx, {}))["entries"]]

        assert titles == ["Нормальное событие"]

    async def test_событие_без_даты_или_названия_пропускается(self, base):
        await base.note_with_events([
            {"at": _iso(2)},
            {"title": "Без даты"},
            {"at": _iso(3), "title": "Целое"},
        ])

        titles = [e["title"] for e in (await agenda.handle(base.ctx, {}))["entries"]]

        assert titles == ["Целое"]

    async def test_бессмысленный_горизонт_не_ломает(self, base):
        await base.note_with_events([{"at": _iso(2), "title": "Событие"}])

        for bad in ({"days": 0}, {"days": -5}, {"days": "много"}, {"days": None}, {"days": 10**9}):
            out = await agenda.handle(base.ctx, bad)
            assert 1 <= out["horizon_days"] <= agenda.MAX_HORIZON_DAYS

    async def test_пусто_это_нормальный_ответ(self, base):
        out = await agenda.handle(base.ctx, {})

        assert out["entries"] == []
        # Сегодняшняя дата есть всегда: без неё модель не поймёт, что
        # «пусто» относится именно к ближайшим дням.
        assert out["today"]


class TestДоступностьВезде:
    async def test_инструмент_есть_у_ассистента_и_не_выключается(self):
        """Не дополнительное умение, а базовый вопрос «что у меня впереди»."""
        from app.tools.registry import SKILL_CATALOG, get_tool_definitions

        assert "list_agenda" in {t.name for t in get_tool_definitions()}
        assert SKILL_CATALOG["list_agenda"]["toggleable"] is False

    async def test_инструмент_отдаётся_наружу_по_MCP(self):
        """Вопрос, с которого всё началось, — увидит ли его Клод."""
        from app.routers.mcp import MCP_EXCLUDED_TOOLS
        from app.tools.registry import get_tool_definitions

        assert "list_agenda" in {t.name for t in get_tool_definitions(set(MCP_EXCLUDED_TOOLS))}
