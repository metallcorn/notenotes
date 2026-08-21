import uuid

from sqlalchemy import select

from app.models import UrlCheckWidget
from app.tools.registry import ToolContext
from app.tools.url_check import insert_url_check_block, serialize_url_check
from app.tools.url_check import test_url_request as call_test_url_request


async def _make_space(auth_client, **kwargs):
    r = await auth_client.post("/api/spaces", json={"name": "Space", **kwargs})
    assert r.status_code == 201
    return r.json()["id"]


def test_serialize_url_check_is_only_an_opaque_reference():
    block = serialize_url_check("some-id")
    assert block == '<div data-url-check data-url-check-id="some-id"></div>'


async def test_test_url_request_accepts_headers_without_persisting(auth_client, db_session, test_user):
    # test_url_request — разовая проверка, ничего не создаёт и не пишет в
    # БД (в отличие от insert_url_check_block ниже, который заводит
    # постоянный UrlCheckWidget).
    space_id = await _make_space(auth_client)
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    result = await call_test_url_request(ctx, {"url": "http://127.0.0.1:8000/", "headers": {"Cookie": "session=abc"}})
    assert result.get("error") is not None  # loopback заблокирован — детерминированно, без реальной сети


async def test_insert_url_check_block_creates_widget_row_with_headers(auth_client, db_session, test_user):
    # Реальная жалоба на первую версию фичи: заголовки лежали открытым
    # текстом прямо в content. Теперь — отдельная строка, в content только
    # ссылка на неё (см. test_url_checks.py про сам content).
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

    widget = (
        await db_session.execute(select(UrlCheckWidget).where(UrlCheckWidget.item_id == uuid.UUID(item_id)))
    ).scalar_one()
    assert widget.url == "http://127.0.0.1:8000/"
    assert widget.fields == [{"path": "$.x", "label": "X"}]
    assert widget.headers == {"Cookie": "session=abc123"}


async def test_insert_url_check_block_without_headers_leaves_widget_headers_null(auth_client, db_session, test_user):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": ""})
    item_id = r.json()["id"]

    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    await insert_url_check_block(
        ctx,
        {"item_id": item_id, "url": "http://127.0.0.1:8000/", "fields": [{"path": "$.x", "label": "X"}]},
    )

    widget = (
        await db_session.execute(select(UrlCheckWidget).where(UrlCheckWidget.item_id == uuid.UUID(item_id)))
    ).scalar_one()
    assert widget.headers is None
