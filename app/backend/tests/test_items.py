async def _make_space(auth_client, **kwargs):
    r = await auth_client.post("/api/spaces", json={"name": "Space", **kwargs})
    assert r.status_code == 201
    return r.json()["id"]


async def test_item_crud_and_versions(auth_client):
    space_id = await _make_space(auth_client)

    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T1", "content": "hello"})
    assert r.status_code == 201
    item_id = r.json()["id"]

    r = await auth_client.get(f"/api/items/{item_id}")
    assert r.status_code == 200 and r.json()["content"] == "hello"

    r = await auth_client.patch(f"/api/items/{item_id}", json={"content": "updated"})
    assert r.status_code == 200 and r.json()["content"] == "updated"

    r = await auth_client.get(f"/api/items/{item_id}/versions")
    assert r.status_code == 200 and len(r.json()) == 1
    assert r.json()[0]["content"] == "hello"  # снэпшот — состояние ДО правки


async def test_item_soft_delete_and_restore(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    r = await auth_client.delete(f"/api/items/{item_id}")
    assert r.status_code == 204

    r = await auth_client.get(f"/api/items/{item_id}")
    assert r.status_code == 404  # мягко удалена — недоступна обычным путём

    r = await auth_client.get("/api/items/trash/list", params={"space_id": space_id})
    assert r.status_code == 200 and any(i["id"] == item_id for i in r.json())

    r = await auth_client.post(f"/api/items/{item_id}/restore")
    assert r.status_code == 200

    r = await auth_client.get(f"/api/items/{item_id}")
    assert r.status_code == 200


async def test_move_item_between_spaces(auth_client):
    space_a = await _make_space(auth_client, name="A")
    space_b = await _make_space(auth_client, name="B")
    r = await auth_client.post("/api/items", json={"space_id": space_a, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    r = await auth_client.post(f"/api/items/{item_id}/move", json={"space_id": space_b})
    assert r.status_code == 200
    assert r.json()["space_id"] == space_b


async def test_share_requires_note_in_public_pages_space(auth_client):
    normal_space = await _make_space(auth_client, name="Normal")
    pub_space = await _make_space(auth_client, name="Pub", is_public_pages=True)

    r = await auth_client.post("/api/items", json={"space_id": normal_space, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    r = await auth_client.post(f"/api/items/{item_id}/share", json={})
    assert r.status_code == 400

    r = await auth_client.post(f"/api/items/{item_id}/move", json={"space_id": pub_space})
    assert r.status_code == 200

    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": False})
    assert r.status_code == 200
    assert r.json()["is_public"] is True
    assert r.json()["share_token"]

    r = await auth_client.post(f"/api/items/{item_id}/unshare")
    assert r.status_code == 200
    assert r.json()["is_public"] is False
    assert r.json()["share_token"] is None
