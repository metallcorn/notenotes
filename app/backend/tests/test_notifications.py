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
