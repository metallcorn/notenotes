async def _make_space(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Folders"})
    return r.json()["id"]


async def test_folder_crud(auth_client):
    space_id = await _make_space(auth_client)

    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "Root"})
    assert r.status_code == 201
    root_id = r.json()["id"]

    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "Child", "parent_id": root_id})
    assert r.status_code == 201
    child_id = r.json()["id"]

    r = await auth_client.get(f"/api/folders?space_id={space_id}")
    assert r.status_code == 200 and len(r.json()) == 2

    r = await auth_client.patch(f"/api/folders/{root_id}", json={"name": "Renamed"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"

    r = await auth_client.delete(f"/api/folders/{child_id}")
    assert r.status_code == 204


async def test_folder_cannot_be_its_own_parent(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "F"})
    folder_id = r.json()["id"]

    r = await auth_client.patch(f"/api/folders/{folder_id}", json={"parent_id": folder_id})
    assert r.status_code == 400


async def test_folder_parent_must_be_in_same_space(auth_client):
    space_a = await _make_space(auth_client)
    space_b = await _make_space(auth_client)
    r = await auth_client.post("/api/folders", json={"space_id": space_a, "name": "A"})
    folder_a = r.json()["id"]

    r = await auth_client.post("/api/folders", json={"space_id": space_b, "name": "B", "parent_id": folder_a})
    assert r.status_code == 400
