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


async def test_video_and_audio_exempt_from_generic_limit(auth_client):
    """MAX_UPLOAD_BYTES (300 МБ) действует для video/*|audio/*, а не
    MAX_GENERIC_UPLOAD_BYTES (20 МБ) — 25 МБ "видео" должно пройти."""
    space_id = await _make_space(auth_client)
    blob = b"x" * (25 * 1024 * 1024)
    r = await auth_client.post(f"/api/uploads?space_id={space_id}", files={"file": ("v.mp4", blob, "video/mp4")})
    assert r.status_code == 201


async def test_docx_upload_extracts_text_preview(auth_client):
    import io

    import docx

    space_id = await _make_space(auth_client)
    doc = docx.Document()
    doc.add_paragraph("Договор аренды")
    doc.add_paragraph("Сумма: 50000 рублей в месяц")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    r = await auth_client.post(
        f"/api/uploads?space_id={space_id}",
        files={
            "file": (
                "contract.docx",
                buf.read(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert r.status_code == 201
    # Реальная жалоба: docx, присланные в Telegram, не распознавались — тот
    # же экстрактор (routers/uploads.py::_extract_text_preview), что
    # используется здесь для веб-загрузки, теперь используется и там
    # (telegram_bot.py). Прямого теста на сетевой Telegram-путь нет (см.
    # tests/README.md — внешние сетевые вызовы вне охвата), но сама функция
    # извлечения — общая, и именно её отсутствие в покрытии было пробелом.
    assert "Договор аренды" in r.json()["preview_text"]
    assert "50000" in r.json()["preview_text"]


async def test_upload_thumbnail_lazily_generated_for_pdf(auth_client):
    """Не-PDF без превью — 404, не 500 (см. get_upload_thumbnail)."""
    space_id = await _make_space(auth_client)
    r = await auth_client.post(
        f"/api/uploads?space_id={space_id}", files={"file": ("f.bin", b"hello", "application/octet-stream")}
    )
    upload_id = r.json()["id"]
    r = await auth_client.get(f"/api/uploads/{upload_id}/thumbnail")
    assert r.status_code == 404


async def test_recording_start_and_chunk(auth_client):
    """finish (реальная расшифровка через Deepgram) сознательно не
    покрыт — внешний ASR-провайдер, см. tests/README.md. start/chunk —
    чистая работа с диском/БД, без сети."""
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/uploads/recording/start", json={"space_id": space_id, "content_type": "audio/webm"})
    assert r.status_code == 201
    upload_id = r.json()["id"]

    r = await auth_client.post(f"/api/uploads/recording/{upload_id}/chunk", content=b"fake-audio-bytes")
    assert r.status_code == 204


async def test_recording_start_rejects_non_audio_content_type(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/uploads/recording/start", json={"space_id": space_id, "content_type": "text/html"})
    assert r.status_code == 400


async def test_staged_upload_requires_vault_space(auth_client):
    space_id = await _make_space(auth_client)  # обычный, не сейф
    r = await auth_client.post(
        f"/api/uploads?space_id={space_id}", files={"file": ("f.bin", b"hello", "application/octet-stream")}
    )
    upload_id = r.json()["id"]
    r = await auth_client.put(f"/api/uploads/{upload_id}/staged", files={"file": ("f.bin", b"new-bytes")})
    assert r.status_code == 400
