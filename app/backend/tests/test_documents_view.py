"""Сквозной вид «Документы».

Запрос владельца: «как-то возможно отсортировать или пересобрать отдельно
где-то все документы, потому что всё сейчас так раскидано».

Ключевое свойство, которое проверяется здесь, — что это ВИД: ничего не
перемещается, доступы не меняются, сейф не показывается.
"""

from __future__ import annotations

import io

import pytest
import pytest_asyncio

PDF = b"%PDF-1.4 " + b"x" * 300


@pytest_asyncio.fixture
async def base(auth_client):
    async def space(name: str) -> str:
        r = await auth_client.post("/api/spaces", json={"name": name})
        return r.json()["id"]

    async def upload(space_id: str, filename: str, data: bytes = PDF, content_type: str = "application/pdf") -> str:
        r = await auth_client.post(
            f"/api/uploads?space_id={space_id}", files={"file": (filename, io.BytesIO(data), content_type)}
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    from types import SimpleNamespace

    return SimpleNamespace(space=space, upload=upload)


class TestЧтоПопадает:
    async def test_документы_из_всех_спейсов(self, auth_client, base):
        mail = await base.space("Почта")
        personal = await base.space("Личное")
        await base.upload(mail, "ZUS DRA 07-2026.pdf")
        await base.upload(personal, "karta_pobytu.pdf", PDF + b"other")

        got = (await auth_client.get("/api/documents")).json()

        spaces = {d["space_name"] for d in got["documents"]}
        assert spaces == {"Почта", "Личное"}, "вид сквозной — иначе он не решает «всё раскидано»"

    async def test_видно_в_какой_заметке_лежит(self, auth_client, base):
        """Иначе из списка можно только скачать байты, а не попасть к
        документу в контекст."""
        space_id = await base.space("Почта")
        upload_id = await base.upload(space_id, "faktura.pdf")
        note = (await auth_client.post("/api/items", json={"space_id": space_id, "title": "Счёт от бухгалтера", "content": ""})).json()
        await auth_client.patch(f"/api/items/{note['id']}", json={"content": f"см. /api/uploads/{upload_id}"})

        got = (await auth_client.get("/api/documents")).json()
        found = next(d for d in got["documents"] if d["id"] == upload_id)

        assert found["item_title"] == "Счёт от бухгалтера"
        assert found["item_id"] == note["id"]

    async def test_видео_не_документ(self, auth_client, base):
        space_id = await base.space("Личное")
        await base.upload(space_id, "клип.mp4", b"\x00mp4" + b"y" * 200, "video/mp4")

        got = (await auth_client.get("/api/documents")).json()

        assert got["documents"] == []

    async def test_картинка_без_распознанного_текста_не_документ(self, auth_client, base):
        """Иначе список утонет в фотографиях из Telegram."""
        space_id = await base.space("Telegram")
        await base.upload(space_id, "кот.jpg", b"\xff\xd8\xff" + b"z" * 200, "image/jpeg")

        got = (await auth_client.get("/api/documents")).json()

        assert got["documents"] == []

    async def test_скан_с_текстом_документ(self, auth_client, base, db_session):
        import uuid as _uuid

        from app.models import Upload

        space_id = await base.space("Telegram")
        upload_id = await base.upload(space_id, "скан.jpg", b"\xff\xd8\xff" + b"q" * 200, "image/jpeg")
        row = await db_session.get(Upload, _uuid.UUID(upload_id))
        row.transcript = "PESEL ... karta pobytu ..."
        await db_session.commit()

        got = (await auth_client.get("/api/documents")).json()

        assert [d["filename"] for d in got["documents"]] == ["скан.jpg"]


class TestГраницы:
    async def test_сейф_не_показывается(self, auth_client, db_session, test_user):
        """Сервер не видит содержимого сейфа, и показывать «документ,
        который нельзя открыть» бессмысленно.

        Спейс заводим напрямую: через API сейф требует соль и verifier
        (routers/spaces.py), а к этой проверке они отношения не имеют.
        """
        from app.models import Space, SpaceMember, Upload

        vault = Space(name="Сейф", owner_id=test_user.id, is_vault=True)
        db_session.add(vault)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=vault.id, user_id=test_user.id))
        db_session.add(Upload(space_id=vault.id, author_id=test_user.id, filename="паспорт.pdf",
                              content_type="application/pdf"))
        await db_session.commit()

        got = (await auth_client.get("/api/documents")).json()

        assert got["documents"] == []

    async def test_чужие_документы_не_видны(self, auth_client, client, db_session):
        from app.models import EmailInbox, Space, SpaceMember, Upload, User
        from app.security import hash_password

        other = User(username="other@example.com", name="Другой", password_hash=hash_password("x"))
        db_session.add(other)
        await db_session.flush()
        space = Space(name="Чужое", owner_id=other.id)
        db_session.add(space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=space.id, user_id=other.id))
        db_session.add(Upload(space_id=space.id, author_id=other.id, filename="чужой.pdf",
                              content_type="application/pdf"))
        await db_session.commit()

        got = (await auth_client.get("/api/documents")).json()

        assert got["documents"] == []

    async def test_без_входа_не_отдаётся(self, client):
        assert (await client.get("/api/documents")).status_code == 401


class TestСерии:
    async def test_серия_собирается_из_разных_спейсов(self, auth_client, base):
        """Бухгалтерский пакет лежит и в «Почте», и в «Личном» — серия
        одна."""
        mail = await base.space("Почта")
        personal = await base.space("Личное")
        await base.upload(mail, "ZUS DRA 07-2026.pdf", PDF + b"07")
        await base.upload(personal, "ZUS DRA 08-2026.pdf", PDF + b"08")

        got = (await auth_client.get("/api/documents")).json()

        assert len(got["series"]) == 1
        series = got["series"][0]
        assert series["title"] == "ZUS DRA"
        assert [i["period"] for i in series["instalments"]] == ["июль 2026", "август 2026"]
        assert {i["space_name"] for i in series["instalments"]} == {"Почта", "Личное"}

    async def test_одиночный_файл_серии_не_создаёт(self, auth_client, base):
        space_id = await base.space("Почта")
        await base.upload(space_id, "ZUS DRA 07-2026.pdf")

        got = (await auth_client.get("/api/documents")).json()

        assert got["series"] == []
        assert len(got["documents"]) == 1
