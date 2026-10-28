"""Инструменты ассистента, заход 2 (28.10): публичные ссылки, столбцы
таблиц, управление файлами, обзоры (обратные ссылки, недавнее,
документы), отмена отметки и «делает не я» у рутин. Данные вымышленные.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models import Item, Upload, User
from app.routine_schedule import STATUS_PENDING
from app.security import hash_password
from app.tools.files import delete_file, reprocess_file, update_file_text
from app.tools.notes import create_note, get_note
from app.tools.overview import list_backlinks, list_documents, list_recent
from app.tools.registry import ToolContext, ToolError, dispatch, get_tool_definitions
from app.tools.routines import create_routine, defer_dose, mark_dose, reopen_dose
from app.tools.sharing import share_note, unshare_note
from app.tools.tables import create_table, delete_table_column, get_table, update_table_column


async def _space(auth_client, name="Dom", **extra):
    return uuid.UUID((await auth_client.post("/api/spaces", json={"name": name, **extra})).json()["id"])


def _ctx(db_session, test_user, space_id):
    return ToolContext(db=db_session, user_id=test_user.id, space_id=space_id)


async def _upload(db_session, space_id, test_user, filename="skan.jpg", content_type="image/jpeg", transcript=None):
    upload = Upload(space_id=space_id, author_id=test_user.id, filename=filename, content_type=content_type, transcript=transcript)
    db_session.add(upload)
    await db_session.commit()
    return upload


# --- публичные ссылки -----------------------------------------------------


async def test_share_requires_public_pages_space(auth_client, db_session, test_user):
    private = await _space(auth_client, "Osobiste")
    public = await _space(auth_client, "Publiczne", is_public_pages=True)
    ctx = _ctx(db_session, test_user, private)
    note = await create_note(ctx, {"title": "Przepis", "content": "x"})
    with pytest.raises(ToolError, match="Публичные страницы"):
        await share_note(ctx, {"item_id": note["id"]})

    pub = await create_note(ctx, {"title": "Przepis", "content": "x", "space": "Publiczne"})
    result = await share_note(ctx, {"item_id": pub["id"], "password": "sekret", "expires_in_days": 7, "single_use": True})
    assert result["url"].endswith("/s/" + result["url"].rsplit("/", 1)[1]) and "/s/" in result["url"]
    assert result["has_password"] is True and result["single_use"] is True and result["expires_at"]
    item = await db_session.get(Item, uuid.UUID(pub["id"]))
    assert item.is_public and item.share_token and item.space_id == public

    result = await unshare_note(ctx, {"item_id": pub["id"]})
    assert result == {"id": pub["id"], "title": "Przepis", "public": False, "was_public": True}
    await db_session.refresh(item)
    assert not item.is_public and item.share_token is None


# --- столбцы таблиц -------------------------------------------------------


async def test_table_columns_rename_and_delete(auth_client, db_session, test_user):
    ctx = _ctx(db_session, test_user, await _space(auth_client))
    table = await create_table(ctx, {"title": "Wydatki", "columns": ["Data", "Kwota", "Uwagi"], "rows": [{"Data": "01.10", "Kwota": "10", "Uwagi": "kawa"}]})

    result = await update_table_column(ctx, {"table_id": table["id"], "column_name": "kwota", "name": "Kwota PLN"})
    assert result["was"] == "Kwota" and result["name"] == "Kwota PLN"

    result = await delete_table_column(ctx, {"table_id": table["id"], "column_name": "Uwagi"})
    assert result["deleted"] == "Uwagi" and result["columns"] == ["Data", "Kwota PLN"]
    got = await get_table(ctx, {"table_id": table["id"]})
    item = await db_session.get(Item, uuid.UUID(table["id"]))
    assert [c["name"] for c in item.properties["columns"]] == ["Data", "Kwota PLN"]
    assert all(len(r["cells"]) == 2 for r in item.properties["rows"])
    assert "kawa" not in (item.content or "")
    assert got

    with pytest.raises(ToolError, match="есть столбцы"):
        await delete_table_column(ctx, {"table_id": table["id"], "column_name": "Nie ma"})
    with pytest.raises(ToolError, match="get_table"):
        await update_table_column(ctx, {"table_id": table["id"], "column_name": "Data", "name": " "})


# --- файлы ----------------------------------------------------------------


async def test_delete_file_refuses_while_attached(auth_client, db_session, test_user, monkeypatch):
    space_id = await _space(auth_client)
    ctx = _ctx(db_session, test_user, space_id)
    upload = await _upload(db_session, space_id, test_user)
    note = await create_note(ctx, {"title": "Skan", "content": f"![skan](/api/uploads/{upload.id})"})

    with pytest.raises(ToolError, match="Skan"):
        await delete_file(ctx, {"file_id": str(upload.id)})

    item = await db_session.get(Item, uuid.UUID(note["id"]))
    item.content = "bez pliku"
    await db_session.commit()
    result = await delete_file(ctx, {"file_id": str(upload.id)})
    assert result["deleted"] == "skan.jpg"
    assert await db_session.get(Upload, upload.id) is None
    with pytest.raises(ToolError, match="list_files"):
        await delete_file(ctx, {"file_id": str(upload.id)})


async def test_reprocess_and_update_text(auth_client, db_session, test_user, monkeypatch):
    space_id = await _space(auth_client)
    ctx = _ctx(db_session, test_user, space_id)
    queued = []
    monkeypatch.setattr("app.routers.uploads.enqueue_vision", lambda upload_id: queued.append(upload_id))
    upload = await _upload(db_session, space_id, test_user, transcript="Kwota: 1O0 zł")

    result = await reprocess_file(ctx, {"file_id": str(upload.id)})
    assert result["status"] == "pending" and queued == [upload.id]
    await db_session.refresh(upload)
    assert upload.transcription_status == "pending"

    other = await _upload(db_session, space_id, test_user, filename="dane.csv", content_type="text/csv")
    with pytest.raises(ToolError, match="update_file_text"):
        await reprocess_file(ctx, {"file_id": str(other.id)})

    result = await update_file_text(ctx, {"file_id": str(upload.id), "text": "Kwota: 100 zł"})
    assert result["length"] == len("Kwota: 100 zł")
    await db_session.refresh(upload)
    assert upload.transcript == "Kwota: 100 zł"
    with pytest.raises(ToolError, match="get_file"):
        await update_file_text(ctx, {"file_id": str(upload.id), "text": ""})


async def test_files_of_strangers_are_invisible(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    upload = await _upload(db_session, space_id, test_user)
    stranger = User(username="obcy", password_hash=hash_password("x"), name="Obcy")
    db_session.add(stranger)
    await db_session.commit()
    their = ToolContext(db=db_session, user_id=stranger.id, space_id=uuid.uuid4())
    for tool in (delete_file, reprocess_file):
        with pytest.raises(ToolError, match="list_files"):
            await tool(their, {"file_id": str(upload.id)})


# --- обзоры ---------------------------------------------------------------


async def test_backlinks_recent_documents(auth_client, db_session, test_user):
    home = await _space(auth_client, "Osobiste")
    ctx = _ctx(db_session, test_user, home)
    target = await create_note(ctx, {"title": "Cel", "content": "x"})
    linker = await create_note(ctx, {"title": "Źródło", "content": f'<a data-item-id="{target["id"]}">Cel</a>'})
    await create_note(ctx, {"title": "Niezwiązana", "content": "y"})

    back = await list_backlinks(ctx, {"item_id": target["id"]})
    assert [b["title"] for b in back["backlinks"]] == ["Źródło"]
    assert back["backlinks"][0]["url"] == (await get_note(ctx, {"item_id": linker["id"]}))["url"]

    recent = await list_recent(ctx, {"limit": 2})
    assert len(recent["items"]) == 2 and {i["title"] for i in recent["items"]} <= {"Cel", "Źródło", "Niezwiązana"}
    assert all(i["space_name"] == "Osobiste" for i in recent["items"])
    with pytest.raises(ToolError, match="limit"):
        await list_recent(ctx, {"limit": "много"})

    pdf = await _upload(db_session, home, test_user, filename="faktura-2026-09.pdf", content_type="application/pdf")
    await _upload(db_session, home, test_user, filename="kot.jpg", content_type="image/jpeg")  # фото без текста — не документ
    await create_note(ctx, {"title": "Faktury", "content": f"![f](/api/uploads/{pdf.id})"})
    docs = await list_documents(ctx, {})
    assert [d["filename"] for d in docs["documents"]] == ["faktura-2026-09.pdf"]
    assert docs["documents"][0]["file_id"] == str(pdf.id) and docs["documents"][0]["item_title"] == "Faktury"
    assert "series" in docs


# --- рутины: отмена отметки и «делает не я» --------------------------------


async def test_reopen_and_defer(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    ctx = _ctx(db_session, test_user, space_id)
    routine = await create_routine(ctx, {"title": "Krople", "times": ["08:00", "20:00"]})
    with pytest.raises(ToolError, match="нет закрытых"):
        await reopen_dose(ctx, {"routine_id": routine["id"]})

    await mark_dose(ctx, {"routine_id": routine["id"]})
    result = await reopen_dose(ctx, {"routine_id": routine["id"]})
    assert result["reopened"] is True and result["next_at"]
    item = await db_session.get(Item, uuid.UUID(routine["id"]))
    doses = item.properties["doses"]
    assert len(doses) == 1 and doses[0]["status"] == STATUS_PENDING

    result = await defer_dose(ctx, {"routine_id": routine["id"]})
    assert result["deferred"] is True
    await db_session.refresh(item)
    assert [d["id"] for d in item.properties["doses"][0]["deferred_by"]] == [str(test_user.id)]


# --- реестр ---------------------------------------------------------------


async def test_registered_and_grouped(auth_client, db_session, test_user):
    names = {d.name for d in get_tool_definitions()}
    new = {
        "share_note", "unshare_note", "update_table_column", "delete_table_column",
        "delete_file", "reprocess_file", "update_file_text",
        "list_backlinks", "list_recent", "list_documents", "reopen_dose", "defer_dose",
    }
    assert new <= names
    without = {d.name for d in get_tool_definitions({"sharing", "file_management", "tables", "routines"})}
    assert not (without & (new - {"list_backlinks", "list_recent", "list_documents"}))
    ctx = _ctx(db_session, test_user, await _space(auth_client))
    assert "отключён" in (await dispatch("share_note", ctx, {"item_id": "x"}, disabled={"sharing"}))["error"]
