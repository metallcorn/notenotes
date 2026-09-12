"""Файлы через инструменты: посмотреть, прочитать, положить.

По MCP нельзя было ни скачать файл, ни отправить новый. Инструментов не
было и у веб-ассистента с Telegram-ботом: ассистент находил заметку, в
которую вставлен скан договора, но прочитать сам скан не мог.
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest_asyncio

from app.core.config import get_settings
from app.models import Item, Space, SpaceMember, Upload, User
from app.security import hash_password
from app.tools import files as files_tool
from app.tools.registry import ToolError

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest_asyncio.fixture
async def base(db_session, test_user):
    space = Space(name="Личное", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    await db_session.commit()

    async def add_file(*, filename="скан.png", content_type="image/png", data=PNG,
                       transcript=None, in_space=None, status="none"):
        target = in_space or space
        upload = Upload(
            space_id=target.id, author_id=target.owner_id, filename=filename,
            content_type=content_type, transcript=transcript, transcription_status=status,
        )
        db_session.add(upload)
        await db_session.flush()
        await db_session.commit()
        path = Path(get_settings().upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / str(upload.id)).write_bytes(data)
        return upload

    async def add_note(content="", title="Заметка"):
        item = Item(space_id=space.id, author_id=test_user.id, title=title,
                    content=content, material_type="note", properties={})
        db_session.add(item)
        await db_session.flush()
        await db_session.commit()
        return item

    ctx = SimpleNamespace(db=db_session, user_id=test_user.id, space_id=space.id, client_timezone="Europe/Warsaw")
    return SimpleNamespace(space=space, ctx=ctx, add_file=add_file, add_note=add_note)


class TestСписок:
    async def test_видно_есть_ли_извлечённый_текст(self, base):
        """Главное в списке: по нему видно, что читать дёшево.

        У 183 файлов из 214 текст уже извлечён — и это самое ценное, что
        в них есть.
        """
        await base.add_file(filename="с_текстом.png", transcript="Договор аренды №12")
        await base.add_file(filename="без_текста.png")

        files = (await files_tool.list_files(base.ctx, {}))["files"]

        by_name = {f["filename"]: f for f in files}
        assert by_name["с_текстом.png"]["text_extracted"] is True
        assert by_name["без_текста.png"]["text_extracted"] is False

    async def test_видно_что_текст_ещё_считается(self, base):
        """Иначе модель решит, что текста нет вовсе, и скажет это человеку."""
        await base.add_file(filename="в_работе.pdf", content_type="application/pdf", status="pending")

        entry = (await files_tool.list_files(base.ctx, {}))["files"][0]

        assert entry["processing"] == "pending"

    async def test_вложения_конкретной_заметки(self, base):
        attached = await base.add_file(filename="вложен.png")
        await base.add_file(filename="посторонний.png")
        note = await base.add_note(content=f"текст ![скан](/api/uploads/{attached.id})")

        files = (await files_tool.list_files(base.ctx, {"item_id": str(note.id)}))["files"]

        assert [f["filename"] for f in files] == ["вложен.png"]

    async def test_файлы_из_сейфа_не_видны(self, base, db_session, test_user):
        vault = Space(name="Сейф", owner_id=test_user.id, is_vault=True)
        db_session.add(vault)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=vault.id, user_id=test_user.id))
        await db_session.commit()
        await base.add_file(filename="паспорт.png", in_space=vault)

        names = [f["filename"] for f in (await files_tool.list_files(base.ctx, {}))["files"]]

        assert "паспорт.png" not in names

    async def test_название_вместо_id_объясняет_что_делать(self, base):
        """Известный режим отказа: модель подставляет название вместо UUID."""
        with __import__("pytest").raises(ToolError) as e:
            await files_tool.list_files(base.ctx, {"item_id": "Договор аренды"})

        assert "search_base" in str(e.value)


class TestЧтение:
    async def test_текст_отдаётся_первым(self, base):
        """На вопрос «что в документе» ответ — текст, а не мегабайт base64."""
        upload = await base.add_file(filename="договор.pdf", content_type="application/pdf",
                                     data=b"%PDF-1.4 ...", transcript="Договор аренды №12 от 1 марта")

        out = await files_tool.get_file(base.ctx, {"file_id": str(upload.id)})

        assert out["text"] == "Договор аренды №12 от 1 марта"

    async def test_картинка_отдаётся_картинкой(self, base):
        """Ради этого в mcp.py и заведён отдельный блок контента: base64 в
        тексте модель увидит как простыню символов, а не изображение."""
        upload = await base.add_file(filename="схема.png")

        out = await files_tool.get_file(base.ctx, {"file_id": str(upload.id)})

        assert out["_mcp_image"]["mime_type"] == "image/png"
        assert base64.b64decode(out["_mcp_image"]["data"]) == PNG

    async def test_pdf_отдаётся_самим_файлом(self, base):
        """Живой случай: человек попросил Клода прислать скан паспорта, и
        тот ответил «нет инструмента для передачи вложений».

        Причина была здесь: первая версия отдавала байты ТОЛЬКО для
        картинок, а у PDF возвращался текст и ссылка — то есть сохранить
        файл клиент не мог физически.
        """
        pdf = b"%PDF-1.4 passport-scan"
        upload = await base.add_file(filename="паспорт.pdf", content_type="application/pdf",
                                     data=pdf, transcript="Паспорт")

        out = await files_tool.get_file(base.ctx, {"file_id": str(upload.id)})

        assert base64.b64decode(out["_mcp_resource"]["data"]) == pdf
        assert out["_mcp_resource"]["mime_type"] == "application/pdf"
        assert out["_mcp_resource"]["filename"] == "паспорт.pdf"
        # Картинкой PDF не притворяется: модель не должна пытаться его
        # «рассмотреть».
        assert "_mcp_image" not in out

    async def test_картинка_идёт_картинкой_а_не_resource(self, base):
        """Разные блоки не формальность: картинку модель рассматривает,
        двоичный файл — сохраняет."""
        upload = await base.add_file(filename="фото.png")

        out = await files_tool.get_file(base.ctx, {"file_id": str(upload.id)})

        assert "_mcp_image" in out
        assert "_mcp_resource" not in out

    async def test_большой_файл_не_лезет_в_ответ(self, base):
        huge = b"\x89PNG" + b"\0" * (files_tool.MAX_INLINE_BYTES + 10)
        upload = await base.add_file(filename="огромная.png", data=huge)

        out = await files_tool.get_file(base.ctx, {"file_id": str(upload.id)})

        assert "_mcp_image" not in out and "_mcp_resource" not in out
        # Ссылка должна быть прямо в подсказке: иначе модель предложит
        # «откройте заметку» вместо того, чтобы дать сам файл.
        assert out["url"] in out["note"]

    async def test_длинная_расшифровка_режется(self, base):
        """Расшифровка часового видео — десятки тысяч слов."""
        upload = await base.add_file(filename="запись.mp4", content_type="video/mp4",
                                     data=b"video", transcript="а" * (files_tool.MAX_TEXT_CHARS + 500))

        out = await files_tool.get_file(base.ctx, {"file_id": str(upload.id)})

        assert len(out["text"]) == files_tool.MAX_TEXT_CHARS
        assert out["text_truncated"] is True

    async def test_чужой_файл_не_прочитать(self, base, db_session):
        other = User(username=f"o_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), name="Чужой")
        db_session.add(other)
        await db_session.flush()
        other_space = Space(name="Чужое", owner_id=other.id)
        db_session.add(other_space)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=other_space.id, user_id=other.id))
        await db_session.commit()
        upload = await base.add_file(filename="чужой.png", in_space=other_space)

        with __import__("pytest").raises(ToolError):
            await files_tool.get_file(base.ctx, {"file_id": str(upload.id)})

    async def test_файл_из_сейфа_не_прочитать(self, base, db_session, test_user):
        """Байты сейфа зашифрованы на клиенте.

        Отдать их модели значит отдать мусор и сделать вид, что это
        документ.
        """
        vault = Space(name="Сейф", owner_id=test_user.id, is_vault=True)
        db_session.add(vault)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=vault.id, user_id=test_user.id))
        await db_session.commit()
        upload = await base.add_file(filename="паспорт.png", in_space=vault)

        with __import__("pytest").raises(ToolError):
            await files_tool.get_file(base.ctx, {"file_id": str(upload.id)})

    async def test_пропавший_с_диска_файл_не_роняет(self, base, db_session):
        upload = await base.add_file(filename="исчез.png")
        (Path(get_settings().upload_dir) / str(upload.id)).unlink()

        out = await files_tool.get_file(base.ctx, {"file_id": str(upload.id)})

        assert "недоступно" in out["note"]


class TestЗагрузка:
    async def test_файл_кладётся_и_возвращает_ссылку(self, base):
        out = await files_tool.upload_file(base.ctx, {
            "filename": "новая.png",
            "content_base64": base64.b64encode(PNG).decode(),
        })

        assert out["filename"] == "новая.png"
        assert out["content_type"] == "image/png"
        assert (Path(get_settings().upload_dir) / out["id"]).read_bytes() == PNG

    async def test_добавляется_в_заметку_ссылкой(self, base):
        """Формат хранения заметок — Markdown, файл ссылкой, не base64."""
        note = await base.add_note(content="Было")

        out = await files_tool.upload_file(base.ctx, {
            "filename": "схема.png",
            "content_base64": base64.b64encode(PNG).decode(),
            "item_id": str(note.id),
        })

        assert out["added_to_note"]
        assert f"![схема.png](/api/uploads/{out['id']})" in note.content
        assert note.content.startswith("Было")

    async def test_мусор_вместо_base64_объясняет_что_не_так(self, base):
        """validate=True обязателен: иначе base64 молча проглатывает мусор
        и на диск ложится обрезанный файл, который потом не открывается."""
        with __import__("pytest").raises(ToolError) as e:
            await files_tool.upload_file(base.ctx, {"filename": "x.png", "content_base64": "это не base64!!!"})

        assert "base64" in str(e.value)

    async def test_слишком_большой_отклоняется(self, base):
        big = base64.b64encode(b"\0" * (files_tool.MAX_UPLOAD_BYTES + 100)).decode()

        with __import__("pytest").raises(ToolError) as e:
            await files_tool.upload_file(base.ctx, {"filename": "огромный.bin", "content_base64": big})

        assert "через приложение" in str(e.value)

    async def test_в_сейф_загрузить_нельзя(self, base, db_session, test_user):
        vault = Space(name="Сейф", owner_id=test_user.id, is_vault=True)
        db_session.add(vault)
        await db_session.flush()
        db_session.add(SpaceMember(space_id=vault.id, user_id=test_user.id))
        await db_session.commit()
        note = Item(space_id=vault.id, author_id=test_user.id, title="В сейфе",
                    content="", material_type="note", properties={})
        db_session.add(note)
        await db_session.flush()
        await db_session.commit()

        with __import__("pytest").raises(ToolError) as e:
            await files_tool.upload_file(base.ctx, {
                "filename": "x.png",
                "content_base64": base64.b64encode(PNG).decode(),
                "item_id": str(note.id),
            })

        assert "сейф" in str(e.value).lower()

    async def test_пустой_файл_отклоняется(self, base):
        with __import__("pytest").raises(ToolError):
            await files_tool.upload_file(base.ctx, {"filename": "пусто.txt", "content_base64": ""})


class TestДоступностьВезде:
    async def test_инструменты_есть_и_у_ассистента_и_по_MCP(self):
        """Вопрос, с которого всё началось: по MCP файл не отправить и не
        скачать. Инструментов не было и у веб-ассистента с ботом."""
        from app.routers.mcp import MCP_EXCLUDED_TOOLS
        from app.tools.registry import get_tool_definitions

        everywhere = {t.name for t in get_tool_definitions()}
        via_mcp = {t.name for t in get_tool_definitions(set(MCP_EXCLUDED_TOOLS))}

        for name in ("list_files", "get_file", "upload_file"):
            assert name in everywhere
            assert name in via_mcp


class TestПоискФайловПоСодержимому:
    async def test_по_описанию_картинки(self, base):
        """Живой случай 12.09: «покажи фото с жабой».

        Клод взял list_files без запроса, получил 20 последних, просмотрел
        8 картинок и заключил, что жаб нет. А их четыре, от 8 августа, с
        «жаба» в описании — в двадцатку не попали. Инструмент подталкивал
        к перебору вместо поиска.
        """
        await base.add_file(filename="file_22.jpg", transcript="Зелёная жаба сидит на листе кувшинки")
        await base.add_file(filename="file_1.jpg", transcript="Инфографика про urząd и wezwanie")

        files = (await files_tool.list_files(base.ctx, {"query": "жаба"}))["files"]

        assert [f["filename"] for f in files] == ["file_22.jpg"]

    async def test_подстрока_ловит_словоформы(self, base):
        """ILIKE, не полнотекст: «жаб» найдёт и «жабы», и «жабой» — у
        to_tsvector('simple') морфологии нет."""
        await base.add_file(filename="a.jpg", transcript="Две жабы у пруда")
        await base.add_file(filename="b.jpg", transcript="Кот")

        files = (await files_tool.list_files(base.ctx, {"query": "жаб"}))["files"]

        assert [f["filename"] for f in files] == ["a.jpg"]

    async def test_по_имени_файла(self, base):
        await base.add_file(filename="polisa_AXA.pdf", content_type="application/pdf", data=b"%PDF")
        await base.add_file(filename="file_3.jpg")

        files = (await files_tool.list_files(base.ctx, {"query": "axa"}))["files"]

        assert [f["filename"] for f in files] == ["polisa_AXA.pdf"]

    async def test_старый_файл_находится_поверх_лимита(self, base):
        """Ради этого поиск и нужен: без него старое вытесняется свежим."""
        old = await base.add_file(filename="жаба_старая.jpg", transcript="жаба")
        # Явно в прошлое: иначе все 26 файлов создаются в одну секунду, и
        # ORDER BY created_at между ними — лотерея (тест так и упал).
        from datetime import datetime, timedelta, timezone

        old.created_at = datetime.now(timezone.utc) - timedelta(days=30)
        await base.ctx.db.commit()
        for i in range(25):
            await base.add_file(filename=f"свежий_{i}.jpg")

        without = (await files_tool.list_files(base.ctx, {}))["files"]
        with_query = (await files_tool.list_files(base.ctx, {"query": "жаба"}))["files"]

        assert str(old.id) not in {f["id"] for f in without}
        assert [f["id"] for f in with_query] == [str(old.id)]

    async def test_внутри_заметки_тоже_фильтрует(self, base):
        frog = await base.add_file(filename="f1.jpg", transcript="жаба")
        cat = await base.add_file(filename="f2.jpg", transcript="кот")
        note = await base.add_note(content=f"![a](/api/uploads/{frog.id}) ![b](/api/uploads/{cat.id})")

        files = (await files_tool.list_files(base.ctx, {"item_id": str(note.id), "query": "жаба"}))["files"]

        assert [f["id"] for f in files] == [str(frog.id)]

    async def test_синонимы_через_смысловой_поиск(self, base, monkeypatch):
        """Живая база: на «жаба» подстрока нашла один файл из четырёх —
        остальные описаны как «лягушка», «лягушонок». Синонимы подстрокой
        не взять; смысловой поиск у нас есть, и описания картинок в
        заметки попадают."""
        frog = await base.add_file(filename="file_22.jpg", transcript="Лягушонок сидит на кувшинке")
        note = await base.add_note(content=f"Фото\n\n![](/api/uploads/{frog.id})\n\nЛягушонок сидит на кувшинке")

        async def fake_semantic(db, user_id, query, **kw):
            return [(note, 0.77, "Лягушонок")]

        monkeypatch.setattr("app.embeddings.search_semantic", fake_semantic)

        files = (await files_tool.list_files(base.ctx, {"query": "жаба"}))["files"]

        assert [f["filename"] for f in files] == ["file_22.jpg"]

    async def test_подстрочные_совпадения_идут_первыми(self, base, monkeypatch):
        exact = await base.add_file(filename="a.jpg", transcript="жаба")
        fuzzy = await base.add_file(filename="b.jpg", transcript="лягушка")
        note = await base.add_note(content=f"![](/api/uploads/{fuzzy.id})")

        async def fake_semantic(db, user_id, query, **kw):
            return [(note, 0.8, "")]

        monkeypatch.setattr("app.embeddings.search_semantic", fake_semantic)

        files = (await files_tool.list_files(base.ctx, {"query": "жаба"}))["files"]

        assert [f["id"] for f in files] == [str(exact.id), str(fuzzy.id)]

    async def test_падение_эмбеддера_не_роняет_поиск(self, base, monkeypatch):
        await base.add_file(filename="a.jpg", transcript="жаба")

        async def explode(*a, **kw):
            raise RuntimeError("эмбеддер недоступен")

        monkeypatch.setattr("app.embeddings.search_semantic", explode)

        files = (await files_tool.list_files(base.ctx, {"query": "жаба"}))["files"]

        assert [f["filename"] for f in files] == ["a.jpg"]

    def test_описание_велит_искать_а_не_листать(self):
        d = files_tool.LIST_FILES.description
        assert "query" in d and "жаб" in d
