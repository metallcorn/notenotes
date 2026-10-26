"""Рутины: приёмы с подтверждением (app/routines.py, routers/routines.py).

Все данные вымышленные: Jan Kowalski и кот Burek.
"""

import contextlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import routines, telegram_bot
from app.models import Item, Notification, TelegramLink, User
from app.routine_schedule import STATUS_DONE, STATUS_MISSED, STATUS_PENDING
from app.security import hash_password

TIMES = {"mode": "times", "times": ["08:00", "20:00"], "min_gap_minutes": 600}


async def _space(auth_client, **kwargs):
    r = await auth_client.post("/api/spaces", json={"name": "Rodzina", **kwargs})
    return r.json()["id"]


async def _member(db_session, auth_client, space_id, username="anna_k"):
    other = User(username=username, password_hash=hash_password("x"), name="Anna")
    db_session.add(other)
    await db_session.commit()
    r = await auth_client.post(f"/api/spaces/{space_id}/members", json={"username": username})
    assert r.status_code == 201, r.text
    return other


async def _routine(auth_client, space_id, **overrides):
    payload = {
        "space_id": space_id,
        "title": "Tabletka dla Burka",
        "subject": "Burek",
        "dose": "pół tabletki",
        "schedule": TIMES,
        **overrides,
    }
    r = await auth_client.post("/api/routines", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _notifications(db_session, routine_id):
    rows = await db_session.execute(
        select(Notification).where(Notification.payload["item_id"].astext == routine_id).order_by(Notification.created_at)
    )
    return list(rows.scalars().all())


def _session_factory(session):
    @contextlib.asynccontextmanager
    async def factory():
        yield session

    return factory


async def _rewind(db_session, routine_id, *, minutes):
    """Сдвинуть открытый приём и его пинги в прошлое на minutes."""
    item = await db_session.get(Item, routine_id)
    props = routines.props_of(item)
    dose = routines.pending_dose(props)
    planned = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    dose["planned_at"] = planned.isoformat()
    routines.set_props(item, props)
    for n in await _notifications(db_session, str(routine_id)):
        if n.resolved_at is None:
            n.trigger_at = planned
    await db_session.commit()
    return dose


async def test_create_opens_first_dose_and_pings_every_member(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)

    routine = await _routine(auth_client, space_id)

    assert routine["status"] == "active"
    assert routine["schedule_text"] == "в 08:00 и 20:00"
    assert len(routine["doses"]) == 1 and routine["doses"][0]["status"] == STATUS_PENDING
    assert routine["next_at"] == routine["doses"][0]["planned_at"]
    notifications = await _notifications(db_session, routine["id"])
    assert {n.user_id for n in notifications} == {test_user.id, other.id}
    assert all(n.type == "routine_dose" for n in notifications)
    assert all(n.payload["dose_id"] == routine["doses"][0]["id"] for n in notifications)
    assert all(n.trigger_at == datetime.fromisoformat(routine["next_at"]) for n in notifications)

    # Рутина — обычная запись в папке, ищется и перемещается как заметка.
    r = await auth_client.get(f"/api/items?space_id={space_id}")
    assert any(i["id"] == routine["id"] and i["material_type"] == "routine" for i in r.json())
    assert "Расписание: в 08:00 и 20:00" in (await auth_client.get(f"/api/items/{routine['id']}")).json()["content"]


async def test_only_author_when_notify_self(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    await _member(db_session, auth_client, space_id)
    routine = await _routine(auth_client, space_id, notify="self")
    notifications = await _notifications(db_session, routine["id"])
    assert [n.user_id for n in notifications] == [test_user.id]


async def test_done_closes_everyone_and_opens_next(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    routine = await _routine(auth_client, space_id)
    dose_id = routine["doses"][0]["id"]

    r = await auth_client.post(f"/api/routines/{routine['id']}/doses/{dose_id}/done", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    done = next(d for d in body["doses"] if d["id"] == dose_id)
    assert done["status"] == STATUS_DONE
    assert done["done_by"] == str(test_user.id)
    assert done["done_by_name"] == test_user.name
    pending = [d for d in body["doses"] if d["status"] == STATUS_PENDING]
    assert len(pending) == 1 and pending[0]["planned_at"] > done["planned_at"]
    assert body["stats"]["done"] == 1

    notifications = await _notifications(db_session, routine["id"])
    first = [n for n in notifications if n.payload["dose_id"] == dose_id]
    assert len(first) == 2 and all(n.resolved_at is not None for n in first)
    following = [n for n in notifications if n.payload["dose_id"] == pending[0]["id"]]
    assert {n.user_id for n in following} == {test_user.id, other.id}

    # Повторно закрыть нельзя.
    r = await auth_client.post(f"/api/routines/{routine['id']}/doses/{dose_id}/done", json={})
    assert r.status_code == 409

    # История версий: снимок до отметки.
    r = await auth_client.get(f"/api/items/{routine['id']}/versions")
    assert r.status_code == 200 and len(r.json()) >= 1


async def test_done_for_someone_else_and_late_flag(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    routine = await _routine(auth_client, space_id)
    dose = await _rewind(db_session, routine["id"], minutes=40)

    r = await auth_client.post(
        f"/api/routines/{routine['id']}/doses/{dose['id']}/done", json={"by": str(other.id)}
    )
    assert r.status_code == 200, r.text
    done = next(d for d in r.json()["doses"] if d["id"] == dose["id"])
    assert done["done_by"] == str(other.id) and done["done_by_name"] == "Anna"
    assert done["late"] is True
    assert r.json()["stats"]["late"] == 1

    # За чужого — нельзя.
    stranger = User(username="stranger_x", password_hash=hash_password("x"), name="S")
    db_session.add(stranger)
    await db_session.commit()
    routine2 = await _routine(auth_client, space_id)
    r = await auth_client.post(
        f"/api/routines/{routine2['id']}/doses/{routine2['doses'][0]['id']}/done", json={"by": str(stranger.id)}
    )
    assert r.status_code == 400


async def test_defer_silences_only_me(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    routine = await _routine(auth_client, space_id)
    dose_id = routine["doses"][0]["id"]

    r = await auth_client.post(f"/api/routines/{routine['id']}/doses/{dose_id}/defer")
    assert r.status_code == 200, r.text
    dose = next(d for d in r.json()["doses"] if d["id"] == dose_id)
    assert dose["status"] == STATUS_PENDING
    assert [d["id"] for d in dose["deferred_by"]] == [str(test_user.id)]

    by_user = {n.user_id: n for n in await _notifications(db_session, routine["id"])}
    assert by_user[test_user.id].resolved_at is not None
    assert by_user[test_user.id].payload["deferred"] is True
    assert by_user[other.id].resolved_at is None


async def test_snooze_is_shared(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    routine = await _routine(auth_client, space_id)
    dose_id = routine["doses"][0]["id"]

    r = await auth_client.post(f"/api/routines/{routine['id']}/doses/{dose_id}/snooze", json={"minutes": 30})
    assert r.status_code == 200, r.text
    expected = datetime.now(timezone.utc) + timedelta(minutes=30)
    for n in await _notifications(db_session, routine["id"]):
        assert n.user_id in (test_user.id, other.id)
        assert abs((n.trigger_at - expected).total_seconds()) < 5
        assert n.dispatched_at is None


async def test_dispatch_rearms_nag_until_window_ends(auth_client, db_session, test_user, monkeypatch):
    import app.notification_dispatch as nd

    space_id = await _space(auth_client)
    routine = await _routine(auth_client, space_id, nag_minutes=30)
    await _rewind(db_session, routine["id"], minutes=3)
    monkeypatch.setattr(nd, "async_session", _session_factory(db_session))

    await nd._dispatch_due()

    (n,) = await _notifications(db_session, routine["id"])
    assert n.payload["nag_count"] == 1
    assert n.dispatched_at is None, "строка взведена заново"
    assert abs((n.trigger_at - (datetime.now(timezone.utc) + timedelta(minutes=30))).total_seconds()) < 5

    # Окно приёма истекло — больше не взводится.
    n.payload = {**n.payload, "nag_until": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}
    n.trigger_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    await nd._dispatch_due()
    (n,) = await _notifications(db_session, routine["id"])
    assert n.payload["nag_count"] == 2
    assert n.dispatched_at is not None


async def test_telegram_ping_replaces_previous_message(auth_client, db_session, test_user, monkeypatch):
    space_id = await _space(auth_client)
    routine = await _routine(auth_client, space_id)
    db_session.add(TelegramLink(user_id=test_user.id, chat_id=4242, space_id=space_id))
    await db_session.commit()
    sent, deleted = [], []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text, reply_markup))
        return 100 + len(sent)

    async def fake_delete(chat_id, message_id):
        deleted.append(message_id)

    monkeypatch.setattr(telegram_bot, "send_message", fake_send)
    monkeypatch.setattr(telegram_bot, "delete_message", fake_delete)
    await _rewind(db_session, routine["id"], minutes=3)
    (n,) = await _notifications(db_session, routine["id"])
    now = datetime.now(timezone.utc)

    await routines.deliver(db_session, n, 4242, now + timedelta(minutes=1))
    assert "Ждёт 4 мин" in sent[0][1]
    await routines.deliver(db_session, n, 4242, now + timedelta(minutes=31))

    assert deleted == [101], "второй пинг удаляет первое сообщение"
    assert n.payload["telegram_message_id"] == 102
    assert "Tabletka dla Burka" in sent[0][1] and "Burek · pół tabletki" in sent[0][1]
    assert "напоминаю 2-й раз" in sent[1][1]
    buttons = [b["text"] for row in sent[1][2]["inline_keyboard"] for b in row]
    assert buttons == ["✓ Дал", "Делает не я", "⏰ +30 мин", "⏰ +1 ч", "Пропустить", "Открыть"]


async def test_telegram_callback_done_redraws_and_closes_for_all(auth_client, db_session, test_user, monkeypatch):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    routine = await _routine(auth_client, space_id)
    db_session.add(TelegramLink(user_id=other.id, chat_id=7, space_id=space_id))
    await db_session.commit()
    edited = []

    async def fake_edit(chat_id, message_id, text, reply_markup=None):
        edited.append((chat_id, message_id, text))

    monkeypatch.setattr(telegram_bot, "edit_message", fake_edit)
    notifications = await _notifications(db_session, routine["id"])
    mine = next(n for n in notifications if n.user_id == test_user.id)
    theirs = next(n for n in notifications if n.user_id == other.id)
    theirs.payload = {**theirs.payload, "telegram_message_id": 555}
    await db_session.commit()

    text, keyboard = await routines.handle_callback(db_session, test_user.id, f"rt:d:{mine.id}")

    assert "✓ Test User" in text
    assert [b["text"] for row in keyboard for b in row] == ["Открыть"]
    assert edited and edited[0][:2] == (7, 555) and "✓ Test User" in edited[0][2]
    item = await db_session.get(Item, routine["id"])
    statuses = [d["status"] for d in item.properties["doses"]]
    assert statuses == [STATUS_DONE, STATUS_PENDING]

    # Чужое уведомление кнопкой не закрыть.
    assert await routines.handle_callback(db_session, test_user.id, f"rt:d:{theirs.id}") == ("Приём не найден", [])


async def test_telegram_callback_not_me_and_snooze(auth_client, db_session, test_user, monkeypatch):
    space_id = await _space(auth_client)
    routine = await _routine(auth_client, space_id)
    (mine,) = await _notifications(db_session, routine["id"])

    text, keyboard = await routines.handle_callback(db_session, test_user.id, f"rt:n:{mine.id}")
    assert "Ждём отметку" in text
    assert [b["text"] for row in keyboard for b in row] == ["✓ Всё-таки дал я", "Открыть"]

    text, keyboard = await routines.handle_callback(db_session, test_user.id, f"rt:s:30:{mine.id}")
    assert "Отложено до" in text
    assert await routines.handle_callback(db_session, test_user.id, f"rt:s:45:{mine.id}") is None


async def test_tick_marks_missed_and_opens_next(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    routine = await _routine(auth_client, space_id)
    item = await db_session.get(Item, routine["id"])
    props = routines.props_of(item)
    dose = routines.pending_dose(props)
    dose["nag_until"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    routines.set_props(item, props)
    await db_session.commit()

    await routines.tick(db_session)
    await db_session.commit()

    item = await db_session.get(Item, routine["id"])
    statuses = [d["status"] for d in item.properties["doses"]]
    assert statuses == [STATUS_MISSED, STATUS_PENDING]
    notifications = await _notifications(db_session, routine["id"])
    old = [n for n in notifications if n.payload["dose_id"] == dose["id"]]
    assert all(n.resolved_at is not None for n in old)
    assert any(n.resolved_at is None for n in notifications)
    assert "никто не отметил" in item.content


async def test_course_end_finishes_routine(auth_client, db_session, test_user):
    from zoneinfo import ZoneInfo

    space_id = await _space(auth_client)
    routine = await _routine(auth_client, space_id, schedule={"mode": "times", "times": ["23:59"]})
    dose = routine["doses"][0]
    # Курс кончается в день первого приёма — после него следующего нет.
    last_day = datetime.fromisoformat(dose["planned_at"]).astimezone(ZoneInfo(routine["timezone"])).date()
    r = await auth_client.patch(f"/api/routines/{routine['id']}", json={"ends_on": last_day.isoformat()})
    assert r.status_code == 200, r.text
    dose = r.json()["doses"][0]
    assert r.json()["status"] == "active" and dose["status"] == STATUS_PENDING

    r = await auth_client.post(f"/api/routines/{routine['id']}/doses/{dose['id']}/done", json={})
    assert r.status_code == 200, r.text
    assert r.json()["next_at"] is None
    assert r.json()["status"] == "finished"


async def test_patch_schedule_recomputes_open_dose(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    routine = await _routine(auth_client, space_id)
    old_dose = routine["doses"][0]["id"]

    r = await auth_client.patch(
        f"/api/routines/{routine['id']}", json={"schedule": {"mode": "interval", "every_minutes": 1440, "first_at": "12:00"}}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schedule_text"] == "каждый день"
    assert [d["status"] for d in body["doses"]] == [STATUS_PENDING]
    assert body["doses"][0]["id"] != old_dose
    old = [n for n in await _notifications(db_session, routine["id"]) if n.payload["dose_id"] == old_dose]
    assert all(n.resolved_at is not None for n in old)

    r = await auth_client.patch(f"/api/routines/{routine['id']}", json={"paused": True})
    assert r.status_code == 200 and r.json()["next_at"] is None and r.json()["paused"] is True
    r = await auth_client.patch(f"/api/routines/{routine['id']}", json={"paused": False})
    assert r.json()["next_at"] is not None


async def test_delete_closes_open_pings(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    routine = await _routine(auth_client, space_id)
    r = await auth_client.delete(f"/api/items/{routine['id']}")
    assert r.status_code == 204
    assert all(n.resolved_at is not None for n in await _notifications(db_session, routine["id"]))
    r = await auth_client.get(f"/api/routines/{routine['id']}")
    assert r.status_code == 404


async def test_generic_resolve_and_snooze_route_to_routine(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    routine = await _routine(auth_client, space_id)
    mine = next(n for n in await _notifications(db_session, routine["id"]) if n.user_id == test_user.id)

    r = await auth_client.post(f"/api/notifications/{mine.id}/snooze", json={"preset": "30m"})
    assert r.status_code == 200, r.text
    r = await auth_client.post(f"/api/notifications/{mine.id}/resolve")
    assert r.status_code == 200, r.text
    assert r.json()["resolved_at"] is not None
    item = await db_session.get(Item, routine["id"])
    assert item.properties["doses"][0]["status"] == STATUS_DONE
    theirs = next(n for n in await _notifications(db_session, routine["id"]) if n.user_id == other.id and n.payload["dose_id"] == item.properties["doses"][0]["id"])
    assert theirs.resolved_at is not None


async def test_validation(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    r = await auth_client.post("/api/routines", json={"space_id": space_id, "title": "x", "schedule": {"mode": "times", "times": []}})
    assert r.status_code == 422
    r = await auth_client.post("/api/routines", json={"space_id": space_id, "title": "x", "schedule": {"mode": "times", "times": ["25:00"]}})
    assert r.status_code == 422
    r = await auth_client.post(
        "/api/routines",
        json={"space_id": space_id, "title": "x", "schedule": TIMES, "starts_on": "2026-11-10", "ends_on": "2026-11-01"},
    )
    assert r.status_code == 422
