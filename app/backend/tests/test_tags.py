async def test_tag_crud_and_duplicate_rejected(auth_client):
    r = await auth_client.post("/api/tags", json={"name": "work"})
    assert r.status_code == 201
    tag_id = r.json()["id"]

    r = await auth_client.post("/api/tags", json={"name": "work"})
    assert r.status_code == 409

    r = await auth_client.get("/api/tags")
    assert r.status_code == 200 and any(t["id"] == tag_id for t in r.json())

    r = await auth_client.patch(f"/api/tags/{tag_id}", json={"name": "renamed"})
    assert r.status_code == 200 and r.json()["name"] == "renamed"

    r = await auth_client.delete(f"/api/tags/{tag_id}")
    assert r.status_code == 204


async def test_tag_merge_moves_item_links(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "S"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    r = await auth_client.post("/api/tags", json={"name": "source"})
    source_id = r.json()["id"]
    r = await auth_client.post("/api/tags", json={"name": "target"})
    target_id = r.json()["id"]

    r = await auth_client.post(f"/api/items/{item_id}/tags/{source_id}")
    assert r.status_code == 200

    r = await auth_client.post(f"/api/tags/{source_id}/merge", json={"target_tag_id": target_id})
    assert r.status_code == 200
    assert r.json()["id"] == target_id

    r = await auth_client.get(f"/api/items/{item_id}")
    tag_ids = [t["id"] for t in r.json()["tags"]]
    assert target_id in tag_ids
    assert source_id not in tag_ids

    # исходный тег удалён после слияния
    r = await auth_client.patch(f"/api/tags/{source_id}", json={"name": "x"})
    assert r.status_code == 404


async def test_tag_merge_with_itself_rejected(auth_client):
    r = await auth_client.post("/api/tags", json={"name": "solo"})
    tag_id = r.json()["id"]
    r = await auth_client.post(f"/api/tags/{tag_id}/merge", json={"target_tag_id": tag_id})
    assert r.status_code == 400
