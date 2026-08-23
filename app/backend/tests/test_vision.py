import uuid

from app.models import Item
from app.vision import _split_ticket_marker, placeholder_text, replace_recognized_text_card, serialize_image_ocr_result


def test_ticket_marker_plain():
    is_ticket, rest = _split_ticket_marker("БИЛЕТ: да\n\nЭлектронный билет на рейс LOT 3945.")
    assert is_ticket is True
    assert rest.startswith("Электронный билет")


def test_ticket_marker_no():
    is_ticket, rest = _split_ticket_marker("БИЛЕТ: нет\n\nФотография кота на подоконнике.")
    assert is_ticket is False
    assert rest.startswith("Фотография кота")


def test_ticket_marker_markdown_bold():
    # Реальный найденный случай: модель обернула маркер в markdown вместо
    # голого текста, как просили в промпте — раньше строгий регэксп это не ловил.
    is_ticket, _ = _split_ticket_marker("**БИЛЕТ: да**\n\nПосадочный талон авиакомпании.")
    assert is_ticket is True


def test_ticket_marker_heading_style():
    is_ticket, _ = _split_ticket_marker("### БИЛЕТ: да\n\nЖД-билет.")
    assert is_ticket is True


def test_ticket_fallback_when_marker_missing_but_description_says_ticket():
    # Реальный найденный случай: модель вообще пропустила маркерную строку,
    # но в самом начале описания честно назвала изображение билетом.
    is_ticket, rest = _split_ticket_marker(
        "Электронный билет авиакомпании LOT Polish Airlines на рейс из Варшавы в Познань."
    )
    assert is_ticket is True
    assert rest.startswith("Электронный билет")


def test_ticket_fallback_boarding_pass_wording():
    is_ticket, _ = _split_ticket_marker("Посадочный талон на автобус, место 14.")
    assert is_ticket is True


def test_ticket_fallback_does_not_trigger_on_unrelated_mention():
    # Осторожный фолбэк: билет должен упоминаться В НАЧАЛЕ описания, не
    # где угодно — иначе случайное упоминание слова "билет" в середине
    # обычной фотографии ложно классифицировалось бы как билет.
    is_ticket, rest = _split_ticket_marker(
        "Фотография стола с ноутбуком и чашкой кофе. Рядом лежит забытый билет в кино."
    )
    assert is_ticket is False
    assert rest.startswith("Фотография стола")


# --- serialize_image_ocr_result: upload_id + data-can-reprocess --------------
# Реальный найденный пробел: карточка распознанного текста не несла
# upload_id вообще — ни кнопку "распознать заново", ни ручную правку текста
# сделать было не от чего оттолкнуться.

def test_serialize_image_ocr_result_includes_upload_id():
    uid = uuid.uuid4()
    html = serialize_image_ocr_result(uid, "текст", "image/jpeg")
    assert f'data-upload-id="{uid}"' in html


def test_serialize_image_ocr_result_can_reprocess_for_image():
    html = serialize_image_ocr_result(uuid.uuid4(), "текст", "image/jpeg")
    assert 'data-can-reprocess="1"' in html


def test_serialize_image_ocr_result_no_reprocess_for_audio():
    # /api/uploads/{id}/reprocess не умеет чистое аудио (голосовые записи
    # note_recording.py — отдельный пайплайн) — не показываем кнопку,
    # которая гарантированно вернёт 400.
    html = serialize_image_ocr_result(uuid.uuid4(), "текст", "audio/ogg")
    assert "data-can-reprocess" not in html


# --- replace_recognized_text_card: и плейсхолдер, и уже готовая карточка ----
# _replace_by_pattern (и все родственные функции в vision.py/pdf_processing.py/
# tickets.py) намеренно используют СВОЙ app.db.async_session(), а не
# Depends(get_db) — они фоновые воркеры, не HTTP-запрос, им неоткуда взять
# request-scoped сессию. Из-за этого их нельзя протестировать через
# db_session/auth_client — те работают в ОДНОЙ изолированной транзакции,
# которая откатывается после теста и не видна другому соединению (тот же
# ограничение, что уже задокументировано у pdf_processing.resume_pending()).
# Поэтому здесь — свой setup/teardown через тот же async_session(), что и
# сама функция: реальные committed-строки, ручная уборка в конце.

async def _make_real_item(content: str) -> tuple[uuid.UUID, uuid.UUID]:
    from app.db import async_session as real_async_session
    from app.models import Space, User
    from app.security import hash_password

    async with real_async_session() as db:
        user = User(username=f"vision_test_{uuid.uuid4().hex[:12]}", password_hash=hash_password("x"), name="T")
        db.add(user)
        await db.flush()
        space = Space(name="S", owner_id=user.id)
        db.add(space)
        await db.flush()
        item = Item(space_id=space.id, author_id=user.id, material_type="note", title="T", content=content)
        db.add(item)
        await db.commit()
        return item.id, user.id


async def _cleanup_real_item(item_id: uuid.UUID, user_id: uuid.UUID) -> None:
    from app.db import async_session as real_async_session
    from app.models import User

    async with real_async_session() as db:
        it = await db.get(Item, item_id)
        if it is not None:
            await db.delete(it)
        u = await db.get(User, user_id)
        if u is not None:
            await db.delete(u)
        await db.commit()


async def test_replace_recognized_text_card_replaces_placeholder():
    uid = uuid.uuid4()
    item_id, user_id = await _make_real_item(f"![]( /x )\n\n{placeholder_text(uid)}\n")
    try:
        new_card = serialize_image_ocr_result(uid, "распознанный текст", "image/jpeg")
        ok = await replace_recognized_text_card(uid, placeholder_text(uid), new_card)
        assert ok is True

        from app.db import async_session as real_async_session

        async with real_async_session() as db:
            item = await db.get(Item, item_id)
            assert placeholder_text(uid) not in item.content
            assert new_card in item.content
    finally:
        await _cleanup_real_item(item_id, user_id)


async def test_replace_recognized_text_card_replaces_existing_card_not_just_placeholder():
    # Реальный найденный баг: повторный запуск распознавания ("распознать
    # заново") на уже готовой картинке раньше искал только текст
    # плейсхолдера — в заметке его давно нет (там уже готовая карточка), и
    # замена молча ничего не находила. Теперь ищем ЛИБО плейсхолдер, ЛИБО
    # существующую карточку этого upload_id по data-upload-id.
    uid = uuid.uuid4()
    old_card = serialize_image_ocr_result(uid, "старый текст с опечаткой", "image/jpeg")
    item_id, user_id = await _make_real_item(f"![]( /x )\n\n{old_card}\n")
    try:
        new_card = serialize_image_ocr_result(uid, "исправленный текст", "image/jpeg")
        ok = await replace_recognized_text_card(uid, placeholder_text(uid), new_card)
        assert ok is True

        from app.db import async_session as real_async_session

        async with real_async_session() as db:
            item = await db.get(Item, item_id)
            assert "старый текст с опечаткой" not in item.content
            assert "исправленный текст" in item.content
    finally:
        await _cleanup_real_item(item_id, user_id)


async def test_replace_recognized_text_card_snapshot_version():
    from sqlalchemy import select

    from app.db import async_session as real_async_session
    from app.models import ItemVersion

    uid = uuid.uuid4()
    old_card = serialize_image_ocr_result(uid, "старый текст", "image/jpeg")
    item_id, user_id = await _make_real_item(old_card)
    try:
        new_card = serialize_image_ocr_result(uid, "новый текст", "image/jpeg")
        await replace_recognized_text_card(uid, None, new_card, snapshot_version=True)

        async with real_async_session() as db:
            versions = (await db.execute(select(ItemVersion).where(ItemVersion.item_id == item_id))).scalars().all()
            assert len(versions) == 1
            assert "старый текст" in versions[0].content
            for v in versions:
                await db.delete(v)
            await db.commit()
    finally:
        await _cleanup_real_item(item_id, user_id)
