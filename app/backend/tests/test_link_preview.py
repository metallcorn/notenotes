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


async def test_link_preview_retries_stale_failure(auth_client, db_session):
    # Реальная жалоба: неудачный фетч (например, сайт временно отдал
    # урезанную страницу) кэшировался как fetch_failed НАВСЕГДА — без
    # этого теста застрял бы точно так же и после устранения первопричины.
    # SSRF-блок — тот же приём, что и в остальных тестах файла: детерминированный
    # отказ без единого реального сетевого запроса.
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models import LinkPreview

    old_time = datetime.now(timezone.utc) - timedelta(hours=25)
    db_session.add(
        LinkPreview(url="http://127.0.0.1/stale-failure", title=None, fetch_failed=True, fetched_at=old_time)
    )
    await db_session.flush()
    await db_session.commit()

    r = await auth_client.get("/api/link-preview", params={"url": "http://127.0.0.1/stale-failure"})
    assert r.status_code == 200
    assert r.json()["fetch_failed"] is True  # SSRF всё ещё блокирует — само по себе не про это

    row = (
        await db_session.execute(select(LinkPreview).where(LinkPreview.url == "http://127.0.0.1/stale-failure"))
    ).scalar_one()
    assert row.fetched_at > old_time + timedelta(hours=1)  # реально попытались перефетчить, а не просто вернули кэш


async def test_link_preview_does_not_retry_recent_failure(auth_client, db_session):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models import LinkPreview

    recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(
        LinkPreview(url="http://127.0.0.1/recent-failure", title=None, fetch_failed=True, fetched_at=recent_time)
    )
    await db_session.flush()
    await db_session.commit()

    await auth_client.get("/api/link-preview", params={"url": "http://127.0.0.1/recent-failure"})

    row = (
        await db_session.execute(select(LinkPreview).where(LinkPreview.url == "http://127.0.0.1/recent-failure"))
    ).scalar_one()
    assert abs((row.fetched_at - recent_time).total_seconds()) < 1  # не тронуто — кэш всё ещё свежий
