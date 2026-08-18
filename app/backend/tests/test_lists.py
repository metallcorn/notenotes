async def _make_space(auth_client, **kwargs):
    r = await auth_client.post("/api/spaces", json={"name": "Lists", **kwargs})
    return r.json()["id"]


async def test_list_crud_and_entries(auth_client):
    space_id = await _make_space(auth_client)

    r = await auth_client.post("/api/lists", json={"space_id": space_id, "title": "Groceries"})
    assert r.status_code == 201
    list_id = r.json()["id"]
    assert r.json()["entries"] == []

    r = await auth_client.get(f"/api/lists/{list_id}")
    assert r.status_code == 200

    r = await auth_client.post(f"/api/lists/{list_id}/entries", json={"text": "Milk"})
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 1
    entry_id = r.json()["entries"][0]["id"]
    assert r.json()["entries"][0]["checked"] is False

    r = await auth_client.patch(f"/api/lists/{list_id}/entries/{entry_id}", json={"checked": True})
    assert r.status_code == 200
    assert r.json()["entries"][0]["checked"] is True

    r = await auth_client.delete(f"/api/lists/{list_id}/entries/{entry_id}")
    assert r.status_code == 200
    assert r.json()["entries"] == []


async def test_list_empty_entry_text_rejected(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/lists", json={"space_id": space_id, "title": "L"})
    list_id = r.json()["id"]

    r = await auth_client.post(f"/api/lists/{list_id}/entries", json={"text": "   "})
    assert r.status_code == 400


async def test_list_not_supported_in_vault(auth_client):
    r = await auth_client.post(
        "/api/spaces", json={"name": "V", "is_vault": True, "vault_salt": "s", "vault_verifier": "{}"}
    )
    space_id = r.json()["id"]
    r = await auth_client.post("/api/lists", json={"space_id": space_id, "title": "L"})
    assert r.status_code == 400
