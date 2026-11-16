"""Билет в PDF — тот же конвейер, что у фото (app/tickets.py,
app/pdf_processing.py).

Реальный случай 16.11: два жд-билета PDF из Telegram остались обычными
документами — ни карточки, ни напоминания о поездке. Данные вымышленные:
Jan Kowalski, маршрут условный.

Фоновые функции работают через свой app.db.async_session(), поэтому
строки создаются по-настоящему и убираются вручную (как в test_vision.py).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import select

from app import pdf_processing, tickets
from app.models import Item, Notification, Space, SpaceMember, Upload, User
from app.security import hash_password

TRANSCRIPT = (
    "| Поле | Значение |\n|---|---|\n| Numer biletu | WJ 000000001 |\n| z/from: | Poznań Gł. |\n"
    "| do/to: | Warszawa Centr. |\n| Główny pasażer | JAN KOWALSKI |\n| Odjazd | 2026-12-01 09:36 |\n"
    "| Wagon | 7 | Miejsce | 42 |\n"
)


async def _make_real_pdf_note() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from app.db import async_session as real_async_session

    async with real_async_session() as db:
        user = User(username=f"pdf_ticket_{uuid.uuid4().hex[:12]}", password_hash=hash_password("x"), name="Jan", timezone="Europe/Warsaw")
        db.add(user)
        await db.flush()
        space = Space(name="S", owner_id=user.id)
        db.add(space)
        await db.flush()
        db.add(SpaceMember(space_id=space.id, user_id=user.id))
        upload = Upload(space_id=space.id, author_id=user.id, filename="ticket_ABC123.pdf", content_type="application/pdf",
                        transcription_status="done", transcript=TRANSCRIPT)
        db.add(upload)
        await db.flush()
        card = pdf_processing.serialize_document_attachment(f"/api/uploads/{upload.id}", "ticket_ABC123.pdf")
        item = Item(space_id=space.id, author_id=user.id, material_type="note", title="ticket_ABC123.pdf", content=f"{card}\n")
        db.add(item)
        await db.commit()
        return item.id, upload.id, user.id


async def _cleanup(item_id: uuid.UUID, upload_id: uuid.UUID, user_id: uuid.UUID) -> None:
    from app.db import async_session as real_async_session

    async with real_async_session() as db:
        for n in (await db.execute(select(Notification).where(Notification.user_id == user_id))).scalars().all():
            await db.delete(n)
        for model, pk in ((Item, item_id), (Upload, upload_id), (User, user_id)):
            row = await db.get(model, pk)
            if row is not None:
                await db.delete(row)
        await db.commit()


async def test_pdf_ticket_gets_card_title_and_trip_reminder(monkeypatch):
    item_id, upload_id, user_id = await _make_real_pdf_note()
    extracted = {
        "ticket_type": "train", "datetime_start": "2026-12-01T09:36:00", "datetime_end": "2026-12-01T12:20:00",
        "location_from": "Poznań Gł.", "location_to": "Warszawa Centr.", "seat": "wagon 7, miejsce 42",
        "flight_number": None, "title": "Билет Poznań — Warszawa, 01.12",
    }

    async def fake_extract(transcript):
        assert "Numer biletu" in transcript
        return extracted

    monkeypatch.setattr(tickets, "_extract", fake_extract)
    monkeypatch.setattr(tickets, "_decode_code", lambda upload_id, *, pdf=False: "AZTEC-PAYLOAD" if pdf else None)
    try:
        await tickets._process(upload_id)

        from app.db import async_session as real_async_session

        async with real_async_session() as db:
            item = await db.get(Item, item_id)
            assert item.material_type == "ticket"
            assert "data-doc-attachment" not in item.content, "карточка документа заменена карточкой билета"
            assert re.search(rf'<div data-ticket-attachment [^>]*data-url="/api/uploads/{upload_id}"', item.content)
            assert 'data-filename="ticket_ABC123.pdf"' in item.content and 'data-ticket-type="train"' in item.content
            assert 'data-code="AZTEC-PAYLOAD"' in item.content
            assert item.title == "Билет Poznań — Warszawa, 01.12", "имя файла — такой же пустой заголовок, как «Фото»"
            assert item.properties["upload_id"] == str(upload_id) and item.properties["ticket_type"] == "train"
            upload = await db.get(Upload, upload_id)
            assert upload.transcription_status == "done"
            reminder = (await db.execute(select(Notification).where(Notification.user_id == user_id))).scalar_one()
            assert reminder.type == "ticket_event" and reminder.title.startswith("ЖД-билет: Билет Poznań")
            # За час до отправления, по поясу автора.
            from zoneinfo import ZoneInfo

            assert reminder.trigger_at.astimezone(ZoneInfo("Europe/Warsaw")).replace(tzinfo=None) == datetime(2026, 12, 1, 8, 36)
    finally:
        await _cleanup(item_id, upload_id, user_id)


async def test_pdf_without_structure_stays_a_document(monkeypatch):
    item_id, upload_id, user_id = await _make_real_pdf_note()

    async def no_data(transcript):
        return None

    monkeypatch.setattr(tickets, "_extract", no_data)
    try:
        await tickets._process(upload_id)
        from app.db import async_session as real_async_session

        async with real_async_session() as db:
            item = await db.get(Item, item_id)
            assert item.material_type == "note" and "data-doc-attachment" in item.content
            assert "⚠️" not in item.content, "документ с текстом не портится предупреждением"
            upload = await db.get(Upload, upload_id)
            assert upload.transcription_status == "done"
    finally:
        await _cleanup(item_id, upload_id, user_id)


async def test_pdf_hand_over_only_when_classifier_says_yes(monkeypatch):
    queued: list[uuid.UUID] = []
    monkeypatch.setattr(tickets, "enqueue_ticket_extraction", queued.append)
    answers = iter([True, False])

    async def fake_classifier(transcript):
        return next(answers)

    monkeypatch.setattr(tickets, "looks_like_ticket", fake_classifier)
    first, second = uuid.uuid4(), uuid.uuid4()
    await pdf_processing._hand_over_if_ticket(first, TRANSCRIPT)
    await pdf_processing._hand_over_if_ticket(second, "Faktura VAT nr 1/2026")
    assert queued == [first]


async def test_classifier_reads_yes_no_and_skips_tiny_text(monkeypatch):
    class _Resp:
        def __init__(self, text):
            self.message = type("M", (), {"content": text})()

    class _Client:
        def __init__(self, text):
            self.text = text

        async def chat(self, messages, tools):
            assert messages[1].content.startswith("| Поле")
            return _Resp(self.text)

    for text, expected in (("Да.", True), ("**да**", True), ("Нет", False), ("Это не билет", False)):
        monkeypatch.setattr(tickets, "get_llm_client", lambda text=text: _Client(text))
        assert await tickets.looks_like_ticket(TRANSCRIPT) is expected, text
    monkeypatch.setattr(tickets, "get_llm_client", lambda: (_ for _ in ()).throw(AssertionError("модель не нужна")))
    assert await tickets.looks_like_ticket("ok") is False
