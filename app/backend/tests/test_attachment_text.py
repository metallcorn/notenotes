"""Распознанный текст файлов живёт в загрузке, а не в заметке (18.10).

Почему — app/attachment_text.py. Здесь: что каждый читатель (поиск,
get_note, публичная страница) видит текст файла, которого в заметке
больше нет; что старый формат с data-text читается по-прежнему; что
ручная правка не теряет прежний текст; и что разовый перенос
(app/attachment_text_migration.py) не теряет ни символа.
"""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy import select

from app import attachment_text_migration
from app.attachment_text import find_attachments, readable_content, strip_inline_text
from app.models import Item, ItemVersion, Space, SpaceMember, Upload, UploadTranscriptVersion
from app.pdf_processing import serialize_document_attachment
from app.routers.search import search_items
from app.tools.notes import get_note
from app.vision import serialize_image_ocr_result


@pytest_asyncio.fixture
async def base(db_session, test_user):
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()

    async def add_file(filename="скан.pdf", content_type="application/pdf", transcript=None):
        upload = Upload(space_id=space.id, author_id=test_user.id, filename=filename,
                        content_type=content_type, transcript=transcript, transcription_status="done")
        db_session.add(upload)
        await db_session.commit()
        return upload

    async def add_note(content, title="Заметка", material_type="note", properties=None):
        item = Item(space_id=space.id, author_id=test_user.id, title=title, content=content,
                    material_type=material_type, properties=properties or {})
        db_session.add(item)
        await db_session.commit()
        return item

    ctx = SimpleNamespace(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="Europe/Warsaw")
    return SimpleNamespace(space=space, user=test_user, ctx=ctx, add_file=add_file, add_note=add_note)


def _legacy_doc(upload_id, text, filename="скан.pdf"):
    esc = text.replace("&", "&amp;").replace("\n", "&#10;").replace('"', "&quot;")
    return f'<div data-doc-attachment data-url="/api/uploads/{upload_id}" data-filename="{filename}" data-text="{esc}"></div>'


def test_new_cards_carry_no_text():
    uid = uuid.uuid4()
    assert "data-text" not in serialize_document_attachment(f"/api/uploads/{uid}", "a.pdf")
    assert "data-text" not in serialize_image_ocr_result(uid, "image/png")


def test_legacy_ocr_card_without_id_binds_to_preceding_image():
    """Карточки текста картинок до августа шли без data-upload-id, сразу
    после самой картинки. ЗАМЕР 18.10: все 64 такие карточки побайтово
    совпали с transcript ближайшей загрузки выше."""
    first, second = uuid.uuid4(), uuid.uuid4()
    content = (
        f"![](/api/uploads/{first})\n\n<div data-image-ocr-result data-text=\"раз\"></div>\n\n"
        f"![](/api/uploads/{second})\n\n<div data-image-ocr-result data-text=\"два\"></div>"
    )
    found = find_attachments(content)
    assert [(a.upload_id, a.inline_text) for a in found] == [(first, "раз"), (second, "два")]


async def test_readable_content_takes_text_from_upload_and_from_legacy_attr(base, db_session):
    fresh = await base.add_file(transcript="Umowa najmu do dnia 14.07.2027")
    content = (
        "До текста\n\n"
        f"{serialize_document_attachment(f'/api/uploads/{fresh.id}', 'umowa.pdf')}\n\n"
        f"{_legacy_doc(uuid.uuid4(), 'Старый текст &amp; кавычки')}"
    )
    readable = await readable_content(db_session, content)
    assert "Umowa najmu do dnia 14.07.2027" in readable
    assert "Старый текст &amp; кавычки" in readable
    assert "<div" not in readable
    assert readable.startswith("До текста")


async def test_search_finds_note_through_attachment_text(base, db_session):
    upload = await base.add_file(transcript="Polisa ubezpieczeniowa Warta numer 777")
    note = await base.add_note(serialize_document_attachment(f"/api/uploads/{upload.id}", "polisa.pdf"))
    await base.add_note("посторонняя заметка", title="Другое")

    found = await search_items(db_session, base.user.id, "Warta")
    assert [i.id for i in found] == [note.id]


async def test_search_finds_ticket_by_everyday_word(base, db_session):
    """«какие у меня авиабилеты» — синонимов в OCR нет, они в properties."""
    upload = await base.add_file(content_type="image/png", transcript="Boarding pass LOT 123")
    ticket = await base.add_note(
        f'<div data-ticket-attachment data-url="/api/uploads/{upload.id}" data-ticket-type="flight"></div>',
        material_type="ticket",
        properties={"ticket_type": "flight", "search_keywords": "авиабилет самолёт рейс перелёт"},
    )
    found = await search_items(db_session, base.user.id, "авиабилет", material_types=("note", "ticket"))
    assert [i.id for i in found] == [ticket.id]


async def test_get_note_gives_file_text_separately_from_content(base):
    upload = await base.add_file(transcript="PESEL 12345678901")
    tag = serialize_document_attachment(f"/api/uploads/{upload.id}", "karta.pdf")
    note = await base.add_note(f"Скан\n\n{tag}")

    result = await get_note(base.ctx, {"item_id": str(note.id)})
    # Тег остаётся в content как есть: модель переписывает заметку целиком,
    # и голый текст на месте тега уничтожил бы карточку файла.
    assert result["content"] == note.content
    assert result["files"] == [{"filename": "karta.pdf", "text": "PESEL 12345678901", "file_id": str(upload.id)}]


async def test_transcript_edit_keeps_previous_text(auth_client, db_session):
    space_id = (await auth_client.post("/api/spaces", json={"name": "Файлы"})).json()["id"]
    r = await auth_client.post(
        f"/api/uploads?space_id={space_id}", files={"file": ("заметки.txt", "Первый текст".encode(), "text/plain")}
    )
    upload_id = r.json()["id"]

    # Текст txt/docx раньше уходил только в заметку — теперь он в загрузке.
    r = await auth_client.get(f"/api/uploads/{upload_id}/text")
    assert r.json()["text"] == "Первый текст"

    r = await auth_client.patch(f"/api/uploads/{upload_id}/transcript", json={"text": "Исправленный текст"})
    assert r.status_code == 200
    assert (await auth_client.get(f"/api/uploads/{upload_id}/text")).json()["text"] == "Исправленный текст"

    versions = (
        await db_session.execute(
            select(UploadTranscriptVersion.transcript).where(UploadTranscriptVersion.upload_id == uuid.UUID(upload_id))
        )
    ).scalars().all()
    assert versions == ["Первый текст"]


async def test_public_page_reads_attachment_text_by_token(client, base, db_session):
    upload = await base.add_file(transcript="Текст для гостя")
    note = await base.add_note(serialize_document_attachment(f"/api/uploads/{upload.id}", "a.pdf"))
    note.is_public = True
    note.share_token = "tok-attachment-text"
    await db_session.commit()

    r = await client.get(f"/api/public/tok-attachment-text/uploads/{upload.id}/text")
    assert r.status_code == 200
    assert r.json()["text"] == "Текст для гостя"

    # Чужой файл по валидному токену — нет.
    other = await base.add_file(transcript="чужое")
    r = await client.get(f"/api/public/tok-attachment-text/uploads/{other.id}/text")
    assert r.status_code == 404


async def test_migration_moves_text_and_loses_nothing(base, db_session, monkeypatch):
    same = await base.add_file(transcript="Совпадающий текст")
    empty = await base.add_file(filename="umowa.docx", transcript=None)
    image = await base.add_file(filename="foto.jpg", content_type="image/jpeg", transcript="Текст фото")
    differs = await base.add_file(transcript="Совсем другое")
    gone = uuid.uuid4()

    content = (
        "Начало заметки\n\n"
        f"{_legacy_doc(same.id, 'Совпадающий текст')}\n\n"
        f"{_legacy_doc(empty.id, 'Przedłużyć do dnia 14.07.2027', 'umowa.docx')}\n\n"
        f"![](/api/uploads/{image.id})\n\n<div data-image-ocr-result data-text=\"Текст фото\"></div>\n\n"
        f"{_legacy_doc(differs.id, 'Текст в заметке')}\n\n"
        f"{_legacy_doc(gone, 'Единственная копия')}\n\n"
        "Конец заметки"
    )
    note = await base.add_note(content)

    @contextlib.asynccontextmanager
    async def _session():
        yield db_session

    monkeypatch.setattr(attachment_text_migration, "async_session", _session)
    await attachment_text_migration.run(apply=True)
    await db_session.refresh(note)
    await db_session.refresh(empty)

    # Перенесено в загрузку то, чего там не было.
    assert empty.transcript == "Przedłużyć do dnia 14.07.2027"
    # Совпавшее, перенесённое и картинка — без data-text; у карточки
    # картинки появился id файла.
    blocks = {a.upload_id: a for a in find_attachments(note.content)}
    assert blocks[same.id].inline_text == ""
    assert blocks[empty.id].inline_text == ""
    assert blocks[image.id].inline_text == ""
    assert f'data-upload-id="{image.id}"' in note.content
    # Разошедшийся и осиротевший — нетронуты.
    assert blocks[differs.id].inline_text == "Текст в заметке"
    assert blocks[gone].inline_text == "Единственная копия"
    # Вне блоков — ни символа изменений.
    assert note.content.startswith("Начало заметки") and note.content.endswith("Конец заметки")
    # Версия до переезда сохранена.
    versions = (await db_session.execute(select(ItemVersion.content).where(ItemVersion.item_id == note.id))).scalars().all()
    assert versions == [content]


def test_strip_inline_text_keeps_blocks():
    uid = uuid.uuid4()
    stripped = strip_inline_text(f"a {_legacy_doc(uid, 'x')} b")
    assert stripped == f'a <div data-doc-attachment data-url="/api/uploads/{uid}" data-filename="скан.pdf"></div> b'


def test_block_with_angle_bracket_inside_text_is_found():
    """Экранирование data-text не трогало >, а в распознанном тексте он
    есть. Разбор «до первого >» пропускал 44 блока из 228 (замер 18.10)."""
    uid = uuid.uuid4()
    content = f"x {_legacy_doc(uid, 'Kwota -> 1200 zł<br>razem')} y"
    found = find_attachments(content)
    assert len(found) == 1
    assert found[0].upload_id == uid
    assert found[0].inline_text == "Kwota -> 1200 zł<br>razem"
    assert "data-text" not in strip_inline_text(content)
