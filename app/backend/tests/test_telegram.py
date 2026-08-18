async def test_status_not_linked_by_default(auth_client):
    r = await auth_client.get("/api/telegram/status")
    assert r.status_code == 200 and r.json() == {"linked": False}


async def test_create_link_code(auth_client):
    r = await auth_client.post("/api/telegram/link-code")
    assert r.status_code == 200
    body = r.json()
    assert body["deep_link"].startswith("https://t.me/")
    assert "expires_at" in body


async def test_unlink_when_not_linked_is_noop(auth_client):
    r = await auth_client.delete("/api/telegram/link")
    assert r.status_code == 200 and r.json() == {"linked": False}


async def test_link_status_reflects_real_link(auth_client, db_session, test_user):
    from app.models import Space, SpaceMember, TelegramLink

    space = Space(name="Telegram", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(TelegramLink(user_id=test_user.id, chat_id=123456789, space_id=space.id))
    await db_session.commit()

    r = await auth_client.get("/api/telegram/status")
    assert r.json() == {"linked": True}

    r = await auth_client.delete("/api/telegram/link")
    assert r.status_code == 200 and r.json() == {"linked": False}
