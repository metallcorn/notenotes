"""Один и тот же файл не должен лечь в базу дважды.

ЗАМЕР 12.10: из 355 файлов 71 — побайтовый дубликат (49 групп, каждый
пятый). Почти всё — месячные пакеты от бухгалтера, приходящие повторно:
«ZUS DRA 07-2026.pdf» лежал в пяти экземплярах с 19.08 по 01.10, в
спейсах «Почта» и «Личное». Сравнивать их было нечем — ни хэша, ни
размера в таблице не существовало.
"""

from __future__ import annotations

import hashlib
import io
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import Space, SpaceMember, Upload
from app.upload_dedup import content_hash, find_anywhere, find_in_space, link_or_write

PACK = b"%PDF-1.4 ZUS DRA 07-2026 ..." + b"x" * 2000


class TestХэш:
    def test_совпадает_с_sha256(self):
        assert content_hash(PACK) == hashlib.sha256(PACK).hexdigest()

    def test_разные_байты_разный_хэш(self):
        assert content_hash(PACK) != content_hash(PACK + b"!")


class TestЖёсткаяСсылка:
    def test_ссылается_на_существующий(self, tmp_path):
        source = tmp_path / "a"
        source.write_bytes(PACK)
        dest = tmp_path / "b"

        assert link_or_write(source, dest, PACK) is True
        assert dest.read_bytes() == PACK
        assert source.stat().st_ino == dest.stat().st_ino, "это должна быть одна и та же inode"

    def test_без_источника_просто_пишет(self, tmp_path):
        dest = tmp_path / "b"

        assert link_or_write(None, dest, PACK) is False
        assert dest.read_bytes() == PACK

    def test_пропавший_источник_не_роняет(self, tmp_path):
        """Экономия диска не стоит того, чтобы из-за неё потерялся файл."""
        dest = tmp_path / "b"

        assert link_or_write(tmp_path / "нет-такого", dest, PACK) is False
        assert dest.read_bytes() == PACK

    def test_удаление_одного_имени_не_уносит_второе(self, tmp_path):
        """Главный довод за ссылку вместо общей строки в БД."""
        source = tmp_path / "a"
        source.write_bytes(PACK)
        dest = tmp_path / "b"
        link_or_write(source, dest, PACK)

        source.unlink()

        assert dest.read_bytes() == PACK


@pytest_asyncio.fixture
async def spaces(db_session, test_user):
    made = []
    for name in ("Почта", "Личное"):
        space = Space(name=name, owner_id=test_user.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
        made.append(space)
    await db_session.commit()
    return made


class TestПоискБлизнеца:
    async def test_находит_в_своём_спейсе(self, db_session, test_user, spaces):
        mail, personal = spaces
        digest = content_hash(PACK)
        db_session.add(Upload(space_id=mail.id, author_id=test_user.id, filename="ZUS DRA 07-2026.pdf",
                              content_type="application/pdf", sha256=digest, size_bytes=len(PACK)))
        await db_session.commit()

        assert (await find_in_space(db_session, mail.id, digest)) is not None
        assert (await find_in_space(db_session, personal.id, digest)) is None, "чужой спейс — не наше дело"
        assert (await find_anywhere(db_session, digest)) is not None

    async def test_без_хэша_не_мешает(self, db_session, test_user, spaces):
        """У файлов, залитых до правки, sha256 пуст — они не должны
        схлопываться друг с другом как «одинаковые»."""
        mail, _ = spaces
        for _ in range(2):
            db_session.add(Upload(space_id=mail.id, author_id=test_user.id, filename="старый.pdf",
                                  content_type="application/pdf"))
        await db_session.commit()

        assert (await find_in_space(db_session, mail.id, content_hash(PACK))) is None


class TestЧерезПриложение:
    async def test_повторная_загрузка_отдаёт_тот_же_файл(self, auth_client):
        space_id = (await auth_client.post("/api/spaces", json={"name": "Почта"})).json()["id"]

        def send():
            return auth_client.post(
                f"/api/uploads?space_id={space_id}",
                files={"file": ("ZUS DRA 07-2026.pdf", io.BytesIO(PACK), "application/pdf")},
            )

        first = await send()
        second = await send()

        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["id"] == second.json()["id"], "второй раз должен вернуться тот же файл"

    async def test_в_базе_остаётся_одна_запись(self, auth_client, db_session):
        space_id = (await auth_client.post("/api/spaces", json={"name": "Почта"})).json()["id"]
        for _ in range(3):
            await auth_client.post(
                f"/api/uploads?space_id={space_id}",
                files={"file": ("ZUS DRA 07-2026.pdf", io.BytesIO(PACK), "application/pdf")},
            )

        rows = (await db_session.execute(
            select(Upload).where(Upload.space_id == uuid.UUID(space_id)))).scalars().all()

        assert len(rows) == 1
        assert rows[0].sha256 == content_hash(PACK)
        assert rows[0].size_bytes == len(PACK)

    async def test_другой_файл_с_тем_же_именем_не_схлопывается(self, auth_client):
        """Имя врёт: «image001.jpg» приходит от разных писем и это разные
        картинки. Решает содержимое, а не имя."""
        space_id = (await auth_client.post("/api/spaces", json={"name": "Почта"})).json()["id"]

        first = await auth_client.post(f"/api/uploads?space_id={space_id}",
                                       files={"file": ("image001.jpg", io.BytesIO(b"aaa" * 100), "image/jpeg")})
        second = await auth_client.post(f"/api/uploads?space_id={space_id}",
                                        files={"file": ("image001.jpg", io.BytesIO(b"bbb" * 100), "image/jpeg")})

        assert first.json()["id"] != second.json()["id"]

    async def test_тот_же_файл_в_другом_спейсе_заводится_отдельно(self, auth_client):
        """Строка своя — иначе пришлось бы отдавать одну запись из двух
        спейсов, то есть ломать проверку доступа по space_id."""
        first_space = (await auth_client.post("/api/spaces", json={"name": "Почта"})).json()["id"]
        second_space = (await auth_client.post("/api/spaces", json={"name": "Личное"})).json()["id"]

        a = await auth_client.post(f"/api/uploads?space_id={first_space}",
                                   files={"file": ("ZUS.pdf", io.BytesIO(PACK), "application/pdf")})
        b = await auth_client.post(f"/api/uploads?space_id={second_space}",
                                   files={"file": ("ZUS.pdf", io.BytesIO(PACK), "application/pdf")})

        assert a.json()["id"] != b.json()["id"]

    async def test_повтор_отдаёт_уже_извлечённый_текст(self, auth_client, db_session):
        """Повторно обрабатывать файл незачем — это и деньги провайдера, и
        очередь на 4 ГБ VPS, и риск перезаписать текст пустотой."""
        space_id = (await auth_client.post("/api/spaces", json={"name": "Почта"})).json()["id"]
        first = await auth_client.post(f"/api/uploads?space_id={space_id}",
                                       files={"file": ("скан.pdf", io.BytesIO(PACK), "application/pdf")})
        upload = await db_session.get(Upload, uuid.UUID(first.json()["id"]))
        upload.transcript = "распознанный текст из прошлого раза"
        await db_session.commit()

        again = await auth_client.post(f"/api/uploads?space_id={space_id}",
                                       files={"file": ("скан.pdf", io.BytesIO(PACK), "application/pdf")})

        assert again.json()["pdf_text"] == "распознанный текст из прошлого раза"
        assert again.json()["pdf_ocr_queued"] is False
