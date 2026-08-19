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


async def test_permanent_delete_cleans_up_notifications(auth_client):
    from datetime import datetime, timezone

    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    trigger_at = datetime.now(timezone.utc).isoformat()
    r = await auth_client.post(
        "/api/notifications", json={"title": "T", "body": "", "trigger_at": trigger_at, "item_id": item_id}
    )
    assert r.status_code == 201
    notif_id = r.json()["id"]

    await auth_client.delete(f"/api/items/{item_id}")  # в корзину
    r = await auth_client.delete(f"/api/items/{item_id}/permanent")
    assert r.status_code == 204

    r = await auth_client.get("/api/notifications?scope=all")
    assert not any(n["id"] == notif_id for n in r.json())  # висящее уведомление на удалённый item — реальная жалоба


async def test_move_item_between_spaces(auth_client):
    space_a = await _make_space(auth_client, name="A")
    space_b = await _make_space(auth_client, name="B")
    r = await auth_client.post("/api/items", json={"space_id": space_a, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    r = await auth_client.post(f"/api/items/{item_id}/move", json={"space_id": space_b})
    assert r.status_code == 200
    assert r.json()["space_id"] == space_b


async def test_move_item_into_folder_of_target_space_in_one_step(auth_client):
    # Реальная жалоба: раньше move всегда сбрасывал в корень целевого
    # спейса, раскладывать по папке приходилось отдельным шагом ПОСЛЕ
    # переноса — теперь можно одним действием (см. MoveItemModal).
    space_a = await _make_space(auth_client, name="A")
    space_b = await _make_space(auth_client, name="B")
    folder_id = (await auth_client.post("/api/folders", json={"space_id": space_b, "name": "Концерты"})).json()["id"]
    item_id = (
        await auth_client.post("/api/items", json={"space_id": space_a, "title": "T", "content": "x"})
    ).json()["id"]

    r = await auth_client.post(f"/api/items/{item_id}/move", json={"space_id": space_b, "folder_id": folder_id})
    assert r.status_code == 200
    assert r.json()["space_id"] == space_b
    assert r.json()["folder_id"] == folder_id


async def test_move_item_into_folder_of_same_space(auth_client):
    # Реальный найденный баг: ранний return на "space_id == item.space_id"
    # молча игнорировал folder_id — клик по вложенной папке ТЕКУЩЕГО спейса
    # в MoveItemModal ничего не делал ("visually correct, but doesn't work").
    space_a = await _make_space(auth_client, name="A")
    folder_id = (await auth_client.post("/api/folders", json={"space_id": space_a, "name": "Концерты"})).json()["id"]
    item_id = (
        await auth_client.post("/api/items", json={"space_id": space_a, "title": "T", "content": "x"})
    ).json()["id"]

    r = await auth_client.post(f"/api/items/{item_id}/move", json={"space_id": space_a, "folder_id": folder_id})
    assert r.status_code == 200
    assert r.json()["space_id"] == space_a
    assert r.json()["folder_id"] == folder_id


async def test_move_item_rejects_folder_from_wrong_space(auth_client):
    space_a = await _make_space(auth_client, name="A")
    space_b = await _make_space(auth_client, name="B")
    foreign_folder_id = (await auth_client.post("/api/folders", json={"space_id": space_a, "name": "Чужая"})).json()["id"]
    item_id = (
        await auth_client.post("/api/items", json={"space_id": space_a, "title": "T", "content": "x"})
    ).json()["id"]

    r = await auth_client.post(
        f"/api/items/{item_id}/move", json={"space_id": space_b, "folder_id": foreign_folder_id}
    )
    assert r.status_code == 400


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


async def test_share_rejects_non_note_material_type(auth_client):
    pub_space = await _make_space(auth_client, is_public_pages=True)
    r = await auth_client.post("/api/lists", json={"space_id": pub_space, "title": "L"})
    list_id = r.json()["id"]
    r = await auth_client.post(f"/api/items/{list_id}/share", json={})
    assert r.status_code == 400


async def test_list_items_by_space_and_folder(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "F"})
    folder_id = r.json()["id"]

    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "Root item", "content": "x"})
    root_item = r.json()["id"]
    r = await auth_client.post(
        "/api/items", json={"space_id": space_id, "folder_id": folder_id, "title": "In folder", "content": "x"}
    )
    foldered_item = r.json()["id"]

    r = await auth_client.get(f"/api/items?space_id={space_id}")
    assert r.status_code == 200
    ids = {i["id"] for i in r.json()}
    assert {root_item, foldered_item} <= ids

    r = await auth_client.get(f"/api/items?space_id={space_id}&folder_id=root")
    ids = {i["id"] for i in r.json()}
    assert root_item in ids and foldered_item not in ids

    r = await auth_client.get(f"/api/items?space_id={space_id}&folder_id={folder_id}")
    ids = {i["id"] for i in r.json()}
    assert foldered_item in ids and root_item not in ids


async def test_list_items_requires_space_or_tag(auth_client):
    r = await auth_client.get("/api/items")
    assert r.status_code == 400


async def test_list_items_by_tag_is_cross_space(auth_client):
    space_a = await _make_space(auth_client, name="A")
    space_b = await _make_space(auth_client, name="B")
    r = await auth_client.post("/api/tags", json={"name": "shared-tag"})
    tag_id = r.json()["id"]

    r = await auth_client.post("/api/items", json={"space_id": space_a, "title": "In A", "content": "x"})
    item_a = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_b, "title": "In B", "content": "x"})
    item_b = r.json()["id"]
    await auth_client.post(f"/api/items/{item_a}/tags/{tag_id}")
    await auth_client.post(f"/api/items/{item_b}/tags/{tag_id}")

    r = await auth_client.get(f"/api/items?tag_id={tag_id}")
    ids = {i["id"] for i in r.json()}
    assert {item_a, item_b} <= ids


async def test_recent_items(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "Recent", "content": "x"})
    item_id = r.json()["id"]

    r = await auth_client.get("/api/items/recent")
    assert r.status_code == 200
    assert any(i["id"] == item_id for i in r.json())


async def test_add_and_remove_tag_on_item(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]
    r = await auth_client.post("/api/tags", json={"name": "important"})
    tag_id = r.json()["id"]

    r = await auth_client.post(f"/api/items/{item_id}/tags/{tag_id}")
    assert r.status_code == 200
    assert any(t["id"] == tag_id for t in r.json()["tags"])

    r = await auth_client.delete(f"/api/items/{item_id}/tags/{tag_id}")
    assert r.status_code == 200
    assert not any(t["id"] == tag_id for t in r.json()["tags"])


async def test_revert_version_restores_old_content(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "original"})
    item_id = r.json()["id"]
    await auth_client.patch(f"/api/items/{item_id}", json={"content": "changed"})

    r = await auth_client.get(f"/api/items/{item_id}/versions")
    version_id = r.json()[0]["id"]  # снэпшот "original" (состояние до правки)

    r = await auth_client.post(f"/api/items/{item_id}/versions/{version_id}/revert")
    assert r.status_code == 200
    assert r.json()["content"] == "original"

    # сам revert тоже создал новую версию (снэпшот "changed" до отката)
    r = await auth_client.get(f"/api/items/{item_id}/versions")
    assert len(r.json()) == 2


async def test_detected_events_list_and_dismiss(auth_client, db_session):
    import uuid
    from datetime import datetime, timedelta, timezone

    from app.models import Item

    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "Note", "content": "x"})
    item_id = r.json()["id"]

    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    item = await db_session.get(Item, uuid.UUID(item_id))
    item.properties = {**item.properties, "detected_events": [{"at": future, "title": "Встреча"}]}
    await db_session.commit()

    r = await auth_client.get("/api/items/detected-events")
    assert r.status_code == 200
    assert any(e["item_id"] == item_id and e["event_title"] == "Встреча" for e in r.json())

    r = await auth_client.post(f"/api/items/{item_id}/detected-events/dismiss", json={"event_at": future, "event_title": "Встреча"})
    assert r.status_code == 204

    r = await auth_client.get("/api/items/detected-events")
    assert not any(e["item_id"] == item_id for e in r.json())
