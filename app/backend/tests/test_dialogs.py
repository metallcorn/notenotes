"""Только детерминированная (без LLM) часть dialogs.py — создание/список/
чтение/удаление сообщений напрямую работают с БД. Собственно отправка
сообщения ассистенту (POST /{dialog_id}/messages -> run_dialog_turn) дёргает
реальный LLM-провайдер (Mistral/Gemini/Groq) — платно и недетерминированно,
сознательно не покрыта тестами (см. tests/README.md)."""
import uuid


async def _make_space(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Dialogs"})
    return r.json()["id"]


async def test_create_list_get_dialog(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id, "title": "Chat"})
    assert r.status_code == 201
    dialog_id = r.json()["id"]

    r = await auth_client.get("/api/dialogs")
    assert r.status_code == 200 and any(d["id"] == dialog_id for d in r.json())

    r = await auth_client.get(f"/api/dialogs/{dialog_id}")
    assert r.status_code == 200 and r.json()["title"] == "Chat"


async def test_dialog_not_created_in_vault_space(auth_client):
    r = await auth_client.post(
        "/api/spaces", json={"name": "V", "is_vault": True, "vault_salt": "s", "vault_verifier": "v"}
    )
    space_id = r.json()["id"]
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id})
    assert r.status_code == 404


async def test_scoped_dialog_for_item(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "Note", "content": "x"})
    item_id = r.json()["id"]

    r = await auth_client.post("/api/dialogs", json={"scoped_item_id": item_id, "selection": "some text"})
    assert r.status_code == 201
    assert "Note" in r.json()["title"]

    r = await auth_client.get(f"/api/dialogs/scoped/{item_id}")
    assert r.status_code == 200 and len(r.json()) == 1


async def test_delete_message_from_dialog(auth_client, db_session, test_user):
    from app.models import Item

    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id})
    assert r.status_code == 201, r.text
    dialog_id = r.json()["id"]

    item = await db_session.get(Item, uuid.UUID(dialog_id))
    message_id = str(uuid.uuid4())
    messages = [{"id": message_id, "role": "user", "content": "Привет"}]
    item.properties = {**item.properties, "messages": messages}
    await db_session.commit()

    r = await auth_client.delete(f"/api/dialogs/{dialog_id}/messages/{message_id}")
    assert r.status_code == 200
    assert r.json()["messages"] == []


async def test_delete_nonexistent_message_404(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id})
    assert r.status_code == 201, r.text
    dialog_id = r.json()["id"]
    r = await auth_client.delete(f"/api/dialogs/{dialog_id}/messages/{uuid.uuid4()}")
    assert r.status_code == 404
