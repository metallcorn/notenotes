from datetime import datetime, timedelta, timezone

from app.models import InviteCode


async def test_register_requires_valid_invite_code(client):
    r = await client.post(
        "/api/auth/register",
        json={"username": "newuser1", "password": "password123", "name": "New User", "invite_code": "bogus"},
    )
    assert r.status_code == 403


async def test_register_login_me_flow(client, db_session, test_user):
    invite = InviteCode(
        code="TESTCODE1",
        created_by_id=test_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(invite)
    await db_session.flush()
    await db_session.commit()

    r = await client.post(
        "/api/auth/register",
        json={"username": "newuser2", "password": "password123", "name": "New User 2", "invite_code": "TESTCODE1"},
    )
    assert r.status_code == 201

    # тот же код второй раз — уже использован
    r = await client.post(
        "/api/auth/register",
        json={"username": "newuser3", "password": "password123", "name": "X", "invite_code": "TESTCODE1"},
    )
    assert r.status_code == 403

    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "newuser2"  # сессионная кука уже выставлена регистрацией

    r = await client.post("/api/auth/logout")
    assert r.status_code == 204

    r = await client.get("/api/auth/me")
    assert r.status_code == 401

    r = await client.post("/api/auth/login", json={"username": "newuser2", "password": "password123"})
    assert r.status_code == 200

    r = await client.post("/api/auth/login", json={"username": "newuser2", "password": "wrong"})
    assert r.status_code == 401


async def test_me_requires_session(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
