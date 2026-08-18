import y_py as Y
import websockets

from app.security import create_session_token


def _cookie_header(user_id) -> list[tuple[str, str]]:
    return [("Cookie", f"notenotes_session={create_session_token(user_id)}")]


async def test_space_ws_rejects_missing_session(live_server, auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "WS space"})
    space_id = r.json()["id"]

    uri = f"{live_server}/api/spaces/{space_id}/ws"
    try:
        async with websockets.connect(uri) as ws:
            await ws.recv()
        assert False, "ожидали закрытие соединения без сессии"
    except websockets.exceptions.ConnectionClosedError as e:
        assert e.code == 4401


async def test_space_ws_receives_items_signal(live_server, auth_client, test_user):
    r = await auth_client.post("/api/spaces", json={"name": "WS space 2"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    uri = f"{live_server}/api/spaces/{space_id}/ws"
    async with websockets.connect(uri, extra_headers=_cookie_header(test_user.id)) as ws:
        await auth_client.patch(f"/api/items/{item_id}", json={"content": "updated"})
        msg = await ws.recv()
        assert '"kind":"items"' in msg or '"kind": "items"' in msg


async def test_notifications_ws_rejects_missing_session(live_server):
    uri = f"{live_server}/api/notifications/ws"
    try:
        async with websockets.connect(uri) as ws:
            await ws.recv()
        assert False, "ожидали закрытие соединения без сессии"
    except websockets.exceptions.ConnectionClosedError as e:
        assert e.code == 4401


async def test_list_ws_broadcasts_entry_change(live_server, auth_client, test_user):
    r = await auth_client.post("/api/spaces", json={"name": "WS list space"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/lists", json={"space_id": space_id, "title": "L"})
    list_id = r.json()["id"]

    uri = f"{live_server}/api/lists/{list_id}/ws"
    async with websockets.connect(uri, extra_headers=_cookie_header(test_user.id)) as ws:
        await auth_client.post(f"/api/lists/{list_id}/entries", json={"text": "Milk"})
        msg = await ws.recv()
        assert "Milk" in msg


async def test_collab_ws_seed_and_sync_between_two_clients(live_server, auth_client, test_user):
    r = await auth_client.post("/api/spaces", json={"name": "WS collab space"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "hello"})
    item_id = r.json()["id"]

    uri = f"{live_server}/api/items/{item_id}/collab"
    headers = _cookie_header(test_user.id)

    async with websockets.connect(uri, extra_headers=headers) as ws1:
        msg1 = await ws1.recv()
        assert msg1[0] == 3  # MSG_SEED_REQUEST

        doc = Y.YDoc()
        with doc.begin_transaction() as txn:
            doc.get_text("content").extend(txn, "seeded content")
        await ws1.send(bytes([1]) + Y.encode_state_as_update(doc))

        async with websockets.connect(uri, extra_headers=headers) as ws2:
            msg2 = await ws2.recv()
            assert msg2[0] == 1  # MSG_UPDATE — состояние комнаты
            doc2 = Y.YDoc()
            Y.apply_update(doc2, msg2[1:])
            assert str(doc2.get_text("content")) == "seeded content"


async def test_collab_ws_rejects_vault_space(live_server, auth_client, test_user):
    r = await auth_client.post(
        "/api/spaces", json={"name": "WS vault", "is_vault": True, "vault_salt": "s", "vault_verifier": "v"}
    )
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "x"})
    item_id = r.json()["id"]

    uri = f"{live_server}/api/items/{item_id}/collab"
    try:
        async with websockets.connect(uri, extra_headers=_cookie_header(test_user.id)) as ws:
            await ws.recv()
        assert False, "ожидали закрытие соединения для сейфа"
    except websockets.exceptions.ConnectionClosedError as e:
        assert e.code == 4400
