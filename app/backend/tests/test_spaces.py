async def test_create_space_and_list(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Test space"})
    assert r.status_code == 201
    space_id = r.json()["id"]

    r = await auth_client.get("/api/spaces")
    assert r.status_code == 200
    assert any(s["id"] == space_id for s in r.json())


async def test_delete_empty_space(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "To delete"})
    space_id = r.json()["id"]
    r = await auth_client.delete(f"/api/spaces/{space_id}")
    assert r.status_code == 204

    r = await auth_client.get("/api/spaces")
    assert not any(s["id"] == space_id for s in r.json())


async def test_delete_space_with_items_rejected(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Has items"})
    space_id = r.json()["id"]
    await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})

    r = await auth_client.delete(f"/api/spaces/{space_id}")
    assert r.status_code == 400

    r = await auth_client.get("/api/spaces")
    assert any(s["id"] == space_id for s in r.json())  # спейс никуда не делся


async def test_delete_space_with_folders_rejected(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Has folders"})
    space_id = r.json()["id"]
    await auth_client.post("/api/folders", json={"space_id": space_id, "name": "F"})

    r = await auth_client.delete(f"/api/spaces/{space_id}")
    assert r.status_code == 400


async def test_delete_space_with_soft_deleted_item_still_rejected(auth_client):
    """Мягко удалённая (в корзине) заметка — всё ещё повод отказать
    удалению спейса: её можно восстановить, каскад стёр бы безвозвратно."""
    r = await auth_client.post("/api/spaces", json={"name": "Has trashed item"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]
    await auth_client.delete(f"/api/items/{item_id}")

    r = await auth_client.delete(f"/api/spaces/{space_id}")
    assert r.status_code == 400


async def test_force_delete_space_with_items_and_uploads(auth_client):
    from datetime import datetime, timezone

    from app.routers.uploads import _upload_path

    r = await auth_client.post("/api/spaces", json={"name": "Force delete"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]
    await auth_client.post("/api/folders", json={"space_id": space_id, "name": "F"})

    r = await auth_client.post(
        f"/api/uploads?space_id={space_id}", files={"file": ("f.bin", b"hello", "application/octet-stream")}
    )
    upload_id = r.json()["id"]
    upload_path = _upload_path(upload_id)
    assert upload_path.exists()

    trigger_at = datetime.now(timezone.utc).isoformat()
    r = await auth_client.post(
        "/api/notifications", json={"title": "T", "body": "", "trigger_at": trigger_at, "item_id": item_id}
    )
    notif_id = r.json()["id"]

    # без force всё ещё отказ, ничего не подчищено
    r = await auth_client.delete(f"/api/spaces/{space_id}")
    assert r.status_code == 400

    r = await auth_client.delete(f"/api/spaces/{space_id}?force=true")
    assert r.status_code == 204

    assert not upload_path.exists()  # реальная жалоба: файлы не должны оставаться мусором на диске

    r = await auth_client.get("/api/spaces")
    assert not any(s["id"] == space_id for s in r.json())

    r = await auth_client.get("/api/notifications?scope=all")
    assert not any(n["id"] == notif_id for n in r.json())  # висящее уведомление на удалённый item


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


async def test_rename_space(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Old name"})
    space_id = r.json()["id"]
    r = await auth_client.patch(f"/api/spaces/{space_id}", json={"name": "New name"})
    assert r.status_code == 200 and r.json()["name"] == "New name"


async def test_add_member_by_unknown_username_404(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "S"})
    space_id = r.json()["id"]
    r = await auth_client.post(f"/api/spaces/{space_id}/members", json={"username": "does-not-exist"})
    assert r.status_code == 404


async def test_accept_expired_invite_rejected(auth_client, db_session, test_user):
    from datetime import datetime, timedelta, timezone

    from app.models import SpaceInvite

    r = await auth_client.post("/api/spaces", json={"name": "S"})
    space_id = r.json()["id"]
    invite = SpaceInvite(
        space_id=space_id,
        created_by_id=test_user.id,
        token="expired-token-123",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(invite)
    await db_session.commit()

    r = await auth_client.post(f"/api/spaces/invites/{invite.token}/accept")
    assert r.status_code == 404


async def test_space_icon_set_and_clear(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Дом"})
    space_id = r.json()["id"]
    assert r.json()["icon"] is None

    r = await auth_client.patch(f"/api/spaces/{space_id}", json={"icon": "🏠"})
    assert r.status_code == 200 and r.json()["icon"] == "🏠"

    # Переименование без icon в теле значок не трогает.
    r = await auth_client.patch(f"/api/spaces/{space_id}", json={"name": "Квартира"})
    assert r.json() == {**r.json(), "name": "Квартира", "icon": "🏠"}

    r = await auth_client.patch(f"/api/spaces/{space_id}", json={"icon": None})
    assert r.status_code == 200 and r.json()["icon"] is None


async def test_spaces_manual_order(auth_client):
    ids = []
    for name in ("Первый", "Второй", "Третий"):
        r = await auth_client.post("/api/spaces", json={"name": name})
        ids.append(r.json()["id"])

    r = await auth_client.put("/api/spaces/order", json={"space_ids": [ids[2], ids[0]]})
    assert r.status_code == 204

    r = await auth_client.get("/api/spaces")
    listed = [s["id"] for s in r.json() if s["id"] in ids]
    # Упорядоченные впереди в заданном порядке, неупорядоченный — после.
    assert listed == [ids[2], ids[0], ids[1]]

    # Чужой id молча пропускается, порядок остальных применяется.
    r = await auth_client.put("/api/spaces/order", json={"space_ids": ["00000000-0000-0000-0000-000000000001", ids[1]]})
    assert r.status_code == 204
    r = await auth_client.get("/api/spaces")
    listed = [s["id"] for s in r.json() if s["id"] in ids]
    assert listed[0] == ids[1]
