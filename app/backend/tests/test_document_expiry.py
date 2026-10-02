"""Сроки документов: предупредить заранее, а не констатировать постфактум.

Данные для этих тестов — настоящие строки с боевой базы (02.10): паспорта,
договор аренды, техосмотр, очередное ТО. Разбор тот же, что у
expiry_check, но смотрит он ВПЕРЁД, а не назад.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import select

from app import document_expiry
from app.models import Item, Notification, Space, SpaceMember, Upload

TODAY = date(2026, 10, 2)


class TestРазборСроков:
    def test_настоящие_строки_из_базы(self):
        # Даты пересчитаны от TODAY, чтобы тест не протух: в живых строках
        # стояли 2027-й и 2031-й, но горизонт — 400 дней, и дальний
        # паспорт сюда намеренно не попадает (см. тест ниже).
        soon = TODAY + timedelta(days=300)
        cases = [
            f"Paszport 75 1234567 ważny do {soon:%d.%m.%Y}",
            f"przedłużyć okres obowiązywania Umowy do dnia {soon:%d.%m.%Y} r.",
            f"Następny przegląd: do 88.166 km lub do dnia {soon:%d.%m.%Y}",
            f"Техосмотр, срок истекает {soon:%d.%m.%Y}",
        ]
        for text in cases:
            found = document_expiry.find_upcoming(text, TODAY)
            assert [d for d, _ in found] == [soon], text

    def test_прошедшее_не_берём(self):
        """Им занимается expiry_check в самом ответе ассистента."""
        assert document_expiry.find_upcoming("ważny do 10.08.2020", TODAY) == []

    def test_слишком_далёкое_подождёт(self):
        """Паспорт до 2031 — настоящий срок, но напоминание на 2031-й
        сегодня не нужно никому; заведётся, когда подойдёт время."""
        far = (TODAY + timedelta(days=500)).strftime("%d.%m.%Y")
        assert document_expiry.find_upcoming(f"ważny do {far}", TODAY) == []

    def test_просто_дата_в_тексте_не_срок(self):
        """«Встреча была 14 июня» — не срок действия, и помечать её шум."""
        assert document_expiry.find_upcoming("Встреча была 14 июня 2027 года", TODAY) == []

    def test_пояснение_объясняет_о_чём_речь(self):
        """Названия бывают бесполезны («CamScanner 29.05.2025 07.31.pdf»),
        а строка из документа объясняет всё."""
        _, snippet = document_expiry.find_upcoming("PESEL 90010112345 Paszport 75 1234567 ważny do 10.08.2027", TODAY)[0]
        assert "Paszport" in snippet

    def test_дубли_по_дате_схлопнуты(self):
        text = "ważny do 10.08.2027 ... и ещё раз ważny do 10.08.2027"
        assert len(document_expiry.find_upcoming(text, TODAY)) == 1


@pytest_asyncio.fixture
async def base(db_session, test_user):
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()

    async def note(content, *, title="Документ", vault=False):
        target = space
        if vault:
            target = Space(name="Сейф", owner_id=test_user.id, is_vault=True)
            db_session.add(target)
            await db_session.flush()
            db_session.add(SpaceMember(space_id=target.id, user_id=test_user.id))
        item = Item(space_id=target.id, author_id=test_user.id, title=title,
                    content=content, material_type="note", properties={})
        db_session.add(item)
        await db_session.flush()
        await db_session.commit()
        return item

    async def file_in(item, transcript, filename="скан.pdf"):
        upload = Upload(space_id=item.space_id, author_id=test_user.id,
                        filename=filename, content_type="application/pdf", transcript=transcript)
        db_session.add(upload)
        await db_session.flush()
        item.content = f"{item.content}\n<div data-doc-attachment data-url=\"/api/uploads/{upload.id}\"></div>"
        await db_session.commit()
        return upload

    from types import SimpleNamespace

    return SimpleNamespace(space=space, note=note, file_in=file_in)


async def _scan(db_session, monkeypatch) -> list[Notification]:
    import contextlib

    @contextlib.asynccontextmanager
    async def same_session():
        yield db_session

    monkeypatch.setattr(document_expiry, "async_session", same_session)
    await document_expiry._scan_once()
    return list((await db_session.execute(
        select(Notification).where(Notification.type == document_expiry.NOTIFICATION_TYPE)
    )).scalars().all())


class TestЗаведениеНапоминаний:
    async def test_срок_из_заметки(self, base, db_session, monkeypatch):
        soon = (date.today() + timedelta(days=90)).strftime("%d.%m.%Y")
        await base.note(f"Umowa najmu, przedłużyć do dnia {soon}", title="Аренда")

        found = await _scan(db_session, monkeypatch)

        assert len(found) == 1
        assert "Срок истекает" in found[0].title and "Аренда" in found[0].title

    async def test_срок_из_текста_ФАЙЛА(self, base, db_session, monkeypatch):
        """Самое ценное лежит в сканах, а не в тексте заметки."""
        item = await base.note("", title="Паспорт мужа")
        soon = (date.today() + timedelta(days=90)).strftime("%d.%m.%Y")
        await base.file_in(item, f"PESEL 90010112345 Paszport 75 1234567 ważny do {soon}")

        found = await _scan(db_session, monkeypatch)

        assert len(found) == 1
        assert "Paszport" in found[0].body

    async def test_предупреждает_за_шестьдесят_дней(self, base, db_session, monkeypatch):
        expires = date.today() + timedelta(days=90)
        await base.note(f"ważny do {expires:%d.%m.%Y}")

        found = await _scan(db_session, monkeypatch)

        assert found[0].trigger_at.date() == expires - document_expiry.LEAD

    async def test_близкий_срок_напоминает_сразу(self, base, db_session, monkeypatch):
        """Осталось меньше 60 дней — trigger_at в прошлом, диспетчер
        отправит немедленно. Узнать поздно лучше, чем не узнать."""
        expires = date.today() + timedelta(days=10)
        await base.note(f"ważny do {expires:%d.%m.%Y}")

        found = await _scan(db_session, monkeypatch)

        assert found[0].trigger_at < datetime.now(timezone.utc)

    async def test_повторный_проход_не_дублирует(self, base, db_session, monkeypatch):
        """Воркер ходит каждые шесть часов."""
        await base.note(f"ważny do {(date.today() + timedelta(days=90)):%d.%m.%Y}")

        await _scan(db_session, monkeypatch)
        found = await _scan(db_session, monkeypatch)

        assert len(found) == 1

    async def test_сейф_не_сканируется(self, base, db_session, monkeypatch):
        """Сервер его не читает — и читать не должен."""
        await base.note(f"ważny do {(date.today() + timedelta(days=90)):%d.%m.%Y}", vault=True)

        assert await _scan(db_session, monkeypatch) == []

    async def test_удалённая_заметка_не_сканируется(self, base, db_session, monkeypatch):
        item = await base.note(f"ważny do {(date.today() + timedelta(days=90)):%d.%m.%Y}")
        item.deleted_at = datetime.now(timezone.utc)
        await db_session.commit()

        assert await _scan(db_session, monkeypatch) == []

    async def test_напоминание_попадает_в_адженду(self, base, db_session, monkeypatch, test_user):
        """Отдельного канала доставки не заводим: обычное напоминание само
        попадает и в сводку, и в list_agenda, и в Telegram."""
        from app.tools.agenda import collect_agenda

        expires = date.today() + timedelta(days=61)
        await base.note(f"ważny do {expires:%d.%m.%Y}", title="Карта побыту")
        await _scan(db_session, monkeypatch)

        agenda = await collect_agenda(db_session, test_user.id, days=3, tz_name="Europe/Warsaw")

        assert any("Карта побыту" in e["title"] for e in agenda["entries"])
