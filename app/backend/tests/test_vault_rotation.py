async def test_rotate_vault_password_updates_salt_and_item_vault_blobs(auth_client):
    r = await auth_client.post(
        "/api/spaces", json={"name": "Vault", "is_vault": True, "vault_salt": "old-salt", "vault_verifier": "old-verifier"}
    )
    space_id = r.json()["id"]

    r = await auth_client.post(
        "/api/items",
        json={"space_id": space_id, "title": "🔒 Зашифровано", "content": "🔒 Зашифровано", "vault": {"title": {"iv": "a", "ciphertext": "b"}}},
    )
    item_id = r.json()["id"]

    r = await auth_client.post(
        f"/api/spaces/{space_id}/vault-rotate-password",
        json={
            "new_salt": "new-salt",
            "new_verifier": "new-verifier",
            "items": [{"id": item_id, "vault": {"title": {"iv": "c", "ciphertext": "d"}}}],
            "upload_ids": [],
        },
    )
    assert r.status_code == 200
    assert r.json()["id"] == space_id

    r = await auth_client.get(f"/api/spaces/{space_id}/vault-unlock-info")
    assert r.status_code == 200
    assert r.json() == {"vault_salt": "new-salt", "vault_verifier": "new-verifier"}

    r = await auth_client.get(f"/api/items/{item_id}")
    assert r.json()["vault"]["title"]["ciphertext"] == "d"


async def test_rotate_vault_password_rejects_non_vault_space(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Normal"})
    space_id = r.json()["id"]
    r = await auth_client.post(
        f"/api/spaces/{space_id}/vault-rotate-password",
        json={"new_salt": "s", "new_verifier": "v", "items": [], "upload_ids": []},
    )
    assert r.status_code == 404


async def test_rotate_vault_password_rejects_item_outside_space(auth_client):
    r = await auth_client.post(
        "/api/spaces", json={"name": "Vault2", "is_vault": True, "vault_salt": "s", "vault_verifier": "v"}
    )
    space_id = r.json()["id"]
    r = await auth_client.post("/api/spaces", json={"name": "Other"})
    other_space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": other_space_id, "title": "T", "content": "x"})
    foreign_item_id = r.json()["id"]

    r = await auth_client.post(
        f"/api/spaces/{space_id}/vault-rotate-password",
        json={
            "new_salt": "s2",
            "new_verifier": "v2",
            "items": [{"id": foreign_item_id, "vault": {}}],
            "upload_ids": [],
        },
    )
    assert r.status_code == 400
