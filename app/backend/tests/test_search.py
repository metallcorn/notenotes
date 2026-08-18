async def _make_space(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Search"})
    return r.json()["id"]


async def test_search_finds_by_content(auth_client):
    space_id = await _make_space(auth_client)
    await auth_client.post("/api/items", json={"space_id": space_id, "title": "Список покупок", "content": "молоко и хлеб"})
    await auth_client.post("/api/items", json={"space_id": space_id, "title": "Другое", "content": "ничего общего"})

    r = await auth_client.get("/api/search", params={"q": "молоко"})
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()]
    assert "Список покупок" in titles
    assert "Другое" not in titles


async def test_search_prefix_match(auth_client):
    space_id = await _make_space(auth_client)
    await auth_client.post("/api/items", json={"space_id": space_id, "title": "Тестовая заметка", "content": "x"})

    r = await auth_client.get("/api/search", params={"q": "тест"})
    assert any("Тестовая" in i["title"] for i in r.json())


async def test_search_transliteration(auth_client):
    space_id = await _make_space(auth_client)
    await auth_client.post("/api/items", json={"space_id": space_id, "title": "Alina passport", "content": "x"})

    r = await auth_client.get("/api/search", params={"q": "Алина"})
    assert any("Alina" in i["title"] for i in r.json())


async def test_search_excludes_vault(auth_client):
    r = await auth_client.post(
        "/api/spaces", json={"name": "V", "is_vault": True, "vault_salt": "s", "vault_verifier": "{}"}
    )
    space_id = r.json()["id"]
    # В сейфе content реально шифротекст, но с точки зрения сервера это
    # просто text — сама проверка в том, что space_id сейфа не даёт
    # найтись НИКАК, даже если content выглядел бы как обычный текст.
    await auth_client.post("/api/items", json={"space_id": space_id, "title": "уникальныйтест", "content": "x"})

    r = await auth_client.get("/api/search", params={"q": "уникальныйтест"})
    assert not any("уникальныйтест" in i["title"] for i in r.json())


async def test_search_empty_query_returns_empty(auth_client):
    r = await auth_client.get("/api/search", params={"q": ""})
    assert r.status_code == 200 and r.json() == []
