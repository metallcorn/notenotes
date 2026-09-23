"""Утренняя сводка «что сегодня» и её кнопки в Telegram.

Половина тестов — про то, чего сводка НЕ должна: слать пустое, слать
дважды, закрывать чужое по кнопке.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest_asyncio

from app import daily_digest
from app.models import Item, Notification, Space, SpaceMember, User
from app.security import hash_password


@pytest_asyncio.fixture
async def base(db_session, test_user):
    test_user.timezone = "Europe/Warsaw"
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()

    tz = ZoneInfo("Europe/Warsaw")
    today_local = datetime.now(tz).replace(hour=15, minute=0, second=0, microsecond=0)

    async def reminder(title, at=None, *, user=None):
        n = Notification(user_id=(user or test_user).id, type="reminder", title=title, body="",
                         trigger_at=(at or today_local).astimezone(timezone.utc))
        db_session.add(n)
        await db_session.flush()
        await db_session.commit()
        return n

    async def event_note(title, at=None, *, owner=None, in_space=None):
        target = in_space or space
        item = Item(space_id=target.id, author_id=(owner or test_user).id, title="Письмо", content="",
                    material_type="note",
                    properties={"detected_events": [{"at": (at or today_local).isoformat(), "title": title}]})
        db_session.add(item)
        await db_session.flush()
        await db_session.commit()
        return item

    from types import SimpleNamespace

    return SimpleNamespace(space=space, reminder=reminder, event_note=event_note, today_local=today_local, tz=tz)


class TestСодержимое:
    async def test_напоминания_и_события_на_сегодня(self, base, db_session, test_user):
        await base.reminder("Позвонить в клинику")
        await base.event_note("Оплата налогов")

        text, keyboard = await daily_digest.build_digest(db_session, test_user)

        assert "Позвонить в клинику" in text
        assert "Оплата налогов" in text
        assert len(keyboard) == 2

    async def test_завтрашнее_не_попадает(self, base, db_session, test_user):
        """Сводка «на сегодня» — не «на неделю»."""
        await base.reminder("Завтрашнее", base.today_local + timedelta(days=1))

        assert await daily_digest.build_digest(db_session, test_user) is None

    async def test_пустая_сводка_не_собирается(self, base, db_session, test_user):
        """«На сегодня ничего» каждое утро учит смахивать не глядя."""
        assert await daily_digest.build_digest(db_session, test_user) is None

    async def test_кнопки_разные_для_напоминания_и_события(self, base, db_session, test_user):
        n = await base.reminder("Дело")
        item = await base.event_note("Событие")

        _, keyboard = await daily_digest.build_digest(db_session, test_user)

        datas = [row[0]["callback_data"] for row in keyboard]
        assert f"dg:r:{n.id}" in datas
        assert any(d.startswith(f"dg:e:{item.id}:") for d in datas)
        # Telegram даёт 64 байта на callback_data.
        assert all(len(d.encode()) <= 64 for d in datas)


class TestКнопки:
    async def test_сделано_закрывает_напоминание(self, base, db_session, test_user):
        n = await base.reminder("Дело")

        reply = await daily_digest.handle_callback(db_session, test_user.id, f"dg:r:{n.id}")

        await db_session.refresh(n)
        assert n.resolved_at is not None
        assert "Сделано" in reply

    async def test_не_актуально_убирает_событие(self, base, db_session, test_user):
        item = await base.event_note("Событие")
        key = daily_digest.event_key(item.properties["detected_events"][0]["at"], "Событие")

        reply = await daily_digest.handle_callback(db_session, test_user.id, f"dg:e:{item.id}:{key}")

        await db_session.refresh(item)
        assert "detected_events" not in item.properties
        assert "Убрано" in reply

    async def test_убирается_только_нужное_событие(self, base, db_session, test_user):
        """Индекс в массиве брать нельзя — события переупорядочиваются.
        Ключ от (дата, название) закрывает ровно то, что нажали."""
        at = base.today_local.isoformat()
        item = Item(space_id=base.space.id, author_id=test_user.id, title="x", content="", material_type="note",
                    properties={"detected_events": [{"at": at, "title": "Первое"}, {"at": at, "title": "Второе"}]})
        db_session.add(item)
        await db_session.flush()
        await db_session.commit()

        await daily_digest.handle_callback(db_session, test_user.id, f"dg:e:{item.id}:{daily_digest.event_key(at, 'Второе')}")

        await db_session.refresh(item)
        assert [e["title"] for e in item.properties["detected_events"]] == ["Первое"]

    async def test_чужое_напоминание_не_закрыть(self, base, db_session, test_user):
        """user_id — владелец чата, из которого пришло нажатие. Угадать id
        чужого напоминания и закрыть его кнопкой нельзя."""
        other = User(username=f"o_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), name="Чужой")
        db_session.add(other)
        await db_session.flush()
        n = await base.reminder("Чужое", user=other)

        reply = await daily_digest.handle_callback(db_session, test_user.id, f"dg:r:{n.id}")

        await db_session.refresh(n)
        assert n.resolved_at is None
        assert "не найдено" in reply

    async def test_чужое_событие_не_убрать(self, base, db_session, test_user):
        other = User(username=f"o_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), name="Чужой")
        db_session.add(other)
        await db_session.flush()
        other_space = Space(name="Чужое", owner_id=other.id)
        db_session.add(other_space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=other_space.id, user_id=other.id))
        await db_session.commit()
        item = await base.event_note("Чужое", owner=other, in_space=other_space)
        key = daily_digest.event_key(item.properties["detected_events"][0]["at"], "Чужое")

        reply = await daily_digest.handle_callback(db_session, test_user.id, f"dg:e:{item.id}:{key}")

        await db_session.refresh(item)
        assert item.properties["detected_events"]
        assert "не найдена" in reply

    async def test_чужой_префикс_игнорируется(self, db_session, test_user):
        assert await daily_digest.handle_callback(db_session, test_user.id, "sr:0") is None

    async def test_мусор_в_данных_не_роняет(self, db_session, test_user):
        for bad in ("dg:r:не-uuid", "dg:e:x", "dg:e:не-uuid:abc", "dg:"):
            assert await daily_digest.handle_callback(db_session, test_user.id, bad) is None


class TestКогдаСлать:
    async def test_только_в_своё_время_и_один_раз_в_день(self, base, db_session, test_user, monkeypatch):
        """Воркер проверяет раз в минуту. Без отметки слал бы в 09:00,
        09:01, 09:02 и ещё раз после перезапуска."""
        import contextlib

        sent: list = []

        async def fake_send(db, user):
            sent.append(user.id)
            return True

        @contextlib.asynccontextmanager
        async def same_session():
            yield db_session

        monkeypatch.setattr(daily_digest, "_send_for", fake_send)
        monkeypatch.setattr(daily_digest, "async_session", same_session)

        now_local = datetime.now(base.tz)
        test_user.digest_time = now_local.strftime("%H:%M")
        test_user.digest_sent_on = None
        await db_session.commit()

        await daily_digest._tick()
        await daily_digest._tick()  # та же минута — второй раз не должно

        assert sent == [test_user.id]
        await db_session.refresh(test_user)
        assert test_user.digest_sent_on == now_local.date().isoformat()

    async def test_выключенная_не_шлётся(self, base, db_session, test_user, monkeypatch):
        import contextlib

        sent: list = []

        async def fake_send(db, user):
            sent.append(user.id)
            return True

        @contextlib.asynccontextmanager
        async def same_session():
            yield db_session

        monkeypatch.setattr(daily_digest, "_send_for", fake_send)
        monkeypatch.setattr(daily_digest, "async_session", same_session)
        test_user.digest_time = None
        await db_session.commit()

        await daily_digest._tick()

        assert sent == []


class TestНастройка:
    async def test_смена_времени(self, auth_client):
        r = await auth_client.patch("/api/auth/me", json={"digest_time": "07:30"})
        assert r.status_code == 200
        assert r.json()["digest_time"] == "07:30"

    async def test_выключение_пустой_строкой(self, auth_client):
        r = await auth_client.patch("/api/auth/me", json={"digest_time": ""})
        assert r.status_code == 200
        assert r.json()["digest_time"] is None

    async def test_кривое_время_отклоняется(self, auth_client):
        for bad in ("9:00", "25:00", "09:60", "утром"):
            r = await auth_client.patch("/api/auth/me", json={"digest_time": bad})
            assert r.status_code == 400, bad

    async def test_по_умолчанию_девять_утра(self, auth_client):
        assert (await auth_client.get("/api/auth/me")).json()["digest_time"] == "09:00"


class TestПерерисовкаПослеКнопки:
    async def test_закрытый_пункт_пропадает_из_сводки(self, base, db_session, test_user):
        """Не «ответ „убрано“ под сообщением», а то же сообщение без пункта.

        Бот после нажатия собирает сводку заново из базы и редактирует
        исходное сообщение — здесь проверяется, что заново собранная
        действительно короче на закрытое.
        """
        n = await base.reminder("Позвонить")
        await base.event_note("Фестиваль")

        before, kb_before = await daily_digest.build_digest(db_session, test_user)
        await daily_digest.handle_callback(db_session, test_user.id, f"dg:r:{n.id}")
        after, kb_after = await daily_digest.build_digest(db_session, test_user)

        assert "Позвонить" in before and "Позвонить" not in after
        assert len(kb_before) == 2 and len(kb_after) == 1

    async def test_когда_всё_закрыто_сводки_нет(self, base, db_session, test_user):
        """Бот в этом случае УДАЛЯЕТ сообщение из чата: неактуальное
        удаляется, актуальное остаётся, а когда актуального не осталось —
        не остаётся и сообщения."""
        n = await base.reminder("Единственное")

        await daily_digest.handle_callback(db_session, test_user.id, f"dg:r:{n.id}")

        assert await daily_digest.build_digest(db_session, test_user) is None


class TestПрошедшееИРаннееЗавтра:
    """Живой случай 23.09.2026.

    Запись на приём в 08:00 попала в сводку, ушедшую в 09:00 — через час
    ПОСЛЕ. Две ошибки в одной: прошедшее показывалось как новость, и
    сводка в 09:00 физически не может вовремя сообщить о событии в 08:00.
    """

    async def test_прошедшее_сегодня_не_показывается(self, base, db_session, test_user):
        from unittest.mock import patch

        now = datetime.now(base.tz).replace(hour=9, minute=0, second=0, microsecond=0)
        await base.reminder("Было в восемь", now.replace(hour=8))
        await base.reminder("Будет в шесть", now.replace(hour=18))

        with patch("app.daily_digest.datetime") as fake:
            fake.now.return_value = now.astimezone(timezone.utc)
            fake.fromisoformat = datetime.fromisoformat
            built = await daily_digest.build_digest(db_session, test_user)

        text, _ = built
        assert "Было в восемь" not in text
        assert "Будет в шесть" in text

    async def test_раннее_завтрашнее_предупреждается_сегодня(self, base, db_session, test_user):
        """Про приём в 08:00 завтра надо сказать сегодня — завтрашняя
        сводка в 09:00 придёт уже поздно."""
        from unittest.mock import patch

        now = datetime.now(base.tz).replace(hour=9, minute=0, second=0, microsecond=0)
        test_user.digest_time = "09:00"
        await db_session.commit()
        await base.reminder("Приём завтра рано", (now + timedelta(days=1)).replace(hour=8))

        with patch("app.daily_digest.datetime") as fake:
            fake.now.return_value = now.astimezone(timezone.utc)
            fake.fromisoformat = datetime.fromisoformat
            built = await daily_digest.build_digest(db_session, test_user)

        text, _ = built
        assert "Завтра рано утром" in text
        assert "Приём завтра рано" in text

    async def test_позднее_завтрашнее_не_дублируется(self, base, db_session, test_user):
        """Про завтрашний вечер завтрашняя сводка скажет вовремя."""
        from unittest.mock import patch

        now = datetime.now(base.tz).replace(hour=9, minute=0, second=0, microsecond=0)
        await base.reminder("Завтра вечером", (now + timedelta(days=1)).replace(hour=19))

        with patch("app.daily_digest.datetime") as fake:
            fake.now.return_value = now.astimezone(timezone.utc)
            fake.fromisoformat = datetime.fromisoformat
            built = await daily_digest.build_digest(db_session, test_user)

        assert built is None

    async def test_у_завтрашнего_нет_кнопок(self, base, db_session, test_user):
        """Закрывать то, что ещё не наступило, незачем."""
        from unittest.mock import patch

        now = datetime.now(base.tz).replace(hour=9, minute=0, second=0, microsecond=0)
        await base.reminder("Приём завтра рано", (now + timedelta(days=1)).replace(hour=7))

        with patch("app.daily_digest.datetime") as fake:
            fake.now.return_value = now.astimezone(timezone.utc)
            fake.fromisoformat = datetime.fromisoformat
            text, keyboard = await daily_digest.build_digest(db_session, test_user)

        assert "Приём завтра рано" in text
        assert keyboard == []


class TestНачалоДняПоМесту:
    async def test_ночное_событие_не_выпадает(self, db_session, test_user):
        """Начало дня — в поясе человека, не в UTC. Для Варшавы (UTC+2)
        окно начиналось в 02:00 по местному, и всё между полуночью и
        двумя выпадало из «сегодня»."""
        from app.tools.agenda import _local_midnight_utc

        now = datetime(2026, 9, 23, 7, 0, tzinfo=timezone.utc)  # 09:00 в Варшаве

        assert _local_midnight_utc(now, "Europe/Warsaw") == datetime(2026, 9, 22, 22, 0, tzinfo=timezone.utc)
        assert _local_midnight_utc(now, "UTC") == datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
        # Кривой пояс не роняет.
        assert _local_midnight_utc(now, "Нет/Такого") is not None
