"""Повторяющиеся напоминания.

Запрос владельца: «каждый понедельник», «раз в месяц оплатить» —
приходилось заводить заново, все напоминания были одноразовыми.

Половина тестов — про арифметику дат: она обманчиво простая. «Через
месяц» от 31 января — не 31 февраля, а «через год» от 29 февраля бывает
раз в четыре года.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app import recurrence
from app.models import Notification, Space, SpaceMember
from app.recurrence import DAILY, MONTHLY, WEEKLY, YEARLY, next_occurrence

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


class TestАрифметикаДат:
    def test_простые_шаги(self):
        base = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
        assert next_occurrence(base, DAILY, now=base) == base + timedelta(days=1)
        assert next_occurrence(base, WEEKLY, now=base) == base + timedelta(weeks=1)
        assert next_occurrence(base, MONTHLY, now=base) == base.replace(month=11)
        assert next_occurrence(base, YEARLY, now=base) == base.replace(year=2027)

    def test_тридцать_первое_января_не_уезжает_за_февраль(self):
        """Человек, поставивший на 31-е, имел в виду «в конце месяца»."""
        base = datetime(2026, 1, 31, 9, 0, tzinfo=timezone.utc)
        assert next_occurrence(base, MONTHLY, now=base) == datetime(2026, 2, 28, 9, 0, tzinfo=timezone.utc)

    def test_високосный_февраль(self):
        base = datetime(2028, 1, 31, 9, 0, tzinfo=timezone.utc)
        assert next_occurrence(base, MONTHLY, now=base).day == 29

    def test_двадцать_девятое_февраля_раз_в_год(self):
        base = datetime(2028, 2, 29, 9, 0, tzinfo=timezone.utc)
        assert next_occurrence(base, YEARLY, now=base) == datetime(2029, 2, 28, 9, 0, tzinfo=timezone.utc)

    def test_пропущенное_не_копится(self):
        """Сервер лежал две недели / человек был в отпуске. Напоминание
        «полить цветы» нужно один раз на сегодня, а не четырнадцать."""
        long_ago = NOW - timedelta(days=14)

        following = next_occurrence(long_ago, DAILY, now=NOW)

        assert following > NOW
        assert following <= NOW + timedelta(days=1)

    def test_неизвестное_правило_не_повторяет(self):
        assert next_occurrence(NOW, "каждое полнолуние", now=NOW) is None

    def test_наивное_время_не_роняет(self):
        naive = datetime(2026, 10, 2, 9, 0)
        assert next_occurrence(naive, DAILY, now=naive) is not None


@pytest_asyncio.fixture
async def reminder(db_session, test_user):
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()

    async def make(*, repeat=None, trigger_at=None, resolved=False):
        n = Notification(
            user_id=test_user.id, type="reminder", title="Полить цветы", body="",
            trigger_at=trigger_at or (datetime.now(timezone.utc) - timedelta(minutes=1)),
            repeat_rule=repeat,
            resolved_at=datetime.now(timezone.utc) if resolved else None,
        )
        db_session.add(n)
        await db_session.flush()
        await db_session.commit()
        return n

    return make


def _session_factory(db):
    """Подменить async_session диспетчера на тестовую сессию.

    Диспетчер открывает сессию сам (`async with async_session() as db`) —
    это правильно для воркера и неудобно для теста, у которого данные живут
    в своей транзакции. Отдаём ту же сессию и не закрываем её.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory():
        yield db

    return factory


async def _all(db) -> list[Notification]:
    return list((await db.execute(select(Notification).order_by(Notification.trigger_at))).scalars().all())


class TestПродолжениеЦепочки:
    async def test_после_отправки_появляется_следующее(self, reminder, db_session):
        from app.notification_dispatch import _schedule_next

        first = await reminder(repeat=WEEKLY)

        _schedule_next(first, db_session)
        await db_session.commit()

        found = await _all(db_session)
        assert len(found) == 2
        assert found[1].trigger_at - first.trigger_at == timedelta(weeks=1)
        assert found[1].repeat_rule == WEEKLY

    async def test_отправленное_больше_не_порождает(self, reminder, db_session):
        """Иначе повторный проход диспетчера наплодил бы копий."""
        from app.notification_dispatch import _schedule_next

        first = await reminder(repeat=WEEKLY)
        _schedule_next(first, db_session)
        _schedule_next(first, db_session)
        await db_session.commit()

        assert len(await _all(db_session)) == 2

    async def test_цепочка_не_рвётся_без_отметки_выполнено(self, reminder, db_session):
        """Ключевое решение: следующий раз заводим ПОСЛЕ ОТПРАВКИ, а не
        после «сделано». Иначе «каждый понедельник» обрывалось бы на
        первой же неделе, когда человек не нажал галочку."""
        from app.notification_dispatch import _schedule_next

        first = await reminder(repeat=WEEKLY)
        assert first.resolved_at is None

        _schedule_next(first, db_session)
        await db_session.commit()

        assert len(await _all(db_session)) == 2

    async def test_сделанное_заранее_не_обрывает_серию(self, reminder, db_session, monkeypatch):
        """Полил цветы утром, галочку поставил — вечерний пинг не нужен, а
        вот «больше никогда не напоминать» было бы молчаливой потерей."""
        import app.notification_dispatch as nd

        await reminder(repeat=DAILY, resolved=True)

        sent: list = []
        async def fake_dispatch(n, db):
            sent.append(n)
        monkeypatch.setattr(nd, "_dispatch_one", fake_dispatch)
        monkeypatch.setattr(nd, "async_session", _session_factory(db_session))

        await nd._dispatch_due()

        assert sent == [], "отмеченное выполненным доставлять незачем"
        found = await _all(db_session)
        assert len(found) == 2
        assert found[1].resolved_at is None

    async def test_закрытая_строка_не_плодит_повторы(self, reminder, db_session, monkeypatch):
        """Второй проход диспетчера по тому же сделанному-заранее."""
        import app.notification_dispatch as nd

        await reminder(repeat=DAILY, resolved=True)
        async def fake_dispatch(n, db):
            pass
        monkeypatch.setattr(nd, "_dispatch_one", fake_dispatch)
        monkeypatch.setattr(nd, "async_session", _session_factory(db_session))

        await nd._dispatch_due()
        await nd._dispatch_due()

        # Вторая копия в будущем, её срок не наступил — всего две строки.
        assert len(await _all(db_session)) == 2

    async def test_одноразовое_остаётся_одноразовым(self, reminder, db_session):
        from app.notification_dispatch import _schedule_next

        first = await reminder(repeat=None)
        _schedule_next(first, db_session)
        await db_session.commit()

        assert len(await _all(db_session)) == 1

    async def test_без_времени_повторять_нечего(self, reminder, db_session):
        from app.notification_dispatch import _schedule_next

        n = await reminder(repeat=DAILY)
        n.trigger_at = None
        _schedule_next(n, db_session)
        await db_session.commit()

        assert len(await _all(db_session)) == 1


class TestВходы:
    async def test_ассистент_заводит_повтор(self, db_session, test_user):
        from types import SimpleNamespace

        from app.tools import reminders

        space = Space(name="S", owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
        await db_session.commit()
        ctx = SimpleNamespace(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="Europe/Warsaw")

        out = await reminders.create_reminder(ctx, {
            "title": "Оплатить ZUS", "trigger_at": "2026-11-10T09:00:00", "repeat": "monthly",
        })

        assert out["repeat"] == "каждый месяц"
        saved = (await db_session.execute(select(Notification))).scalars().first()
        assert saved.repeat_rule == MONTHLY

    async def test_ассистенту_объясняют_опечатку(self, db_session, test_user):
        from types import SimpleNamespace

        from app.tools import reminders
        from app.tools.registry import ToolError

        ctx = SimpleNamespace(db=db_session, user_id=test_user.id, space_id=None, client_timezone="UTC")

        with pytest.raises(ToolError) as e:
            await reminders.create_reminder(ctx, {
                "title": "x", "trigger_at": "2026-11-10T09:00:00", "repeat": "еженедельно",
            })

        assert "daily" in str(e.value)

    async def test_через_приложение(self, auth_client):
        space_id = (await auth_client.post("/api/spaces", json={"name": "S"})).json()["id"]
        r = await auth_client.post("/api/notifications", json={
            "title": "Вынести мусор", "trigger_at": "2026-11-10T20:00:00", "repeat": "weekly",
        })
        assert r.status_code in (200, 201), r.text
        assert r.json()["repeat_rule"] == "weekly"
        assert space_id

    async def test_приложение_отклоняет_мусор(self, auth_client):
        r = await auth_client.post("/api/notifications", json={
            "title": "x", "trigger_at": "2026-11-10T20:00:00", "repeat": "иногда",
        })
        assert r.status_code == 400
