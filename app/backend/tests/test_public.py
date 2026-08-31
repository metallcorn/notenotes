async def _make_public_note(auth_client, content="hello world"):
    r = await auth_client.post("/api/spaces", json={"name": "Pub", "is_public_pages": True})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "Public note", "content": content})
    return r.json()["id"]


async def test_public_view_without_password(auth_client, client):
    item_id = await _make_public_note(auth_client)
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": False})
    token = r.json()["share_token"]

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 200
    assert r.json()["title"] == "Public note"


async def test_public_unknown_token_404(client):
    r = await client.get("/api/public/does-not-exist")
    assert r.status_code == 404


async def test_public_password_flow(auth_client, client):
    item_id = await _make_public_note(auth_client)
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"password": "sekret123", "single_use": False})
    token = r.json()["share_token"]

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 200
    assert r.json() == {"requires_password": True}

    r = await client.post(f"/api/public/{token}/unlock", json={"password": "wrong"})
    assert r.status_code == 401

    r = await client.post(f"/api/public/{token}/unlock", json={"password": "sekret123"})
    assert r.status_code == 200
    assert r.json()["title"] == "Public note"


async def test_public_single_use_blocks_second_view(auth_client, client):
    item_id = await _make_public_note(auth_client)
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": True})
    token = r.json()["share_token"]

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 200

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 404


async def test_public_upload_requires_reference_in_content(auth_client, client):
    item_id = await _make_public_note(auth_client, content="text ![](/api/uploads/00000000-0000-0000-0000-000000000000)")
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": False})
    token = r.json()["share_token"]

    # не встречается в content этой заметки — 404, даже с валидным токеном
    r = await client.get(f"/api/public/{token}/uploads/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 404


async def test_unshare_invalidates_old_token(auth_client, client):
    item_id = await _make_public_note(auth_client)
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": False})
    token = r.json()["share_token"]

    r = await auth_client.post(f"/api/items/{item_id}/unshare")
    assert r.status_code == 200

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 404


# --- /s/{token}: og:* для мессенджеров-анфёрлеров (Telegram и т.п.) --------
# Реальная жалоба: делишься ссылкой на заметку в Telegram — превью пустое.
# /s/{token} раньше отдавался тем же голым index.html, что и всё
# остальное (SPA catch-all в main.py) — ни заголовка заметки, ни og:*,
# бот-анфёрлер не исполняет JS и не видит контент, который рисует React.

async def test_share_preview_includes_note_title_and_description(auth_client, client):
    item_id = await _make_public_note(auth_client, content="Первая строка текста заметки.")
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": False})
    token = r.json()["share_token"]

    r = await client.get(f"/s/{token}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert '<title>Public note</title>' in r.text
    assert 'property="og:title" content="Public note"' in r.text
    assert "Первая строка текста заметки" in r.text


async def test_share_preview_password_protected_hides_title(auth_client, client):
    item_id = await _make_public_note(auth_client, content="секретный контент, не должен утечь")
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"password": "sekret123", "single_use": False})
    token = r.json()["share_token"]

    r = await client.get(f"/s/{token}")
    assert r.status_code == 200
    assert "Public note" not in r.text
    assert "секретный контент" not in r.text
    assert "Защищённая заметка" in r.text


async def test_share_preview_single_use_does_not_burn_token(auth_client, client):
    # Реальный риск: мессенджеры сами дёргают эту страницу СЕРВЕРНО, чтобы
    # собрать превью, ещё до того как получатель хоть раз откроет ссылку —
    # если бы /s/{token} помечал одноразовую ссылку использованной, она
    # сгорала бы от одной вставки в чат, до всякого клика получателя.
    item_id = await _make_public_note(auth_client)
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": True})
    token = r.json()["share_token"]

    r = await client.get(f"/s/{token}")
    assert r.status_code == 200
    assert "Public note" in r.text

    r = await client.get(f"/api/public/{token}")
    assert r.status_code == 200  # всё ещё не использована


async def test_share_preview_unknown_token_falls_back_gracefully(client):
    r = await client.get("/s/does-not-exist")
    assert r.status_code == 200  # SPA-страница должна отрисоваться, не 404
    assert "Notenotes" in r.text


async def test_share_preview_uses_first_real_image_as_og_image(auth_client, client):
    r = await auth_client.post("/api/spaces", json={"name": "PubImg", "is_public_pages": True})
    space_id = r.json()["id"]
    r = await auth_client.post(
        f"/api/uploads?space_id={space_id}", files={"file": ("p.png", b"\x89PNG\r\n\x1a\nfakepngbytes", "image/png")}
    )
    assert r.status_code == 201
    upload_id = r.json()["id"]

    r = await auth_client.post(
        "/api/items",
        json={"space_id": space_id, "title": "With image", "content": f"![]( /api/uploads/{upload_id} )"},
    )
    item_id = r.json()["id"]
    r = await auth_client.post(f"/api/items/{item_id}/share", json={"single_use": False})
    token = r.json()["share_token"]

    r = await client.get(f"/s/{token}")
    assert r.status_code == 200

    from app.core.config import get_settings

    base_url = get_settings().public_base_url.rstrip("/")
    assert f'og:image" content="{base_url}/api/public/{token}/uploads/{upload_id}"' in r.text
