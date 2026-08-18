async def test_link_preview_blocks_loopback(auth_client):
    """_SSRFBlocked (app/link_preview.py) резолвит хост сам и отказывает
    ДО любого сетевого запроса — тест не делает реальных обращений в сеть,
    только проверяет, что private/loopback адрес не пропускается."""
    r = await auth_client.get("/api/link-preview", params={"url": "http://127.0.0.1/secret"})
    assert r.status_code == 200
    assert r.json()["fetch_failed"] is True


async def test_link_preview_blocks_metadata_endpoint(auth_client):
    r = await auth_client.get("/api/link-preview", params={"url": "http://169.254.169.254/latest/meta-data/"})
    assert r.status_code == 200
    assert r.json()["fetch_failed"] is True


async def test_link_preview_rejects_empty_url(auth_client):
    r = await auth_client.get("/api/link-preview", params={"url": "  "})
    assert r.status_code == 400


async def test_link_preview_rejects_too_long_url(auth_client):
    r = await auth_client.get("/api/link-preview", params={"url": "http://example.com/" + "x" * 2000})
    assert r.status_code == 400


async def test_link_preview_caches_by_url(auth_client, db_session):
    from app.models import LinkPreview

    db_session.add(LinkPreview(url="https://cached.example/page", title="Cached title", fetch_failed=False))
    await db_session.flush()
    await db_session.commit()

    r = await auth_client.get("/api/link-preview", params={"url": "https://cached.example/page"})
    assert r.status_code == 200
    assert r.json()["title"] == "Cached title"
