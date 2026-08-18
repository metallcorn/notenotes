import pytest


async def test_create_space_and_list(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Test space"})
    assert r.status_code == 201
    space_id = r.json()["id"]

    r = await auth_client.get("/api/spaces")
    assert r.status_code == 200
    assert any(s["id"] == space_id for s in r.json())


async def test_vault_requires_salt_and_verifier(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Vault", "is_vault": True})
    assert r.status_code == 400

    r = await auth_client.post(
        "/api/spaces", json={"name": "Vault", "is_vault": True, "vault_salt": "s", "vault_verifier": "{}"}
    )
    assert r.status_code == 201
    assert r.json()["is_vault"] is True


async def test_vault_and_public_pages_are_mutually_exclusive(auth_client):
    r = await auth_client.post(
        "/api/spaces",
        json={
            "name": "Conflict",
            "is_vault": True,
            "vault_salt": "s",
            "vault_verifier": "{}",
            "is_public_pages": True,
        },
    )
    assert r.status_code == 400


async def test_space_members_and_invite_flow(auth_client, client, db_session):
    from app.models import User
    from app.security import hash_password

    other = User(username="other_user", password_hash=hash_password("x"), name="Other")
    db_session.add(other)
    await db_session.flush()

    r = await auth_client.post("/api/spaces", json={"name": "Shared"})
    space_id = r.json()["id"]

    r = await auth_client.post(f"/api/spaces/{space_id}/members", json={"username": "other_user"})
    assert r.status_code == 201
    assert r.json()["username"] == "other_user"

    # уже участник — конфликт
    r = await auth_client.post(f"/api/spaces/{space_id}/members", json={"username": "other_user"})
    assert r.status_code == 409

    r = await auth_client.get(f"/api/spaces/{space_id}/members")
    assert len(r.json()) == 2

    r = await auth_client.delete(f"/api/spaces/{space_id}/members/{other.id}")
    assert r.status_code == 204

    r = await auth_client.post(f"/api/spaces/{space_id}/invites")
    assert r.status_code == 201
    invite = r.json()

    r = await auth_client.get(f"/api/spaces/{space_id}/invites")
    assert len(r.json()) == 1

    r = await auth_client.delete(f"/api/spaces/{space_id}/invites/{invite['id']}")
    assert r.status_code == 204

    r = await auth_client.post(f"/api/spaces/invites/{invite['token']}/accept")
    assert r.status_code == 404  # уже отозвана
