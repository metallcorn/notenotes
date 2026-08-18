async def _make_space(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Uploads"})
    assert r.status_code == 201
    return r.json()["id"]


async def test_generic_file_over_20mb_rejected(auth_client):
    space_id = await _make_space(auth_client)
    big = b"x" * (21 * 1024 * 1024)
    r = await auth_client.post(
        f"/api/uploads?space_id={space_id}", files={"file": ("big.bin", big, "application/octet-stream")}
    )
    assert r.status_code == 400
    assert "20" in r.json()["detail"]


async def test_generic_file_under_20mb_accepted(auth_client):
    space_id = await _make_space(auth_client)
    small = b"x" * (1024 * 1024)
    r = await auth_client.post(
        f"/api/uploads?space_id={space_id}", files={"file": ("small.bin", small, "application/octet-stream")}
    )
    assert r.status_code == 201
    upload_id = r.json()["id"]

    r = await auth_client.get(f"/api/uploads/{upload_id}")
    assert r.status_code == 200

    r = await auth_client.delete(f"/api/uploads/{upload_id}")
    assert r.status_code == 204


async def test_note_total_attachment_size_over_100mb_rejected(auth_client):
    """_check_note_attachments_size (routers/items.py) — суммарный вес
    НЕ-медиа вложений одной заметки ограничен 100 МБ, считается по
    ссылкам /api/uploads/{id} внутри content. Три файла по 18 МБ каждый
    (все в пределах 20 МБ per-file лимита по отдельности) в сумме дают
    54 МБ — ещё не бьют потолок; шесть таких же — 108 МБ, уже должны
    отклоняться при попытке сохранить заметку с таким content."""
    space_id = await _make_space(auth_client)
    chunk = b"x" * (18 * 1024 * 1024)

    upload_ids = []
    for i in range(6):
        r = await auth_client.post(
            f"/api/uploads?space_id={space_id}", files={"file": (f"f{i}.bin", chunk, "application/octet-stream")}
        )
        assert r.status_code == 201
        upload_ids.append(r.json()["id"])

    r = await auth_client.post(f"/api/items", json={"space_id": space_id, "title": "T", "content": ""})
    item_id = r.json()["id"]

    content_3_files = "\n".join(f"/api/uploads/{uid}" for uid in upload_ids[:3])
    r = await auth_client.patch(f"/api/items/{item_id}", json={"content": content_3_files})
    assert r.status_code == 200  # 54 МБ — в пределах лимита

    content_6_files = "\n".join(f"/api/uploads/{uid}" for uid in upload_ids)
    r = await auth_client.patch(f"/api/items/{item_id}", json={"content": content_6_files})
    assert r.status_code == 400
    assert "100" in r.json()["detail"]
