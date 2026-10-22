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


async def test_folder_cannot_go_into_its_own_subfolder(auth_client):
    """Иначе цикл: ни одна из папок больше не корень, обе пропадают из
    дерева. С перетаскиванием мышкой — одно неточное движение."""
    space_id = await _make_space(auth_client)
    top = (await auth_client.post("/api/folders", json={"space_id": space_id, "name": "A"})).json()["id"]
    mid = (await auth_client.post("/api/folders", json={"space_id": space_id, "name": "B", "parent_id": top})).json()["id"]
    low = (await auth_client.post("/api/folders", json={"space_id": space_id, "name": "C", "parent_id": mid})).json()["id"]

    r = await auth_client.patch(f"/api/folders/{top}", json={"parent_id": low})
    assert r.status_code == 400

    r = await auth_client.patch(f"/api/folders/{low}", json={"parent_id": None})
    assert r.status_code == 200


async def test_folder_parent_must_be_in_same_space(auth_client):
    space_a = await _make_space(auth_client)
    space_b = await _make_space(auth_client)
    r = await auth_client.post("/api/folders", json={"space_id": space_a, "name": "A"})
    folder_a = r.json()["id"]

    r = await auth_client.post("/api/folders", json={"space_id": space_b, "name": "B", "parent_id": folder_a})
    assert r.status_code == 400


async def test_move_folder_with_subtree_and_items(auth_client):
    space_a = await _make_space(auth_client)
    space_b = await _make_space(auth_client)

    r = await auth_client.post("/api/folders", json={"space_id": space_a, "name": "Parent"})
    parent_id = r.json()["id"]
    r = await auth_client.post("/api/folders", json={"space_id": space_a, "name": "Child", "parent_id": parent_id})
    child_id = r.json()["id"]

    r = await auth_client.post("/api/items", json={"space_id": space_a, "folder_id": parent_id, "title": "In parent", "content": "x"})
    item_parent = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_a, "folder_id": child_id, "title": "In child", "content": "y"})
    item_child = r.json()["id"]

    r = await auth_client.post(f"/api/folders/{parent_id}/move", json={"space_id": space_b})
    assert r.status_code == 200
    assert r.json()["space_id"] == space_b
    assert r.json()["parent_id"] is None

    r = await auth_client.get(f"/api/folders?space_id={space_b}")
    names = {f["name"] for f in r.json()}
    assert names == {"Parent", "Child"}

    r = await auth_client.get(f"/api/folders?space_id={space_a}")
    assert r.json() == []

    r = await auth_client.get(f"/api/items/{item_parent}")
    assert r.json()["space_id"] == space_b and r.json()["folder_id"] == parent_id
    r = await auth_client.get(f"/api/items/{item_child}")
    assert r.json()["space_id"] == space_b and r.json()["folder_id"] == child_id


async def test_move_folder_with_vault_rejected(auth_client):
    space_a = await _make_space(auth_client)
    r = await auth_client.post(
        "/api/spaces", json={"name": "V", "is_vault": True, "vault_salt": "s", "vault_verifier": "{}"}
    )
    vault_space = r.json()["id"]

    r = await auth_client.post("/api/folders", json={"space_id": space_a, "name": "F"})
    folder_id = r.json()["id"]

    r = await auth_client.post(f"/api/folders/{folder_id}/move", json={"space_id": vault_space})
    assert r.status_code == 400


async def test_folder_icon_set_and_clear(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "Поездки", "icon": "✈️"})
    assert r.status_code == 201 and r.json()["icon"] == "✈️"
    folder_id = r.json()["id"]

    # Переименование без icon в теле значок не трогает.
    r = await auth_client.patch(f"/api/folders/{folder_id}", json={"name": "Отпуск"})
    assert r.status_code == 200 and r.json()["icon"] == "✈️"

    r = await auth_client.patch(f"/api/folders/{folder_id}", json={"icon": "🏖️"})
    assert r.status_code == 200 and r.json()["icon"] == "🏖️"

    r = await auth_client.patch(f"/api/folders/{folder_id}", json={"icon": None})
    assert r.status_code == 200 and r.json()["icon"] is None

    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "Без значка"})
    assert r.status_code == 201 and r.json()["icon"] is None
