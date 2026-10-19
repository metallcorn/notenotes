"""«Сделано» и «отложить» для напоминания — в вебе, в Telegram, в сводке.

Жалоба 18.10: напоминание открыли и не закрыли — и оно два месяца висело,
больше ни разу о себе не напомнив. Из Telegram его нельзя было ни закрыть,
ни отложить, а сводка показывала только то, что впереди.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app import daily_digest, notification_dispatch, reminder_actions, telegram_bot
from app.models import Notification, Space, TelegramLink, User
from app.security import hash_password
from app.tools.registry import ToolContext
from app.tools.reminders import snooze_reminder

WARSAW = ZoneInfo("Europe/Warsaw")


async def _reminder(db, user, *, at, dispatched=True, repeat=None, type_="reminder"):
    n = Notification(
        user_id=user.id, type=type_, title="Купить корм", body="",
        trigger_at=at, repeat_rule=repeat,
        dispatched_at=at if dispatched else None,
        read_at=at if dispatched else None,
    )
    db.add(n)
    await db.flush()
    await db.commit()
    return n


class TestКогдаОтложено:
    def test_завтра_утром_во_время_сводки_человека(self):
        user = User(timezone="Europe/Warsaw", digest_time="08:30")
        now = datetime(2026, 10, 18, 20, 0, tzinfo=WARSAW)

        until = reminder_actions.snooze_until("tomorrow", user, now)

        assert until.astimezone(WARSAW) == datetime(2026, 10, 19, 8, 30, tzinfo=WARSAW)

    def test_сводка_выключена_значит_девять(self):
        user = User(timezone="Europe/Warsaw", digest_time=None)
        now = datetime(2026, 10, 18, 20, 0, tzinfo=WARSAW)

        until = reminder_actions.snooze_until("week", user, now)

        assert until.astimezone(WARSAW) == datetime(2026, 10, 25, 9, 0, tzinfo=WARSAW)

    def test_через_час(self):
        user = User(timezone="Europe/Warsaw")
        now = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)

        assert reminder_actions.snooze_until("1h", user, now) == now + timedelta(hours=1)


class TestОтложенноеСрабатываетЗаново:
    async def test_диспетчер_присылает_его_ещё_раз(self, db_session, test_user, monkeypatch):
        """Не просто сдвиг даты: без сброса dispatched_at диспетчер
        считал бы его уже отправленным и больше не прислал."""
        past = datetime.now(timezone.utc) - timedelta(days=58)
        n = await _reminder(db_session, test_user, at=past)

        reminder_actions.snooze(db_session, n, datetime.now(timezone.utc) - timedelta(seconds=1))
        await db_session.commit()
        assert n.read_at is None

        sent = []

        async def fake_dispatch(notification, db):
            sent.append(notification.id)
            notification.dispatched_at = datetime.now(timezone.utc)

        @contextlib.asynccontextmanager
        async def same_session():
            yield db_session

        monkeypatch.setattr(notification_dispatch, "_dispatch_one", fake_dispatch)
        monkeypatch.setattr(notification_dispatch, "async_session", same_session)
        await notification_dispatch._dispatch_due()

        assert sent == [n.id]

    async def test_повторяющееся_не_сдвигает_цепочку(self, db_session, test_user):
        """«Каждый понедельник 9:00», отложенный на час, не должен стать
        «каждый понедельник 10:00»."""
        at = datetime.now(timezone.utc) + timedelta(hours=2)
        n = await _reminder(db_session, test_user, at=at, dispatched=False, repeat="weekly")

        reminder_actions.snooze(db_session, n, at + timedelta(hours=1))
        await db_session.commit()

        rows = (
            await db_session.execute(select(Notification).where(Notification.user_id == test_user.id))
        ).scalars().all()
        chain = [r for r in rows if r.repeat_rule == "weekly"]
        assert len(chain) == 1 and chain[0].trigger_at == at + timedelta(days=7)
        assert n.repeat_rule is None and n.trigger_at == at + timedelta(hours=1)


class TestВеб:
    async def test_отложить_через_api(self, auth_client, db_session, test_user):
        n = await _reminder(db_session, test_user, at=datetime.now(timezone.utc) - timedelta(days=3))

        r = await auth_client.post(f"/api/notifications/{n.id}/snooze", json={"preset": "tomorrow"})

        assert r.status_code == 200
        body = r.json()
        assert datetime.fromisoformat(body["trigger_at"]) > datetime.now(timezone.utc)
        assert body["read_at"] is None and body["resolved_at"] is None

    async def test_неизвестный_вариант(self, auth_client, db_session, test_user):
        n = await _reminder(db_session, test_user, at=datetime.now(timezone.utc))

        r = await auth_client.post(f"/api/notifications/{n.id}/snooze", json={"preset": "someday"})

        assert r.status_code == 400

    async def test_чужое_не_отложить(self, auth_client, db_session):
        other = User(username="snooze_other", password_hash=hash_password("x"), name="Other")
        db_session.add(other)
        await db_session.flush()
        n = await _reminder(db_session, other, at=datetime.now(timezone.utc))

        r = await auth_client.post(f"/api/notifications/{n.id}/snooze", json={"preset": "1h"})

        assert r.status_code == 404


class TestTelegram:
    async def test_под_напоминанием_есть_сделано_и_отложить(self, db_session, test_user, monkeypatch):
        sent = []

        async def fake_send(chat_id, text, reply_markup=None):
            sent.append(reply_markup)

        monkeypatch.setattr(telegram_bot, "send_message", fake_send)
        space = Space(name="Личное", owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(TelegramLink(user_id=test_user.id, chat_id=515151, space_id=space.id))
        n = await _reminder(db_session, test_user, at=datetime.now(timezone.utc), dispatched=False)

        await notification_dispatch._dispatch_one(n, db_session)

        datas = [b.get("callback_data") for row in sent[0]["inline_keyboard"] for b in row]
        assert f"nt:d:{n.id}" in datas
        assert f"nt:s:tomorrow:{n.id}" in datas
        assert all(len(d.encode()) <= 64 for d in datas if d)

    async def test_у_приглашения_кнопок_действий_нет(self, db_session, test_user):
        n = Notification(user_id=test_user.id, type="space_invite", title="Вас добавили", body="")
        assert reminder_actions.telegram_buttons(n) == []

    async def test_сделано(self, db_session, test_user):
        n = await _reminder(db_session, test_user, at=datetime.now(timezone.utc))

        reply = await reminder_actions.handle_callback(db_session, test_user.id, f"nt:d:{n.id}")

        assert reply == "✓ Сделано" and n.resolved_at is not None

    async def test_отложить(self, db_session, test_user):
        n = await _reminder(db_session, test_user, at=datetime.now(timezone.utc) - timedelta(days=1))

        reply = await reminder_actions.handle_callback(db_session, test_user.id, f"nt:s:1h:{n.id}")

        assert reply.startswith("⏰ Отложено до")
        assert n.trigger_at > datetime.now(timezone.utc) and n.dispatched_at is None

    async def test_чужое_кнопкой_не_закрыть(self, db_session, test_user):
        other = User(username="snooze_tg_other", password_hash=hash_password("x"), name="Other")
        db_session.add(other)
        await db_session.flush()
        n = await _reminder(db_session, other, at=datetime.now(timezone.utc))

        reply = await reminder_actions.handle_callback(db_session, test_user.id, f"nt:d:{n.id}")

        assert reply == "Напоминание не найдено" and n.resolved_at is None

    async def test_не_наши_данные(self, db_session, test_user):
        assert await reminder_actions.handle_callback(db_session, test_user.id, "dg:r:x") is None


class TestСводкаПоказываетВисящее:
    async def test_старое_незакрытое_в_сводке_с_кнопками(self, db_session, test_user):
        test_user.timezone = "Europe/Warsaw"
        n = await _reminder(db_session, test_user, at=datetime.now(timezone.utc) - timedelta(days=58))

        text, keyboard = await daily_digest.build_digest(db_session, test_user)

        assert "Висит" in text and "Купить корм" in text
        datas = [b.get("callback_data") for row in keyboard for b in row]
        assert f"dg:r:{n.id}" in datas and f"dg:z:{n.id}" in datas

    async def test_отложенное_из_сводки_пропадает(self, db_session, test_user):
        test_user.timezone = "Europe/Warsaw"
        n = await _reminder(db_session, test_user, at=datetime.now(timezone.utc) - timedelta(days=58))

        await daily_digest.handle_callback(db_session, test_user.id, f"dg:z:{n.id}")

        built = await daily_digest.build_digest(db_session, test_user)
        assert built is None or "Купить корм" not in built[0]

    async def test_закрытое_и_приглашения_не_висят(self, db_session, test_user):
        test_user.timezone = "Europe/Warsaw"
        old = datetime.now(timezone.utc) - timedelta(days=5)
        n = await _reminder(db_session, test_user, at=old)
        n.resolved_at = old
        await _reminder(db_session, test_user, at=old, type_="space_invite")
        await db_session.commit()

        assert await daily_digest.build_digest(db_session, test_user) is None


class TestАссистент:
    async def test_отложить_вместо_дубля(self, db_session, test_user):
        n = await _reminder(db_session, test_user, at=datetime.now(timezone.utc) - timedelta(days=2))
        ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.uuid4())
        until = (datetime.now(WARSAW) + timedelta(days=2)).replace(tzinfo=None, microsecond=0)

        result = await snooze_reminder(ctx, {"notification_id": str(n.id), "until": until.isoformat()})

        assert result["id"] == str(n.id)
        assert n.trigger_at > datetime.now(timezone.utc) and n.dispatched_at is None
        count = (
            await db_session.execute(select(Notification).where(Notification.user_id == test_user.id))
        ).scalars().all()
        assert len(count) == 1
