import uuid

from app.models import Item, Space, Upload, User
from app.security import hash_password
from app.transcription import _process, placeholder_text


async def _make_real_upload_and_item(content_type: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from app.db import async_session as real_async_session

    async with real_async_session() as db:
        user = User(username=f"transcription_test_{uuid.uuid4().hex[:12]}", password_hash=hash_password("x"), name="T")
        db.add(user)
        await db.flush()
        space = Space(name="S", owner_id=user.id)
        db.add(space)
        await db.flush()
        upload = Upload(space_id=space.id, author_id=user.id, filename="v.mp4", content_type=content_type)
        db.add(upload)
        await db.flush()
        item = Item(
            space_id=space.id,
            author_id=user.id,
            material_type="note",
            title="T",
            content=f"{placeholder_text(upload.id)}\n",
        )
        db.add(item)
        await db.commit()
        return upload.id, item.id, user.id


async def _cleanup(upload_id: uuid.UUID, item_id: uuid.UUID, user_id: uuid.UUID) -> None:
    from app.db import async_session as real_async_session

    async with real_async_session() as db:
        it = await db.get(Item, item_id)
        if it is not None:
            await db.delete(it)
        up = await db.get(Upload, upload_id)
        if up is not None:
            await db.delete(up)
        u = await db.get(User, user_id)
        if u is not None:
            await db.delete(u)
        await db.commit()


async def test_process_missing_video_file_replaces_placeholder_with_failure_message():
    # Реальная жалоба ("постоянно что-то зависает в фоне"): файл для этого
    # upload_id заведомо не существует на диске (тестовая запись без
    # реальной загрузки) — раньше это молча оставляло плейсхолдер
    # "⏳ ...обрабатывается…" висеть в заметке навсегда, хотя
    # transcription_status уже давно "failed" в БД.
    upload_id, item_id, user_id = await _make_real_upload_and_item("video/mp4")
    try:
        await _process(upload_id)

        from app.db import async_session as real_async_session

        async with real_async_session() as db:
            item = await db.get(Item, item_id)
            assert placeholder_text(upload_id) not in item.content
            assert "не удал" in item.content.lower()

            upload = await db.get(Upload, upload_id)
            assert upload.transcription_status == "failed"
    finally:
        await _cleanup(upload_id, item_id, user_id)
