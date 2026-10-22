from datetime import datetime, timedelta, timezone


async def test_create_list_resolve_delete_notification(auth_client):
    trigger_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    r = await auth_client.post(
        "/api/notifications", json={"title": "Reminder", "body": "Body", "trigger_at": trigger_at}
    )
    assert r.status_code == 201
    notif_id = r.json()["id"]

    r = await auth_client.get("/api/notifications")
    assert r.status_code == 200 and any(n["id"] == notif_id for n in r.json())

    r = await auth_client.post(f"/api/notifications/{notif_id}/resolve")
    assert r.status_code == 200 and r.json()["resolved_at"] is not None

    # уже наступившее + resolved — больше не в scope="due" по умолчанию
    r = await auth_client.get("/api/notifications")
    assert not any(n["id"] == notif_id for n in r.json())

    r = await auth_client.get("/api/notifications?scope=all")
    assert any(n["id"] == notif_id for n in r.json())

    r = await auth_client.post(f"/api/notifications/{notif_id}/unresolve")
    assert r.status_code == 200 and r.json()["resolved_at"] is None

    r = await auth_client.post(f"/api/notifications/{notif_id}/read")
    assert r.status_code == 200 and r.json()["read_at"] is not None

    r = await auth_client.delete(f"/api/notifications/{notif_id}")
    assert r.status_code == 204


async def test_notification_for_foreign_item_rejected(auth_client, client, db_session):
    from app.models import User
    from app.security import create_session_token, hash_password

    other = User(username="notif_other", password_hash=hash_password("x"), name="Other")
    db_session.add(other)
    await db_session.flush()

    r = await auth_client.post("/api/spaces", json={"name": "Private"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    other_client = client
    other_client.cookies.set("notenotes_session", create_session_token(other.id))
    trigger_at = datetime.now(timezone.utc).isoformat()
    r = await other_client.post(
        "/api/notifications", json={"title": "T", "body": "", "trigger_at": trigger_at, "item_id": item_id}
    )
    assert r.status_code == 404


async def test_reminder_on_shared_item_notifies_all_space_members(auth_client, client, db_session):
    # Реальный запрос: напоминание, поставленное в общей заметке, должно
    # сработать у всех участников спейса, не только у того, кто его создал
    # — права на спейс общие (routers/notifications.py, tools/reminders.py).
    from app.models import SpaceMember, User
    from app.security import create_session_token, hash_password

    other = User(username="notif_shared_other", password_hash=hash_password("x"), name="Other")
    db_session.add(other)
    await db_session.flush()

    r = await auth_client.post("/api/spaces", json={"name": "Shared"})
    space_id = r.json()["id"]
    db_session.add(SpaceMember(space_id=space_id, user_id=other.id))
    await db_session.flush()

    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    trigger_at = datetime.now(timezone.utc).isoformat()
    r = await auth_client.post(
        "/api/notifications", json={"title": "Общее", "body": "", "trigger_at": trigger_at, "item_id": item_id}
    )
    assert r.status_code == 201

    other_client = client
    other_client.cookies.set("notenotes_session", create_session_token(other.id))
    r = await other_client.get("/api/notifications?scope=all")
    assert any(n["title"] == "Общее" for n in r.json())


async def test_reminder_without_item_stays_private(auth_client, client, db_session):
    # Без item_id нет спейса, на который распространять — напоминание
    # остаётся только у автора, как и раньше.
    from app.models import User
    from app.security import create_session_token, hash_password

    other = User(username="notif_private_other", password_hash=hash_password("x"), name="Other")
    db_session.add(other)
    await db_session.flush()

    trigger_at = datetime.now(timezone.utc).isoformat()
    r = await auth_client.post(
        "/api/notifications", json={"title": "Личное", "body": "", "trigger_at": trigger_at}
    )
    assert r.status_code == 201

    other_client = client
    other_client.cookies.set("notenotes_session", create_session_token(other.id))
    r = await other_client.get("/api/notifications?scope=all")
    assert not any(n["title"] == "Личное" for n in r.json())


async def test_mark_all_read(auth_client):
    for _ in range(3):
        await auth_client.post(
            "/api/notifications",
            json={"title": "T", "body": "", "trigger_at": datetime.now(timezone.utc).isoformat()},
        )
    r = await auth_client.post("/api/notifications/read-all")
    assert r.status_code == 204
    r = await auth_client.get("/api/notifications?scope=all")
    assert all(n["read_at"] is not None for n in r.json())


async def test_кнопка_в_телеграме_ведёт_к_месту_в_заметке(db_session, test_user, monkeypatch):
    """Напоминание о сроке документа должно открывать заметку НА ТОМ МЕСТЕ,
    где дата. Для этого в ссылку добавляется find (document_expiry.py)."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from app import notification_dispatch, telegram_bot
    from app.models import Notification, TelegramLink

    sent: list = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text, reply_markup))

    monkeypatch.setattr(telegram_bot, "send_message", fake_send)

    from app.models import Space, SpaceMember

    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    item_id = str(_uuid.uuid4())
    db_session.add(TelegramLink(user_id=test_user.id, chat_id=424242, space_id=space.id))
    notification = Notification(
        user_id=test_user.id, type="document_expiry",
        title="Срок истекает 10.12.2026: Сервисная книжка", body="",
        payload={"item_id": item_id, "space_id": str(space.id), "find": "10.12.2026"},
        trigger_at=datetime.now(timezone.utc),
    )
    db_session.add(notification)
    await db_session.commit()

    await notification_dispatch._dispatch_one(notification, db_session)

    assert len(sent) == 1
    url = sent[0][2]["inline_keyboard"][0][0]["web_app"]["url"]
    assert f"?item={item_id}" in url
    assert "find=10.12.2026" in url


async def test_без_find_ссылка_как_раньше(db_session, test_user, monkeypatch):
    """У обычных напоминаний прокручивать некуда — лишнего параметра быть
    не должно."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from app import notification_dispatch, telegram_bot
    from app.models import Notification, TelegramLink

    sent: list = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(reply_markup)

    monkeypatch.setattr(telegram_bot, "send_message", fake_send)

    from app.models import Space, SpaceMember

    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(TelegramLink(user_id=test_user.id, chat_id=424243, space_id=space.id))
    notification = Notification(
        user_id=test_user.id, type="reminder", title="Полить цветы", body="",
        payload={"item_id": str(_uuid.uuid4())},
        trigger_at=datetime.now(timezone.utc),
    )
    db_session.add(notification)
    await db_session.commit()

    await notification_dispatch._dispatch_one(notification, db_session)

    assert "find=" not in sent[0]["inline_keyboard"][0][0]["web_app"]["url"]
