import uuid

from app.tools.registry import ToolContext
from app.tools.url_check import insert_url_check_block


async def _second_user_client(_client_factory, db_session):
    from app.models import User
    from app.security import create_session_token, hash_password

    other = User(username="url_check_outsider", password_hash=hash_password("x"), name="Outsider")
    db_session.add(other)
    await db_session.flush()
    c = _client_factory()
    c.cookies.set("notenotes_session", create_session_token(other.id))
    return c


async def _make_widget(auth_client, db_session, test_user, headers=None):
    r = await auth_client.post("/api/spaces", json={"name": "Space"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": ""})
    item_id = r.json()["id"]

    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    args = {
        "item_id": item_id,
        "url": "http://127.0.0.1:8000/",  # SSRF-заблокирован, детерминированно, без реальной сети
        "fields": [{"path": "$.x", "label": "X"}],
    }
    if headers:
        args["headers"] = headers
    await insert_url_check_block(ctx, args)

    r = await auth_client.get(f"/api/items/{item_id}")
    content = r.json()["content"]
    widget_id = content.split('data-url-check-id="')[1].split('"')[0]
    return item_id, widget_id


async def test_insert_url_check_block_stores_only_id_in_content(auth_client, db_session, test_user):
    # Реальный найденный риск первой версии фичи: url/поля/заголовки/
    # результат лежали прямо в content. Теперь там только непрозрачный id.
    item_id, widget_id = await _make_widget(auth_client, db_session, test_user, headers={"Cookie": "session=abc123"})
    r = await auth_client.get(f"/api/items/{item_id}")
    content = r.json()["content"]
    assert "session=abc123" not in content
    assert "data-fields=" not in content
    assert "data-last-result=" not in content
    assert "data-headers=" not in content
    assert widget_id in content


async def test_get_url_check_widget_never_leaks_headers(auth_client, db_session, test_user):
    _, widget_id = await _make_widget(auth_client, db_session, test_user, headers={"Cookie": "session=abc123"})
    r = await auth_client.get(f"/api/url-checks/{widget_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["has_credentials"] is True
    assert "session=abc123" not in r.text
    assert "headers" not in body


async def test_get_url_check_widget_requires_space_access(auth_client, _client_factory, db_session, test_user):
    _, widget_id = await _make_widget(auth_client, db_session, test_user)
    outsider = await _second_user_client(_client_factory, db_session)
    r = await outsider.get(f"/api/url-checks/{widget_id}")
    assert r.status_code == 404


async def test_refresh_requires_space_access(auth_client, _client_factory, db_session, test_user):
    _, widget_id = await _make_widget(auth_client, db_session, test_user)
    outsider = await _second_user_client(_client_factory, db_session)
    r = await outsider.post(f"/api/url-checks/{widget_id}/refresh")
    assert r.status_code == 404


async def test_refresh_does_not_touch_item_content_or_version_history(auth_client, db_session, test_user):
    # Главный смысл переноса состояния из content: "Обновить" больше не
    # создаёт новую версию заметки с целиком телом ответа внутри.
    item_id, widget_id = await _make_widget(auth_client, db_session, test_user)
    r = await auth_client.get(f"/api/items/{item_id}")
    content_before = r.json()["content"]
    versions_before = (await auth_client.get(f"/api/items/{item_id}/versions")).json()

    r = await auth_client.post(f"/api/url-checks/{widget_id}/refresh")
    assert r.status_code == 200

    r = await auth_client.get(f"/api/items/{item_id}")
    assert r.json()["content"] == content_before
    versions_after = (await auth_client.get(f"/api/items/{item_id}/versions")).json()
    assert len(versions_after) == len(versions_before)


def test_build_request_headers_merges_and_keeps_default_user_agent():
    from app.url_check import _build_request_headers

    result = _build_request_headers({"Cookie": "session=abc123", "Authorization": "Bearer x"})
    assert result["Cookie"] == "session=abc123"
    assert result["Authorization"] == "Bearer x"
    assert result["User-Agent"] == "Notenotesbot-url-check/1.0"


def test_build_request_headers_strips_host_case_insensitive():
    from app.url_check import _build_request_headers

    result = _build_request_headers({"Host": "evil.example", "hOsT": "also-evil"})
    assert "Host" not in result
    assert "hOsT" not in result


def test_build_request_headers_none_returns_only_default():
    from app.url_check import _build_request_headers

    assert _build_request_headers(None) == {"User-Agent": "Notenotesbot-url-check/1.0"}
