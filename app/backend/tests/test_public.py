async def _make_public_note(auth_client, content="hello world"):
    r = await auth_client.post("/api/spaces", json={"name": "Pub", "is_public_pages": True})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "Public note", "content": content})
    return r.json()["id"]


async def test_public_view_without_password(auth_client, client):
    item_id = await _make_public_note(auth_client)
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": False})
    token = r.json()["share_token"]

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 200
    assert r.json()["title"] == "Public note"


async def test_public_unknown_token_404(client):
    r = await client.get("/api/public/does-not-exist")
    assert r.status_code == 404


async def test_public_password_flow(auth_client, client):
    item_id = await _make_public_note(auth_client)
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"password": "sekret123", "single_use": False})
    token = r.json()["share_token"]

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 200
    assert r.json() == {"requires_password": True}

    r = await client.post(f"/api/public/{token}/unlock", json={"password": "wrong"})
    assert r.status_code == 401

    r = await client.post(f"/api/public/{token}/unlock", json={"password": "sekret123"})
    assert r.status_code == 200
    assert r.json()["title"] == "Public note"


async def test_public_single_use_blocks_second_view(auth_client, client):
    item_id = await _make_public_note(auth_client)
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": True})
    token = r.json()["share_token"]

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 200

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 404


async def test_public_upload_requires_reference_in_content(auth_client, client):
    item_id = await _make_public_note(auth_client, content="text ![](/api/uploads/00000000-0000-0000-0000-000000000000)")
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": False})
    token = r.json()["share_token"]

    # не встречается в content этой заметки — 404, даже с валидным токеном
    r = await client.get(f"/api/public/{token}/uploads/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 404


async def test_unshare_invalidates_old_token(auth_client, client):
    item_id = await _make_public_note(auth_client)
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": False})
    token = r.json()["share_token"]

    r = await auth_client.post(f"/api/items/{item_id}/unshare")
    assert r.status_code == 200

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 404
