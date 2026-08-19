import uuid

import y_py as Y
import websockets

from app import collab
from app.security import create_session_token
from app.tools.notes import append_to_note, update_note
from app.tools.registry import ToolContext


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


async def test_table_ws_broadcasts_row_change(live_server, auth_client, test_user):
    r = await auth_client.post("/api/spaces", json={"name": "WS table space"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/tables", json={"space_id": space_id, "title": "T", "columns": [{"name": "A"}]})
    table_id = r.json()["id"]
    col_id = r.json()["columns"][0]["id"]

    uri = f"{live_server}/api/tables/{table_id}/ws"
    async with websockets.connect(uri, extra_headers=_cookie_header(test_user.id)) as ws:
        await auth_client.post(f"/api/tables/{table_id}/rows", json={"cells": {col_id: "Squat"}})
        msg = await ws.recv()
        assert "Squat" in msg


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


async def test_assistant_update_note_invalidates_live_collab_room(
    live_server, auth_client, test_user, db_session, monkeypatch
):
    # Реальный найденный баг (2026-08-19): заметку одновременно правили в
    # браузере (живая коллаборация) и через Telegram-ассистента — тул
    # update_note писал в item.content напрямую, в обход Yjs, не разрывая
    # комнату, и следующий же автосейв из устаревшего Yjs-состояния молча
    # затирал правку ассистента обратно. Та же причина, что была уже
    # исправлена для vision.py/pdf_processing.py/tickets.py — здесь
    # проверяем, что update_note теперь тоже зовёт collab.invalidate_room.
    # Debounce (см. collab.py) тут не нужен — тест ждёт разрыва СИНХРОННО.
    monkeypatch.setattr(collab, "_INVALIDATE_DEBOUNCE_SECONDS", 0)
    r = await auth_client.post("/api/spaces", json={"name": "WS collab assistant space"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "hello"})
    item_id = r.json()["id"]

    uri = f"{live_server}/api/items/{item_id}/collab"
    async with websockets.connect(uri, extra_headers=_cookie_header(test_user.id)) as ws:
        msg = await ws.recv()
        assert msg[0] == 3  # MSG_SEED_REQUEST — клиент уже зарегистрирован в комнате

        ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
        await update_note(ctx, {"item_id": item_id, "content": "changed via assistant"})

        try:
            await ws.recv()
            assert False, "ожидали, что правка ассистента разорвёт живую комнату"
        except websockets.exceptions.ConnectionClosedError as e:
            assert e.code == collab.INVALIDATED_CLOSE_CODE


async def test_assistant_append_to_note_invalidates_live_collab_room(
    live_server, auth_client, test_user, db_session, monkeypatch
):
    monkeypatch.setattr(collab, "_INVALIDATE_DEBOUNCE_SECONDS", 0)
    r = await auth_client.post("/api/spaces", json={"name": "WS collab assistant space 2"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "hello"})
    item_id = r.json()["id"]

    uri = f"{live_server}/api/items/{item_id}/collab"
    async with websockets.connect(uri, extra_headers=_cookie_header(test_user.id)) as ws:
        msg = await ws.recv()
        assert msg[0] == 3  # MSG_SEED_REQUEST

        ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
        await append_to_note(ctx, {"item_id": item_id, "text": "дописано ассистентом"})

        try:
            await ws.recv()
            assert False, "ожидали, что правка ассистента разорвёт живую комнату"
        except websockets.exceptions.ConnectionClosedError as e:
            assert e.code == collab.INVALIDATED_CLOSE_CODE


async def test_revert_version_invalidates_live_collab_room(live_server, auth_client, test_user, monkeypatch):
    # Реальный найденный баг: revert_version (кнопка "Восстановить" в
    # истории версий) пишет item.content НАПРЯМУЮ, в обход Yjs — тот же
    # класс, что уже был закрыт для update_note/append_to_note/
    # vision.py/pdf_processing.py/tickets.py, но сюда чинку тогда не
    # довели. Без invalidate_room восстановленная версия никогда не
    # долетала до заметки с открытой живой коллаборацией: следующий же
    # автосейв из устаревшего Y.Doc молча затирал её обратно.
    monkeypatch.setattr(collab, "_INVALIDATE_DEBOUNCE_SECONDS", 0)
    r = await auth_client.post("/api/spaces", json={"name": "WS collab revert space"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "hello"})
    item_id = r.json()["id"]
    r = await auth_client.patch(f"/api/items/{item_id}", json={"content": "changed"})
    assert r.status_code == 200
    r = await auth_client.get(f"/api/items/{item_id}/versions")
    version_id = r.json()[0]["id"]

    uri = f"{live_server}/api/items/{item_id}/collab"
    async with websockets.connect(uri, extra_headers=_cookie_header(test_user.id)) as ws:
        msg = await ws.recv()
        assert msg[0] == 3  # MSG_SEED_REQUEST — клиент уже зарегистрирован в комнате

        r = await auth_client.post(f"/api/items/{item_id}/versions/{version_id}/revert")
        assert r.status_code == 200

        try:
            await ws.recv()
            assert False, "ожидали, что откат версии разорвёт живую комнату"
        except websockets.exceptions.ConnectionClosedError as e:
            assert e.code == collab.INVALIDATED_CLOSE_CODE


async def test_insert_url_check_block_invalidates_live_collab_room(
    live_server, auth_client, test_user, db_session, monkeypatch
):
    from app.tools.url_check import insert_url_check_block

    monkeypatch.setattr(collab, "_INVALIDATE_DEBOUNCE_SECONDS", 0)
    r = await auth_client.post("/api/spaces", json={"name": "WS collab url-check space"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": "hello"})
    item_id = r.json()["id"]

    uri = f"{live_server}/api/items/{item_id}/collab"
    async with websockets.connect(uri, extra_headers=_cookie_header(test_user.id)) as ws:
        msg = await ws.recv()
        assert msg[0] == 3  # MSG_SEED_REQUEST

        ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
        # Loopback — url_check.check_url блокирует его как SSRF (see
        # test_url_checks.py) и отдаёт {"error": ...} без единого реального
        # сетевого запроса — детерминированно, нас интересует только сам
        # факт записи блока в content, не результат фетча.
        await insert_url_check_block(
            ctx,
            {"item_id": item_id, "url": "http://127.0.0.1:8000/", "fields": [{"path": "$.x", "label": "X"}]},
        )

        try:
            await ws.recv()
            assert False, "ожидали, что вставка блока проверки ссылки разорвёт живую комнату"
        except websockets.exceptions.ConnectionClosedError as e:
            assert e.code == collab.INVALIDATED_CLOSE_CODE


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
