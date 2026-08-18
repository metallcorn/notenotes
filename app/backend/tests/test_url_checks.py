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
