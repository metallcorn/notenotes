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

    async def test_диалог_не_документ(self, base, db_session, monkeypatch, test_user):
        """Живой случай 10.10: на «какие мероприятия на этой неделе» пришло
        два одинаковых «Срок истекает 10.12.2026» — один от сервисной
        книжки, второй от ДИАЛОГА, где ассистент про неё говорил.

        content диалога — это расшифровка разговора (_flatten_transcript),
        и любой обсуждённый срок находился в нём второй раз. Разговор не
        документ: срок у него не истекает, и вести человека из
        напоминания в середину переписки вместо самой книжки —
        бессмысленно.
        """
        dialog = Item(
            space_id=base.space.id, author_id=test_user.id, material_type="dialog",
            title="Telegram", properties={"messages": []},
            content="Ты: когда техосмотр?\nАссистент: Warunki normalne do dnia 10.12.2026",
        )
        db_session.add(dialog)
        await db_session.commit()

        found = await _scan(db_session, monkeypatch)

        assert found == [], "из разговора срок заводить нельзя"

    async def test_тот_же_срок_в_заметке_заводится(self, base, db_session, monkeypatch, test_user):
        """Контроль к тесту выше: исключён именно диалог, а не сам разбор."""
        await base.note("Warunki normalne do dnia 10.12.2026", title="Сервисная книжка")
        dialog = Item(
            space_id=base.space.id, author_id=test_user.id, material_type="dialog",
            title="Telegram", properties={"messages": []},
            content="Ассистент: Warunki normalne do dnia 10.12.2026",
        )
        db_session.add(dialog)
        await db_session.commit()

        found = await _scan(db_session, monkeypatch)

        assert len(found) == 1
        assert "Сервисная книжка" in found[0].title


class TestПояснениеЧитаемо:
    def test_мусор_разметки_вычищен(self):
        """В боевой базе пояснение выглядело так:
        «-----------|&#10;| 10.12.2024 | | Warunki normalne □ | do 73 000 km»
        — срез markdown-таблицы с неразэкранированным переводом строки и
        палками столбцов. Непонятно ни человеку, ни модели."""
        text = "|-----------|&#10;| 10.12.2024 | | Warunki normalne □ | do 73 000 km lub do dnia 10.12.2026"

        got = document_expiry._snippet(text, len(text))

        assert "|" not in got
        assert "&#" not in got
        assert "---" not in got
        assert "Warunki normalne" in got, "смысл при чистке теряться не должен"

    def test_обычный_текст_не_портится(self):
        """Без разметки и без длинных цифровых цепочек пояснение должно
        доходить слово в слово. (Номер документа тут был бы замаскирован —
        см. test_серия_в_буквенно_цифровом_номере_маскируется.)"""
        text = "Umowa najmu, przedłużyć do dnia 14.07.2027"

        assert document_expiry._snippet(text, len(text)) == text

    def test_номера_документов_не_уезжают_в_уведомление(self):
        """Живое напоминание про паспорт выглядело так: «Jan K… PESEL
        90010112345 Paszport 75 1234567 ważny do 10.08.2027». Оно уходит в
        Telegram и в push, то есть ВЫТАЛКИВАЕТСЯ без спроса, а ещё
        попадает в промпт модели через list_agenda. ТЗ §16.1 про PII
        говорит обратное: в индекс и в промпт — только тег/лейбл.

        Смысл пояснения — сказать, КАКОЙ это документ, а не повторить
        номер: для «пора продлевать» номер не нужен.
        """
        text = "Jan Kowalski PESEL 90010112345 Paszport 75 1234567 ważny do 10.08.2027"

        got = document_expiry._snippet(text, len(text))

        assert "90010112345" not in got
        assert "1234567" not in got
        assert "Paszport" in got, "какой это документ — должно остаться"
        assert "10.08.2027" in got, "и срок тоже"

    def test_даты_и_обычные_числа_не_маскируются(self):
        text = "10.12.2024 Warunki normalne do 73 000 km lub do dnia 10.12.2026"

        got = document_expiry._snippet(text, len(text))

        assert got == text

    def test_серия_в_буквенно_цифровом_номере_маскируется(self):
        text = "Paszport AB7654321, ważny do 05.02.2031"

        got = document_expiry._snippet(text, len(text))

        assert "7654321" not in got
        assert got.startswith("Paszport AB"), "по префиксу документ ещё узнаваем"


class TestПерекрытыеСроки:
    """Жалоба владельца 11.10: пришло «Срок истекает 10.12.2026:
    Сервисная книжка», а срок давно не актуален — документ оказался
    журналом обслуживания, и с тех пор было четыре ТО."""

    SERVICE_BOOK = """
    | 03.10.2023 | Następny przegląd do | 26000 km lub do dnia 03.10.2024 |
    | 25.10.2023 | Następny przegląd do | 41000 km lub do dnia 25.10.2024 |
    | 14.03.2024 | Warunki trudne | do 56 000 km lub do dnia 14.03.2025 |
    | 10.12.2024 | Warunki normalne | do 73 000 km lub do dnia 10.12.2026 |
    | 12.12.2024 | Warunki trudne | do 73 000 km lub do dnia 12.12.2025 |
    | 02.07.2025 | Warunki trudne | do 90 000 km lub do dnia 02.07.2026 |
    | 25.08.2026 | Następny przegląd: do 88.166 km lub do dnia 25.08.2027 |
    """

    def test_журнал_обслуживания_схлопывается_в_последнюю_запись(self):
        from datetime import date

        got = document_expiry.find_upcoming(self.SERVICE_BOOK, date(2026, 10, 11))

        assert [d for d, _ in got] == [date(2027, 8, 25)]

    def test_разные_документы_в_одном_скане_остаются_оба(self):
        """ПРАВИЛО ВЫБРАЛИ ДАННЫЕ. Очевидное «оставляем самый поздний под
        одной формулировкой» прогнал по всей боевой базе — оно отбросило
        бы 10.08.2027 в скане CamScanner, оставив 05.02.2031. А это
        РАЗНЫЕ документы в одном скане (там и PESEL'и трёх человек), и
        спрятать срок на три с половиной года раньше было бы хуже
        исходной болезни. Правило в прод не поехало.

        Два паспорта с близкими сроками — тот же случай, но уже внутри
        горизонта: оба обязаны остаться."""
        from datetime import date

        scan = (
            "Paszport 75 1234567 ważny do 10.08.2027\n"
            "Karta pobytu AB7654321 ważny do 20.10.2027\n"
        )

        got = document_expiry.find_upcoming(scan, date(2026, 10, 11))

        assert [d for d, _ in got] == [date(2027, 8, 10), date(2027, 10, 20)]

    def test_слишком_далёкий_срок_по_прежнему_ждёт(self):
        """Горизонт в 400 дней никуда не делся — и именно он, а не новое
        правило, защищал скан CamScanner в проде: паспорт до 2031 года
        просто не попадал в выборку. Новое правило нужно для случая, когда
        оба срока внутри горизонта (тест выше)."""
        from datetime import date

        got = document_expiry.find_upcoming("Paszport ważny do 05.02.2031", date(2026, 10, 11))

        assert got == []

    def test_журналом_считается_только_своя_формулировка(self):
        """История под «do dnia» не должна схлопывать сроки под «ważny do»
        в том же документе."""
        from datetime import date

        mixed = (
            "Następny przegląd do dnia 03.10.2024\n"      # прошедшее, история
            "Następny przegląd do dnia 25.08.2027\n"
            "Następny przegląd do dnia 10.12.2026\n"
            "Paszport ważny do 10.08.2027\n"
            "Karta pobytu ważny do 20.10.2027\n"
        )

        got = [d for d, _ in document_expiry.find_upcoming(mixed, date(2026, 10, 11))]

        assert date(2027, 8, 25) in got and date(2026, 12, 10) not in got, "журнал схлопнут"
        assert date(2027, 8, 10) in got and date(2027, 10, 20) in got, "паспорта не тронуты"

    def test_одна_будущая_дата_при_истории_остаётся(self):
        """Нечего схлопывать — нечего и терять."""
        from datetime import date

        text = "do dnia 03.10.2024\ndo dnia 25.08.2027\n"

        got = document_expiry.find_upcoming(text, date(2026, 10, 11))

        assert [d for d, _ in got] == [date(2027, 8, 25)]

    FRAGMENT = """
    | 14.03.2024 | 11203 | Warunki trudne X | do 56 000 km lub do dnia 14.03.2025 |
    | 12.12.2024 | 53110 | Warunki trudne X | do 73 000 km lub do dnia 12.12.2025 |
    | 10.12.2024 |       | Warunki normalne | do 73 000 km lub do dnia 10.12.2026 |
    | 02.07.2025 | 69000 | Warunki trudne X | do 90 000 km lub do dnia 02.07.2026 |
    """

    def test_живой_срок_определяет_последняя_ЗАПИСЬ_а_не_поздняя_дата(self):
        """Живой случай 12.10: фото 20260822_132310.jpg — фрагмент той же
        книжки. Самый поздний СРОК в нём 10.12.2026, и о нём пришло
        напоминание. Но он из записи от 10.12.2024, а машину обслуживали
        позже — 02.07.2025, и тот срок (02.07.2026) уже прошёл. Значит
        живого срока во фрагменте нет вовсе, а 10.12.2026 — бумажный
        хвост.
        """
        from datetime import date

        got = document_expiry.find_upcoming(self.FRAGMENT, date(2026, 10, 12))

        assert got == []

    def test_запись_строки_читается_из_её_же_строки(self):
        from datetime import date
        import re

        from app.expiry_check import _CLAIM_RE

        match = next(m for m in _CLAIM_RE.finditer(self.FRAGMENT) if "10.12.2026" in m.group(0))

        assert document_expiry._row_date(self.FRAGMENT, match) == date(2024, 12, 10)
        assert isinstance(match, re.Match)

    def test_без_даты_записи_срок_не_выбрасывается(self):
        """Если строку журнала распознали без её даты, лучше предупредить
        лишний раз, чем промолчать о настоящем сроке."""
        from datetime import date

        text = "do dnia 03.10.2024\nNastępny przegląd do dnia 25.08.2027\n"

        got = [d for d, _ in document_expiry.find_upcoming(text, date(2026, 10, 12))]

        assert got == [date(2027, 8, 25)]


class TestСсылкаИзНапоминания:
    async def test_в_payload_есть_и_item_и_space(self, base, db_session, monkeypatch):
        """Жалоба владельца 12.10: «не могу на это кликнуть в отличии от
        всего другого». ActivityView.tsx делает карточку кликабельной
        только при наличии ОБОИХ — space_id и item_id, — а мы кладли
        только второй, и все пять напоминаний о сроках были мёртвыми
        ссылками."""
        await base.note("Paszport ważny do 10.08.2027", title="Паспорт")

        found = await _scan(db_session, monkeypatch)

        assert len(found) == 1
        assert found[0].payload.get("item_id")
        assert found[0].payload.get("space_id") == str(base.space.id)

    async def test_в_payload_есть_куда_прокрутить(self, base, db_session, monkeypatch):
        """Жалоба владельца 12.10: «не могу перейти к тому месту, где эта
        дата». Заметка открывалась целиком — а это 12 554 символа
        распознанной сервисной книжки."""
        await base.note("Paszport ważny do 10.08.2027", title="Паспорт")

        found = await _scan(db_session, monkeypatch)

        # ДД.ММ.ГГГГ: так дату пишут в польских и русских документах, и
        # она переживает рендер, в отличие от разметки исходника.
        assert found[0].payload["find"] == "10.08.2027"

    async def test_срок_из_файла_ведёт_к_вложению(self, base, db_session, monkeypatch):
        """Живой случай 12.10: «Техосмотр Citroën», дата 11.03.2027 есть в
        распознанном тексте ФОТОГРАФИИ и отсутствует в content заметки —
        искать её там нечего, прокручивать надо к самому вложению.

        Поэтому в find кладётся id загрузки, а не дата; различает их
        фронтенд (lib/findInDoc.ts)."""
        note = await base.note("Техосмотр, фото ниже", title="Техосмотр Citroën")
        upload = await base.file_in(note, "Następny przegląd do dnia 11.03.2027", filename="фото.jpg")

        found = await _scan(db_session, monkeypatch)

        assert len(found) == 1
        assert found[0].payload["find"] == str(upload.id), "дата в заметке отсутствует — ведём к файлу"

    async def test_срок_из_самой_заметки_ведёт_к_дате(self, base, db_session, monkeypatch):
        """Контроль к тесту выше: когда срок в тексте заметки, ищем дату."""
        await base.note("Paszport ważny do 10.08.2027", title="Паспорт")

        found = await _scan(db_session, monkeypatch)

        assert found[0].payload["find"] == "10.08.2027"
