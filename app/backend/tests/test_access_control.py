"""Самая важная граница безопасности, которая раньше не была явно
проверена ни одним тестом: участник ДРУГОГО спейса не должен читать/
писать заметки, папки, списки и файлы в спейсе, где он не состоит.
ensure_space_access (deps.py) — общая точка проверки для всех этих
роутеров, но у каждого свой _get_accessible_item/_get_owned_folder/
_get_list_item — стоит убедиться, что все они реально её вызывают, не
только один."""
import io


async def _second_user_client(_client_factory, db_session):
    from app.models import User
    from app.security import create_session_token, hash_password

    other = User(username="outsider", password_hash=hash_password("x"), name="Outsider")
    db_session.add(other)
    await db_session.flush()
    c = _client_factory()
    c.cookies.set("notenotes_session", create_session_token(other.id))
    return c


async def test_foreign_user_cannot_read_or_write_item(auth_client, _client_factory, db_session):
    r = await auth_client.post("/api/spaces", json={"name": "Private"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "Secret", "content": "x"})
    item_id = r.json()["id"]

    outsider = await _second_user_client(_client_factory, db_session)

    r = await outsider.get(f"/api/items/{item_id}")
    assert r.status_code == 404
    r = await outsider.patch(f"/api/items/{item_id}", json={"content": "hacked"})
    assert r.status_code == 404
    r = await outsider.delete(f"/api/items/{item_id}")
    assert r.status_code == 404
    r = await outsider.get(f"/api/items/{item_id}/versions")
    assert r.status_code == 404


async def test_foreign_user_cannot_access_folder(auth_client, _client_factory, db_session):
    r = await auth_client.post("/api/spaces", json={"name": "Private2"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "F"})
    folder_id = r.json()["id"]

    outsider = await _second_user_client(_client_factory, db_session)
    r = await outsider.get(f"/api/folders?space_id={space_id}")
    assert r.status_code == 404
    r = await outsider.patch(f"/api/folders/{folder_id}", json={"name": "hacked"})
    assert r.status_code == 404
    r = await outsider.delete(f"/api/folders/{folder_id}")
    assert r.status_code == 404


async def test_foreign_user_cannot_access_list(auth_client, _client_factory, db_session):
    r = await auth_client.post("/api/spaces", json={"name": "Private3"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/lists", json={"space_id": space_id, "title": "L"})
    list_id = r.json()["id"]

    outsider = await _second_user_client(_client_factory, db_session)
    r = await outsider.get(f"/api/lists/{list_id}")
    assert r.status_code == 404
    r = await outsider.post(f"/api/lists/{list_id}/entries", json={"text": "x"})
    assert r.status_code == 404


async def test_foreign_user_cannot_access_upload(auth_client, _client_factory, db_session):
    r = await auth_client.post("/api/spaces", json={"name": "Private4"})
    space_id = r.json()["id"]
    r = await auth_client.post(
        f"/api/uploads?space_id={space_id}", files={"file": ("f.bin", b"hello", "application/octet-stream")}
    )
    upload_id = r.json()["id"]

    outsider = await _second_user_client(_client_factory, db_session)
    r = await outsider.get(f"/api/uploads/{upload_id}")
    assert r.status_code == 404
    r = await outsider.delete(f"/api/uploads/{upload_id}")
    assert r.status_code == 404


async def test_foreign_user_cannot_move_item_into_or_out_of_space(auth_client, _client_factory, db_session):
    r = await auth_client.post("/api/spaces", json={"name": "Owner space"})
    owner_space = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": owner_space, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    outsider = await _second_user_client(_client_factory, db_session)
    r = await outsider.post("/api/spaces", json={"name": "Outsider space"})
    outsider_space = r.json()["id"]

    # аутсайдер не может перенести чужую заметку вообще (нет доступа к ней)
    r = await outsider.post(f"/api/items/{item_id}/move", json={"space_id": outsider_space})
    assert r.status_code == 404

    # владелец не может перенести СВОЮ заметку в спейс, где он не состоит
    r = await auth_client.post(f"/api/items/{item_id}/move", json={"space_id": outsider_space})
    assert r.status_code == 404


async def test_space_endpoints_404_for_non_member(auth_client, _client_factory, db_session):
    r = await auth_client.post("/api/spaces", json={"name": "Owner-only"})
    space_id = r.json()["id"]

    outsider = await _second_user_client(_client_factory, db_session)
    r = await outsider.get(f"/api/spaces/{space_id}/members")
    assert r.status_code == 404
    r = await outsider.post(f"/api/spaces/{space_id}/invites")
    assert r.status_code == 404
    r = await outsider.patch(f"/api/spaces/{space_id}", json={"name": "hacked"})
    assert r.status_code == 404
