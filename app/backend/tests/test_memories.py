async def test_memory_crud(auth_client):
    r = await auth_client.post("/api/memories", json={"content": "Любит кофе без сахара"})
    assert r.status_code == 201
    memory_id = r.json()["id"]

    r = await auth_client.get("/api/memories")
    assert r.status_code == 200 and any(m["id"] == memory_id for m in r.json())

    r = await auth_client.delete(f"/api/memories/{memory_id}")
    assert r.status_code == 204

    r = await auth_client.get("/api/memories")
    assert not any(m["id"] == memory_id for m in r.json())


async def test_memory_empty_content_rejected(auth_client):
    r = await auth_client.post("/api/memories", json={"content": "   "})
    assert r.status_code == 400


async def test_memory_delete_foreign_rejected(auth_client, client, db_session):
    from app.models import User
    from app.security import create_session_token, hash_password

    other = User(username="mem_other", password_hash=hash_password("x"), name="Other")
    db_session.add(other)
    await db_session.flush()

    r = await auth_client.post("/api/memories", json={"content": "secret"})
    memory_id = r.json()["id"]

    client.cookies.set("notenotes_session", create_session_token(other.id))
    r = await client.delete(f"/api/memories/{memory_id}")
    assert r.status_code == 404
