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


async def test_update_me_settings(auth_client):
    r = await auth_client.patch(
        "/api/auth/me",
        json={"custom_instructions": "Пиши коротко", "auto_process_uploads": False, "tts_voice": "default_high"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["custom_instructions"] == "Пиши коротко"
    assert body["auto_process_uploads"] is False
    assert body["tts_voice"] == "default_high"


async def test_update_me_rejects_unknown_llm_provider(auth_client):
    r = await auth_client.patch("/api/auth/me", json={"llm_provider": "not-a-real-provider"})
    assert r.status_code == 400


async def test_invite_code_create_and_list_scoped_to_creator(auth_client, _client_factory, db_session):
    from app.models import User
    from app.security import create_session_token, hash_password

    r = await auth_client.post("/api/auth/invite-codes")
    assert r.status_code == 201
    assert r.json()["used_at"] is None

    r = await auth_client.get("/api/auth/invite-codes")
    assert r.status_code == 200 and len(r.json()) == 1

    other = User(username="invite_other", password_hash=hash_password("x"), name="Other")
    db_session.add(other)
    await db_session.flush()
    other_client = _client_factory()
    other_client.cookies.set("notenotes_session", create_session_token(other.id))

    # список кодов — только свои, не чужие
    r = await other_client.get("/api/auth/invite-codes")
    assert r.status_code == 200 and r.json() == []


async def test_login_rate_limited_after_repeated_failures(client, test_user):
    headers = {"x-forwarded-for": "10.1.2.3"}  # уникальный fake-IP — не делить счётчик с другими тестами
    for _ in range(5):
        r = await client.post(
            "/api/auth/login", json={"username": test_user.username, "password": "wrong"}, headers=headers
        )
        assert r.status_code == 401

    r = await client.post(
        "/api/auth/login", json={"username": test_user.username, "password": "wrong"}, headers=headers
    )
    assert r.status_code == 429

    # даже с ВЕРНЫМ паролем — заблокировано по IP, не по логину
    r = await client.post(
        "/api/auth/login", json={"username": test_user.username, "password": "testpass123"}, headers=headers
    )
    assert r.status_code == 429
