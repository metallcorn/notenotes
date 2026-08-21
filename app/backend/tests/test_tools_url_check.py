import uuid

from app.tools.registry import ToolContext
from app.tools.url_check import insert_url_check_block, serialize_url_check
from app.tools.url_check import test_url_request as call_test_url_request


async def _make_space(auth_client, **kwargs):
    r = await auth_client.post("/api/spaces", json={"name": "Space", **kwargs})
    assert r.status_code == 201
    return r.json()["id"]


def test_serialize_url_check_includes_headers_when_present():
    block = serialize_url_check("https://example.com", [], None, None, headers={"Cookie": "session=abc"})
    assert 'data-headers="' in block
    assert "session=abc" in block


def test_serialize_url_check_omits_headers_when_absent():
    block = serialize_url_check("https://example.com", [], None, None, headers=None)
    assert "data-headers" not in block


def test_serialize_url_check_omits_headers_when_empty_dict():
    block = serialize_url_check("https://example.com", [], None, None, headers={})
    assert "data-headers" not in block


async def test_test_url_request_accepts_headers_without_persisting(auth_client, db_session, test_user):
    # test_url_request — разовая проверка, ничего не создаёт и не пишет в
    # БД (реальный запрос пользователя: "разово можно, постоянно — только
    # с явным предупреждением", см. insert_url_check_block ниже).
    space_id = await _make_space(auth_client)
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    result = await call_test_url_request(ctx, {"url": "http://127.0.0.1:8000/", "headers": {"Cookie": "session=abc"}})
    assert result.get("error") is not None  # loopback заблокирован — детерминированно, без реальной сети


async def test_insert_url_check_block_stores_headers_in_note_content(auth_client, db_session, test_user):
    # Реальный запрос: постоянный виджет для авторизованной ссылки — headers
    # СОХРАНЯЮТСЯ в content (нужны кнопке "Обновить" позже), в отличие от
    # test_url_request выше.
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": ""})
    item_id = r.json()["id"]

    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    await insert_url_check_block(
        ctx,
        {
            "item_id": item_id,
            "url": "http://127.0.0.1:8000/",
            "fields": [{"path": "$.x", "label": "X"}],
            "headers": {"Cookie": "session=abc123"},
        },
    )

    r = await auth_client.get(f"/api/items/{item_id}")
    assert "data-headers" in r.json()["content"]
    assert "session=abc123" in r.json()["content"]


async def test_insert_url_check_block_without_headers_omits_data_headers(auth_client, db_session, test_user):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": ""})
    item_id = r.json()["id"]

    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    await insert_url_check_block(
        ctx,
        {"item_id": item_id, "url": "http://127.0.0.1:8000/", "fields": [{"path": "$.x", "label": "X"}]},
    )

    r = await auth_client.get(f"/api/items/{item_id}")
    assert "data-headers" not in r.json()["content"]
