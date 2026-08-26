"""Только детерминированная (без LLM) часть dialogs.py — создание/список/
чтение/удаление сообщений напрямую работают с БД. Собственно отправка
сообщения ассистенту (POST /{dialog_id}/messages -> run_dialog_turn) дёргает
реальный LLM-провайдер (Mistral/Gemini/Groq) — платно и недетерминированно,
сознательно не покрыта тестами (см. tests/README.md)."""
import uuid


async def _make_space(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Dialogs"})
    return r.json()["id"]


async def test_create_list_get_dialog(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id, "title": "Chat"})
    assert r.status_code == 201
    dialog_id = r.json()["id"]

    r = await auth_client.get("/api/dialogs")
    assert r.status_code == 200 and any(d["id"] == dialog_id for d in r.json())

    r = await auth_client.get(f"/api/dialogs/{dialog_id}")
    assert r.status_code == 200 and r.json()["title"] == "Chat"


async def test_dialog_not_created_in_vault_space(auth_client):
    r = await auth_client.post(
        "/api/spaces", json={"name": "V", "is_vault": True, "vault_salt": "s", "vault_verifier": "v"}
    )
    space_id = r.json()["id"]
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id})
    assert r.status_code == 404


async def test_scoped_dialog_for_item(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "Note", "content": "x"})
    item_id = r.json()["id"]

    r = await auth_client.post("/api/dialogs", json={"scoped_item_id": item_id, "selection": "some text"})
    assert r.status_code == 201
    assert "Note" in r.json()["title"]

    r = await auth_client.get(f"/api/dialogs/scoped/{item_id}")
    assert r.status_code == 200 and len(r.json()) == 1


async def test_delete_message_from_dialog(auth_client, db_session, test_user):
    from app.models import Item

    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id})
    assert r.status_code == 201, r.text
    dialog_id = r.json()["id"]

    item = await db_session.get(Item, uuid.UUID(dialog_id))
    message_id = str(uuid.uuid4())
    messages = [{"id": message_id, "role": "user", "content": "Привет"}]
    item.properties = {**item.properties, "messages": messages}
    await db_session.commit()

    r = await auth_client.delete(f"/api/dialogs/{dialog_id}/messages/{message_id}")
    assert r.status_code == 200
    assert r.json()["messages"] == []


async def test_delete_nonexistent_message_404(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id})
    assert r.status_code == 201, r.text
    dialog_id = r.json()["id"]
    r = await auth_client.delete(f"/api/dialogs/{dialog_id}/messages/{uuid.uuid4()}")
    assert r.status_code == 404


# --- scoped_folder_id: "Обсудить с ассистентом" на уровне папки -------------

async def test_scoped_dialog_for_folder(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "Авто"})
    folder_id = r.json()["id"]

    r = await auth_client.post("/api/dialogs", json={"scoped_folder_id": folder_id})
    assert r.status_code == 201
    assert "Авто" in r.json()["title"]

    r = await auth_client.get(f"/api/dialogs/scoped-folder/{folder_id}")
    assert r.status_code == 200 and len(r.json()) == 1


async def test_scoped_folder_dialog_not_created_for_nonexistent_folder(auth_client):
    await _make_space(auth_client)
    r = await auth_client.post("/api/dialogs", json={"scoped_folder_id": str(uuid.uuid4())})
    assert r.status_code == 404


async def test_scoped_folder_dialog_not_created_in_vault_space(auth_client):
    r = await auth_client.post(
        "/api/spaces", json={"name": "V", "is_vault": True, "vault_salt": "s", "vault_verifier": "v"}
    )
    vault_space_id = r.json()["id"]
    r = await auth_client.post("/api/folders", json={"space_id": vault_space_id, "name": "Секреты"})
    folder_id = r.json()["id"]

    r = await auth_client.post("/api/dialogs", json={"scoped_folder_id": folder_id})
    assert r.status_code == 404


async def test_scoped_folder_dialog_requires_space_access(auth_client, _client_factory, db_session):
    from app.models import User
    from app.security import create_session_token, hash_password

    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "Авто"})
    folder_id = r.json()["id"]

    outsider = User(username="dialog_folder_outsider", password_hash=hash_password("x"), name="Outsider")
    db_session.add(outsider)
    await db_session.flush()
    client = _client_factory()
    client.cookies.set("notenotes_session", create_session_token(outsider.id))

    r = await client.post("/api/dialogs", json={"scoped_folder_id": folder_id})
    assert r.status_code == 404  # ensure_space_access прячет чужие папки за 404, не 403


async def test_list_dialogs_excludes_scoped_folder_dialogs(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "Авто"})
    folder_id = r.json()["id"]
    r = await auth_client.post("/api/dialogs", json={"scoped_folder_id": folder_id})
    scoped_dialog_id = r.json()["id"]

    r = await auth_client.post("/api/dialogs", json={"space_id": space_id, "title": "Обычный чат"})
    assert r.status_code == 201

    r = await auth_client.get("/api/dialogs")
    ids = [d["id"] for d in r.json()]
    assert scoped_dialog_id not in ids


async def test_scoped_folder_dialogs_list_only_this_folder(auth_client):
    space_id = await _make_space(auth_client)
    r1 = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "Авто"})
    folder1_id = r1.json()["id"]
    r2 = await auth_client.post("/api/folders", json={"space_id": space_id, "name": "Работа"})
    folder2_id = r2.json()["id"]

    r = await auth_client.post("/api/dialogs", json={"scoped_folder_id": folder1_id})
    dialog1_id = r.json()["id"]
    await auth_client.post("/api/dialogs", json={"scoped_folder_id": folder2_id})

    r = await auth_client.get(f"/api/dialogs/scoped-folder/{folder1_id}")
    ids = [d["id"] for d in r.json()]
    assert ids == [dialog1_id]


# --- _build_folder_context: чистая функция, без БД/LLM -----------------------

def test_build_folder_context_lists_items_with_previews():
    from app.models import Folder, Item
    from app.routers.dialogs import _build_folder_context

    folder = Folder(id=uuid.uuid4(), space_id=uuid.uuid4(), parent_id=None, name="Авто")
    items = [
        Item(id=uuid.uuid4(), title="ТО пройдено", content="Заменили масло и фильтры 12 августа"),
        Item(id=uuid.uuid4(), title="Страховка", content="ОСАГО оплачено до конца года"),
    ]

    ctx = _build_folder_context(folder, items)

    assert "«Авто»" in ctx
    assert "(2)" in ctx
    assert "ТО пройдено" in ctx
    assert "Заменили масло" in ctx
    assert "Страховка" in ctx
    assert "ОСАГО оплачено" in ctx


def test_build_folder_context_empty_folder_does_not_crash():
    from app.models import Folder
    from app.routers.dialogs import _build_folder_context

    folder = Folder(id=uuid.uuid4(), space_id=uuid.uuid4(), parent_id=None, name="Пусто")
    ctx = _build_folder_context(folder, [])
    assert "(0)" in ctx
    assert "не показаны целиком" not in ctx


def test_build_folder_context_truncates_when_over_budget_and_notes_remainder():
    from app.models import Folder, Item
    from app.routers.dialogs import _build_folder_context

    folder = Folder(id=uuid.uuid4(), space_id=uuid.uuid4(), parent_id=None, name="Авто")
    # Превью каждой заметки само по себе обрезано до 300 симв (см.
    # _FOLDER_CONTEXT_PREVIEW_CHARS) — контент длиннее не раздувает бюджет
    # сам по себе, нужно МНОГО заметок, а не несколько больших, чтобы
    # реально упереться в общий потолок в 6000 симв.
    items = [
        Item(id=uuid.uuid4(), title=f"Заметка {i}", content="x" * 5000)
        for i in range(30)
    ]

    ctx = _build_folder_context(folder, items)

    assert "Заметка 0" in ctx
    assert "Заметка 29" not in ctx
    assert "не показаны целиком" in ctx
    assert "get_note/search_base" in ctx


# --- Сжатие истории (app/dialog_compaction.py) -------------------------------


def _msg(role, content="", **extra):
    return {"id": str(uuid.uuid4()), "role": role, "content": content, "created_at": "2026-08-25T00:00:00+00:00", **extra}


async def _seed_dialog_with_messages(auth_client, db_session, count, with_tool_pair=False):
    from app.models import Item

    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id})
    dialog_id = r.json()["id"]
    item = await db_session.get(Item, uuid.UUID(dialog_id))

    messages = []
    if with_tool_pair:
        call_id = str(uuid.uuid4())
        messages += [
            _msg("user", "Найди заметку про кота"),
            _msg("assistant", "", tool_calls=[{"id": call_id, "name": "get_note", "arguments": {}}]),
            _msg("tool", '{"title": "Кот"}', tool_call_id=call_id, name="get_note"),
            _msg("assistant", "Нашёл заметку «Кот»"),
        ]
    for i in range(count - len(messages)):
        messages.append(_msg("user" if i % 2 == 0 else "assistant", f"Сообщение {i}"))

    item.properties = {**item.properties, "messages": messages}
    await db_session.commit()
    return dialog_id, messages


def _patch_llm_key(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_api_key", "test-key")


def _patch_summarize(monkeypatch, summary="Итоговая сводка разговора"):
    async def fake_summarize_records(client, old_records):
        return summary

    monkeypatch.setattr("app.routers.dialogs.summarize_records", fake_summarize_records)
    return summary


async def test_compact_dialog_replaces_old_messages_with_summary(auth_client, db_session, test_user, monkeypatch):
    _patch_llm_key(monkeypatch)
    summary = _patch_summarize(monkeypatch)
    dialog_id, messages = await _seed_dialog_with_messages(auth_client, db_session, 30)

    r = await auth_client.post(f"/api/dialogs/{dialog_id}/compact", json={})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["messages"][0]["is_summary"] is True
    assert body["messages"][0]["content"] == summary
    assert len(body["compaction_snapshots"]) == 1
    snapshot = body["compaction_snapshots"][0]
    assert snapshot["id"] == body["messages"][0]["snapshot_id"]
    assert snapshot["message_count"] == len(messages) - (len(body["messages"]) - 1)


async def test_compact_dialog_too_short_returns_400(auth_client, db_session, test_user, monkeypatch):
    _patch_llm_key(monkeypatch)
    _patch_summarize(monkeypatch)
    dialog_id, _ = await _seed_dialog_with_messages(auth_client, db_session, 5)

    r = await auth_client.post(f"/api/dialogs/{dialog_id}/compact", json={})
    assert r.status_code == 400


async def test_compact_dialog_without_llm_key_returns_400(auth_client, db_session, test_user, monkeypatch):
    from app.core.config import get_settings

    # Реальный ключ приходит в тестовый контейнер из secrets/app.env (тот
    # же env_file, что у прод-сервиса) — дефолт тут НЕ пустой, надо явно
    # погасить, иначе сработает настоящий сетевой вызов вместо этой ветки.
    monkeypatch.setattr(get_settings(), "llm_api_key", "")
    dialog_id, _ = await _seed_dialog_with_messages(auth_client, db_session, 30)
    r = await auth_client.post(f"/api/dialogs/{dialog_id}/compact", json={})
    assert r.status_code == 400


async def test_compact_dialog_requires_space_access(auth_client, _client_factory, db_session, test_user, monkeypatch):
    from app.models import User
    from app.security import create_session_token, hash_password

    _patch_llm_key(monkeypatch)
    _patch_summarize(monkeypatch)
    dialog_id, _ = await _seed_dialog_with_messages(auth_client, db_session, 30)

    outsider = User(username="compact_outsider", password_hash=hash_password("x"), name="Outsider")
    db_session.add(outsider)
    await db_session.flush()
    client = _client_factory()
    client.cookies.set("notenotes_session", create_session_token(outsider.id))

    r = await client.post(f"/api/dialogs/{dialog_id}/compact", json={})
    assert r.status_code == 404


async def test_revert_compaction_restores_exact_messages(auth_client, db_session, test_user, monkeypatch):
    _patch_llm_key(monkeypatch)
    _patch_summarize(monkeypatch)
    dialog_id, original_messages = await _seed_dialog_with_messages(
        auth_client, db_session, 30, with_tool_pair=True
    )

    r = await auth_client.post(f"/api/dialogs/{dialog_id}/compact", json={})
    assert r.status_code == 200, r.text
    snapshot_id = r.json()["messages"][0]["snapshot_id"]

    r = await auth_client.post(f"/api/dialogs/{dialog_id}/compactions/{snapshot_id}/revert")
    assert r.status_code == 200, r.text
    restored = r.json()["messages"]

    assert [m["id"] for m in restored] == [m["id"] for m in original_messages]
    assert [m["content"] for m in restored] == [m["content"] for m in original_messages]
    tool_msg = next(m for m in restored if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == next(m for m in original_messages if m["role"] == "tool")["tool_call_id"]
    assert r.json()["compaction_snapshots"] == []


async def test_revert_nonexistent_snapshot_404(auth_client, db_session, test_user):
    dialog_id, _ = await _seed_dialog_with_messages(auth_client, db_session, 5)
    r = await auth_client.post(f"/api/dialogs/{dialog_id}/compactions/{uuid.uuid4()}/revert")
    assert r.status_code == 404


def test_scoped_tool_names_include_delivery_tracking():
    # Реальный найденный случай: попросил в scoped-чате прямо в заметке
    # добавить виджет отслеживания — track_delivery/insert_delivery_block
    # были доступны только глобальному ассистенту, scoped откатывался на
    # generic web-тулы и упирался в антибот. Пропуск при добавлении этих
    # тулов (Этап 1/2 этой же сессии) был оверсайтом, не намеренным
    # ограничением — этот тест защищает от повторения при будущих правках.
    from app.routers.dialogs import _SCOPED_TOOL_NAMES

    assert "track_delivery" in _SCOPED_TOOL_NAMES
    assert "insert_delivery_block" in _SCOPED_TOOL_NAMES


def test_scoped_tool_names_include_compacted_history_read():
    from app.routers.dialogs import _SCOPED_TOOL_NAMES

    assert "get_compacted_history" in _SCOPED_TOOL_NAMES
