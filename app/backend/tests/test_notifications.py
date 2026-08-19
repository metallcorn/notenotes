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
