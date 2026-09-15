"""Напоминания о билетах — заранее, а не в момент начала.

Живой случай 15.09.2026: напоминание об авиарейсе W6 1234 пришло ровно в
08:15 — в момент вылета, когда человек уже сидел в самолёте. Ноль
опережения бессмыслен для всего, куда надо приехать заранее.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest_asyncio
from sqlalchemy import select

from app import tickets
from app.models import Item, Notification, Space, SpaceMember


@pytest_asyncio.fixture
async def ticket(db_session, test_user):
    test_user.timezone = "Europe/Warsaw"
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()

    async def make(ticket_type: str, *, title="Билет", start="2026-09-15T08:15:00", **extra):
        props = {"ticket_type": ticket_type, "datetime_start": start, **extra}
        item = Item(space_id=space.id, author_id=test_user.id, title=title, content="",
                    material_type="ticket", properties=props)
        db_session.add(item)
        await db_session.flush()
        await tickets._add_event_notification(db_session, item, props, title)
        await db_session.commit()
        return (await db_session.execute(
            select(Notification).where(Notification.payload["item_id"].astext == str(item.id))
        )).scalar_one()

    return make


def _local(n: Notification) -> str:
    from zoneinfo import ZoneInfo

    return n.trigger_at.astimezone(ZoneInfo("Europe/Warsaw")).strftime("%H:%M")


class TestОпережение:
    async def test_самолёт_за_три_часа(self, ticket):
        n = await ticket("flight", start="2026-09-15T08:15:00")
        assert _local(n) == "05:15"

    async def test_поезд_за_час(self, ticket):
        n = await ticket("train", start="2026-09-15T08:15:00")
        assert _local(n) == "07:15"

    async def test_мероприятие_за_два(self, ticket):
        n = await ticket("event", start="2026-09-15T20:00:00")
        assert _local(n) == "18:00"

    async def test_неизвестный_тип_за_час(self, ticket):
        n = await ticket("other", start="2026-09-15T08:15:00")
        assert _local(n) == "07:15"

    async def test_в_тексте_сказано_через_сколько(self, ticket):
        """Человек должен понимать, что это «через 3 часа», а не «сейчас»."""
        n = await ticket("flight", title="Рейс W6 1234")
        assert "Через 3 ч" in n.body


class TestСсылкаНаРейс:
    async def test_из_поля_распознавания(self, ticket):
        n = await ticket("flight", flight_number="W6 1234")
        assert "flightradar24.com/data/flights/w61234" in n.body

    async def test_из_заголовка_для_старых_билетов(self, ticket):
        """Поле flight_number появилось позже — у уже распознанных билетов
        его нет, но номер есть в заголовке."""
        n = await ticket("flight", title="Рейс W6 1234 Познань — Рим, 15.09")
        assert "flightradar24.com/data/flights/w61234" in n.body

    async def test_без_номера_ссылки_нет(self, ticket):
        n = await ticket("flight", title="Куда-то летим")
        assert "flightradar24" not in n.body

    async def test_у_поезда_ссылки_нет(self, ticket):
        n = await ticket("train", title="ЖД 7942 Познань — Варшава")
        assert "flightradar24" not in n.body

    def test_разбор_номера(self):
        assert tickets.extract_flight_number("W6 1234") == "W61234"
        assert tickets.extract_flight_number("Рейс LO 123 Варшава") == "LO123"
        assert tickets.extract_flight_number("FR1234") == "FR1234"
        assert tickets.extract_flight_number(None, "", "Билет") is None
        # Первый подходящий источник — приоритет у явного поля.
        assert tickets.extract_flight_number("LO 123", "Рейс W6 1234") == "LO123"
