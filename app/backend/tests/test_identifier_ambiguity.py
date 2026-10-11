"""Чей это номер.

ЖИВОЙ СЛУЧАЙ 11.10. На прямой вопрос «Какой у меня PESEL?» ассистент
нашёл заметку «PIT Мужа» — совместную налоговую декларацию с номерами
обоих супругов — и назвал первый попавшийся, не тот, который спрашивали.

В базе владельца десять разных PESEL минимум восьми человек: он, жена,
трое прежних владельцев машины, ещё трое из пересылки про ВНЖ.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.identifier_ambiguity import ambiguity_warning, distinct_identifiers
from app.models import Item, Space, SpaceMember, Upload
from app.tools import files as files_tool
from app.tools import notes as notes_tool
from app.tools.registry import ToolContext

MINE = "90010112345"      # 01.01.1990 — дата рождения владельца
SPOUSE = "92071554321"     # 15.07.1992


class TestРазборНомеров:
    def test_находит_оба_номера(self):
        assert distinct_identifiers(f"PESEL {MINE} и {SPOUSE}") == [MINE, SPOUSE]

    def test_номер_по_клеткам(self):
        """В PIT номер печатают по одной цифре в клетке."""
        assert distinct_identifiers("numer PESEL podatnika | 9 2 0 7 1 5 5 4 3 2 1 |") == [SPOUSE]

    def test_повтор_одного_номера_не_неоднозначность(self):
        assert ambiguity_warning(f"{MINE} ... снова {MINE}") is None

    def test_один_номер_молчит(self):
        """В документе с одним номером лишнего поля быть не должно."""
        assert ambiguity_warning(f"Paszport, PESEL {MINE}") is None

    def test_два_номера_предупреждают(self):
        warning = ambiguity_warning(f"{MINE} {SPOUSE}")

        assert warning is not None
        assert "РАЗНЫМ людям" in warning
        assert "не выбирай первый попавшийся" in warning

    @pytest.mark.parametrize("text", [
        "",
        "никаких номеров",
        "дата 10.12.2026 и сумма 73 000",
        "телефон +48 61 111 22 333",
        "12345678901234567890",   # двадцать цифр — не PESEL
    ])
    def test_не_придумывает_номера(self, text):
        assert ambiguity_warning(text) is None


@pytest_asyncio.fixture
async def ctx(db_session, test_user):
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()
    return ToolContext(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="UTC")


class TestЧерезИнструменты:
    async def test_get_note_предупреждает(self, ctx, db_session, test_user):
        item = Item(space_id=ctx.space_id, author_id=test_user.id, material_type="note",
                    title="PIT Мужа", content=f"PESEL podatnika {SPOUSE}\nPESEL małżonka {MINE}",
                    properties={})
        db_session.add(item)
        await db_session.commit()

        result = await notes_tool.get_note(ctx, {"item_id": str(item.id)})

        assert "чьи_номера" in result
        # Содержимое отдаётся как было: предупреждение не заменяет данные.
        assert MINE in result["content"] and SPOUSE in result["content"]

    async def test_get_note_с_одним_номером_не_шумит(self, ctx, db_session, test_user):
        item = Item(space_id=ctx.space_id, author_id=test_user.id, material_type="note",
                    title="Карта побыту", content=f"PESEL {MINE}", properties={})
        db_session.add(item)
        await db_session.commit()

        result = await notes_tool.get_note(ctx, {"item_id": str(item.id)})

        assert "чьи_номера" not in result

    async def test_get_file_предупреждает(self, ctx, db_session, test_user, tmp_path, monkeypatch):
        upload = Upload(space_id=ctx.space_id, author_id=test_user.id, filename="CamScanner.pdf",
                        content_type="application/pdf", transcript=f"{MINE}\n{SPOUSE}",
                        transcription_status="done")
        db_session.add(upload)
        await db_session.flush()
        await db_session.commit()
        monkeypatch.setattr(files_tool, "_path", lambda _id: tmp_path / "нет-файла")

        result = await files_tool.get_file(ctx, {"file_id": str(upload.id)})

        assert "чьи_номера" in result
