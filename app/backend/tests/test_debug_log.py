import uuid


def _fake_ip_headers() -> dict:
    # _client_ip (routers/debug_log.py) читает X-Forwarded-For — счётчик
    # rate-limit'а модульный (переживает между тестами в одном процессе),
    # уникальный fake-IP на тест держит их независимыми друг от друга, не
    # полагаясь на порядок запуска тестов в файле.
    return {"x-forwarded-for": f"10.0.0.{uuid.uuid4().int % 250 + 1}"}


async def test_debug_log_accepts_anonymous(client):
    r = await client.post(
        "/api/debug-log", json={"event": "app_start", "data": {"ok": True}}, headers=_fake_ip_headers()
    )
    assert r.status_code == 204


async def test_debug_log_payload_too_large_rejected(client):
    r = await client.post(
        "/api/debug-log", json={"event": "x", "data": {"blob": "x" * 7000}}, headers=_fake_ip_headers()
    )
    assert r.status_code == 413


async def test_debug_log_rate_limited(client):
    headers = _fake_ip_headers()
    for _ in range(30):
        r = await client.post("/api/debug-log", json={"event": "ping", "data": {}}, headers=headers)
        assert r.status_code == 204
    r = await client.post("/api/debug-log", json={"event": "ping", "data": {}}, headers=headers)
    assert r.status_code == 429
