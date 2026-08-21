async def test_url_check_blocks_loopback(auth_client):
    """check_url (app/url_check.py) никогда не бросает наружу — SSRF-блок
    отдаётся как {"error": ...} с 200, не как HTTP-ошибка (тот же принцип,
    что read_website.fetch/link_preview.fetch_preview)."""
    r = await auth_client.post("/api/url-checks/fetch", json={"url": "http://127.0.0.1:8000/api/health"})
    assert r.status_code == 200
    assert r.json()["error"] is not None
    assert r.json()["status_code"] is None


async def test_url_check_blocks_private_network(auth_client):
    r = await auth_client.post("/api/url-checks/fetch", json={"url": "http://10.0.0.1/"})
    assert r.status_code == 200
    assert r.json()["error"] is not None


async def test_url_check_requires_auth(client):
    r = await client.post("/api/url-checks/fetch", json={"url": "http://127.0.0.1/"})
    assert r.status_code == 401


async def test_url_check_accepts_optional_headers(auth_client):
    # Реальный запрос: пользователь хочет проверять авторизованную ссылку
    # своим токеном/cookie (из своей команды curl) — headers опциональны,
    # запрос всё ещё SSRF-safe независимо от того, что в них передано.
    r = await auth_client.post(
        "/api/url-checks/fetch",
        json={"url": "http://127.0.0.1:8000/", "headers": {"Cookie": "session=abc123"}},
    )
    assert r.status_code == 200
    assert r.json()["error"] is not None  # loopback всё ещё заблокирован, headers это не обходят


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
