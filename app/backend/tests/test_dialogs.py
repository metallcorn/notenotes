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


async def test_two_sequential_properties_commits_with_mutated_shared_list_both_persist(auth_client, db_session):
    """Реальный найденный баг (не через run_dialog_turn — тот бьёт в
    настоящий LLM, здесь чистый repro механизма): если item.properties
    присваивается ДВАЖДЫ за один ход с тем же (мутируемым между
    присваиваниями) list-объектом в значении "messages", SQLAlchemy не
    видит второе присваивание как изменение JSONB-колонки и не шлёт по
    нему апдейт — сохраняется только первый коммит. Ответ ассистента,
    дописанный ПОСЛЕ раннего коммита реплики пользователя (см.
    run_dialog_turn), от этого исчезал целиком, хотя реально
    генерировался. Фикс — list(records) (копия) при каждом присваивании,
    не сам объект по ссылке."""
    from app.models import Item

    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id})
    dialog_id = uuid.UUID(r.json()["id"])
    item = await db_session.get(Item, dialog_id)

    records: list[dict] = []
    records.append({"id": "m1", "role": "user", "content": "первое сообщение"})
    item.properties = {**item.properties, "messages": list(records)}
    await db_session.commit()

    # Мутируем ТОТ ЖЕ list-объект (не переприсваиваем переменную records) —
    # именно так это происходит в run_dialog_turn: records.append(...) в
    # цикле после раннего коммита.
    records.append({"id": "m2", "role": "assistant", "content": "второй ответ"})
    item.properties = {**item.properties, "messages": list(records)}
    await db_session.commit()

    # Читаем СВЕЖИМ запросом, не через тот же ORM-объект (expire_on_commit=False
    # иначе замаскировал бы баг — item.properties в Python-памяти и так уже
    # содержит оба сообщения, вопрос именно в том, что реально дошло до БД).
    db_session.expire_all()
    fresh = await db_session.get(Item, dialog_id)
    assert len(fresh.properties["messages"]) == 2
    assert fresh.properties["messages"][1]["content"] == "второй ответ"


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


def test_calendar_reminders_tools_are_core_regardless_of_keywords():
    # Реальный найденный случай: "Какие у меня дела на сегодня?" не задело
    # НИ ОДНО ключевое слово старой категории calendar_reminders —
    # list_reminders не попадал в набор тулов вообще, модель откатывалась
    # на search_base и отвечала выдуманными "делами" из содержимого
    # случайно найденных заметок, хотя реальных напоминаний на сегодня не
    # было ни одного. calendar_reminders теперь core — тест защищает от
    # повторного скатывания в keyword-гейтинг для этой группы.
    from app.routers.dialogs import _CORE_TOOL_NAMES, _relevant_tool_names

    for name in ("create_calendar_event", "create_reminder", "list_reminders", "resolve_reminder"):
        assert name in _CORE_TOOL_NAMES

    all_names = {"list_reminders", "search_base", "web_search"}
    relevant = _relevant_tool_names(all_names, "Какие у меня дела на сегодня?", set())
    assert "list_reminders" in relevant
    assert "web_search" not in relevant  # не задело web-категорию — не должен попасть


def test_run_python_is_core_regardless_of_keywords():
    # Реальный найденный случай (бенчмарк моделей на реальных вопросах
    # пользователя): "через 48 дней от сегодня какой будет день недели?" —
    # не задело ни одно ключевое слово старой категории "utility"
    # ("посчита", "сумм", "вычисли" и т.п.), run_python не попадал в набор
    # тулов вообще, все три проверенных модели (small/medium/large) считали
    # дату в уме и ошибались. run_python теперь core.
    from app.routers.dialogs import _CORE_TOOL_NAMES, _relevant_tool_names

    assert "run_python" in _CORE_TOOL_NAMES

    all_names = {"run_python", "search_base", "web_search"}
    relevant = _relevant_tool_names(all_names, "какой день недели будет через 48 дней от сегодня?", set())
    assert "run_python" in relevant
    assert "web_search" not in relevant  # не задело web-категорию — не должен попасть


# --- _strip_unverified_links: реальная жалоба "не кликабельные ссылки" ----
# Промпт один не удерживает модель от выдумывания правдоподобных URL —
# проверено дважды на реальном разговоре (calendar.google.com с придуманными
# координатами, facebook.com/<похожее на название>). Код должен резать
# и markdown-, и голые ссылки, если их не было ни в одном результате тула.

def test_strip_unverified_links_keeps_verified_markdown_link():
    from app.routers.dialogs import _strip_unverified_links

    text = "Вот страница: [SaleMuzyczne](https://www.facebook.com/salaprobexample)"
    result = _strip_unverified_links(text, {"https://www.facebook.com/salaprobexample"})
    assert "[SaleMuzyczne](https://www.facebook.com/salaprobexample)" in result


def test_strip_unverified_links_strips_fabricated_markdown_link():
    from app.routers.dialogs import _strip_unverified_links

    text = "Вот страница: [SaleMuzyczne](https://www.facebook.com/salemuzyczne.pl)"
    result = _strip_unverified_links(text, {"https://www.facebook.com/salaprobexample"})
    assert "https://www.facebook.com/salemuzyczne.pl" not in result
    assert "SaleMuzyczne" in result  # текст ссылки остаётся, просто без URL


def test_strip_unverified_links_keeps_verified_bare_url():
    from app.routers.dialogs import _strip_unverified_links

    text = "facebook.com тут: https://www.facebook.com/salaprobexample"
    result = _strip_unverified_links(text, {"https://www.facebook.com/salaprobexample"})
    assert "https://www.facebook.com/salaprobexample" in result


def test_strip_unverified_links_neutralizes_fabricated_bare_url():
    # Реальный найденный случай: web_search не нашёл нужную страницу, модель
    # на прямой повторный вопрос всё равно ответила ГОЛЫМ URL (не markdown-
    # ссылкой) — _MARKDOWN_LINK_RE такое не видит вообще, тут отдельная
    # проверка на голые URL.
    from app.routers.dialogs import _strip_unverified_links

    text = "https://www.facebook.com/salemuzyczne.pl"
    result = _strip_unverified_links(text, {"https://www.facebook.com/salaprobexample"})
    assert "https://www.facebook.com/salemuzyczne.pl" not in result
    assert "не подтверждена" in result


def test_strip_unverified_links_bare_url_inside_verified_markdown_link_untouched():
    # Регрессия: голая проверка после markdown-прохода не должна портить
    # уже сохранённую верифицированную markdown-ссылку — URL внутри неё
    # тоже "голый" с точки зрения _BARE_URL_RE, должен остаться как есть.
    from app.routers.dialogs import _strip_unverified_links

    text = "[Страница](https://www.facebook.com/salaprobexample)"
    result = _strip_unverified_links(text, {"https://www.facebook.com/salaprobexample"})
    assert result == text


def test_strip_unverified_links_strips_fabricated_custom_scheme():
    # Пойман живьём в ролплей-прогоне (magistral, сценарий новичка): модель
    # ответила "Готово!" без единого вызова тула и выдала кнопку с
    # выдуманной схемой notenotes:// — старый шаблон с https? её не видел,
    # и фальшивая кнопка доезжала до пользователя кликабельной.
    from app.routers.dialogs import _strip_unverified_links

    text = "Список создан. [Открыть «Покупки»](notenotes://list)"
    result = _strip_unverified_links(text, set())
    assert "notenotes://list" not in result
    assert "Открыть «Покупки»" in result


# --- _looks_like_action_request / _looks_like_false_completion_claim ------
# Реальный найденный случай (ролплей-тест длинного диалога, 2026-09-03):
# на просьбу "перенеси данные из заметки X в таблицу Y" модель прочитала
# исходную заметку и тут же ответила "Готово, все записи добавлены" — не
# вызвав НИ ОДНОГО изменяющего тула. Повторная проверка ("точно добавил?")
# снова не тронула таблицу и повторила ту же ложь. Обнаружилось только
# спустя несколько реплик, когда пользователь сам потребовал показать
# содержимое таблицы.

def test_looks_like_action_request_true_for_imperative_verbs():
    from app.routers.dialogs import _looks_like_action_request

    assert _looks_like_action_request("Добавь данные из заметки в таблицу")
    assert _looks_like_action_request("Перенеси записи из сервисной книжки")
    assert _looks_like_action_request("создай список покупок")


def test_looks_like_action_request_false_for_plain_question():
    from app.routers.dialogs import _looks_like_action_request

    assert not _looks_like_action_request("Какие тормозные диски подходят на мою машину?")
    assert not _looks_like_action_request("Когда заканчивается страховка PZU?")


def test_looks_like_action_request_sees_request_from_earlier_turn():
    # Детектор ложного "готово" смотрит не на текущее сообщение, а на
    # склейку последних реплик пользователя (recent_user_text) — ровно по
    # той же причине, что и _named_list_owner_mismatch. Пойман живьём в
    # ролплей-прогоне сценария новичка: "а можно просто записать, что мне
    # нужно купить?" → ассистент переспросил про папку → "может, без
    # папки?" → "Хорошо, создаю список без папки. Готово!" без единого
    # вызова тула. В ПОСЛЕДНЕМ сообщении просьбы о действии нет, и по нему
    # одному детектор молчал.
    from app.routers.dialogs import _looks_like_action_request

    last_message = "Ой, а что это за папки? Я не понимаю. Может, без папки?"
    assert not _looks_like_action_request(last_message)

    recent_user_text = " ".join([
        "а можно просто записать, что мне нужно купить?",
        last_message,
    ])
    assert _looks_like_action_request(recent_user_text)


# --- «дорогие» темы: жёсткое правило про подтверждённые факты -------------
# Самый опасный класс из найденных замерами: модель звучит ОДИНАКОВО
# уверенно, когда права и когда выдумывает. Подтверждено живьём — неверный
# вид животного для звонка в экстренную службу (с польской фразой, которую
# человек прочитал бы диспетчеру), визовые требования из головы, цены без
# проверки. Отличить по тону нельзя, поэтому режем по теме.





def test_unconfirmed_high_stakes_number_detected():
    # Реальный найденный случай (замер 2026-09-04, сценарий про дозу
    # парацетамола ребёнку, 2 прогона из 3): все числа взяты из головы,
    # web_search возвращал пустоту. Худший прогон судья оценил на 5/5,
    # потому что модель вписала коэффициенты ЛИТЕРАЛАМИ в код run_python
    # и подала расчёт как подтверждённый инструментом — калькулятор
    # перемножил догадку, а не проверил её.
    from app.routers.dialogs import _has_unconfirmed_high_stakes_number as num

    # Медицинская доза ловится ВНЕ ЗАВИСИМОСТИ от того, распознана ли
    # тема по словам: единица измерения устойчивее формулировки вопроса.
    # Это исправление собственной ошибки — сначала проверка была привязана
    # к списку слов, и он промахнулся на «Ребёнку 4 года, температура 38.5.
    # Сколько парацетамола можно дать?».
    assert num("это 250 мг парацетамола", False)
    assert num("разовая доза 10–15 мг/кг массы тела", False)
    assert num("дать 1 таблетку сейчас и вторую через 6 часов", False)
    # Деньги — только когда тема распознана: сумма сама по себе безобидна.
    assert num("штраф около 500 злотых", True)


def test_unconfirmed_high_stakes_number_ignores_advice_without_numbers():
    # Общие объяснения и порядок действий безвредны и полезны — пометка
    # там была бы чистым занудством.
    from app.routers.dialogs import _has_unconfirmed_high_stakes_number as num

    assert not num("Температуру сбивают, когда ребёнку плохо, а не по цифре", False)
    assert not num("Дозу я не проверял — она зависит от веса, уточните у врача", False)
    assert not num("Вызывайте скорую, если появится сыпь или судороги", False)
    # «мл», «г» и «раз в день» сознательно не считаются дозой: они рядовые
    # в рецептах и списке покупок, пометка там была бы занудством.
    assert not num("Купить: 200 мл молока, 500 г муки", False)
    assert not num("Поливать 2 раза в день", False)
    assert not num("записал: молоко 5 злотых, хлеб 4 злотых", False)


def test_high_stakes_fragment_mixed_into_prompt_only_when_needed():
    from app.routers.dialogs import HIGH_STAKES_PROMPT_FRAGMENT, _build_system_prompt

    marker = HIGH_STAKES_PROMPT_FRAGMENT[:40]
    with_rule = _build_system_prompt([], "", set(), set(), False, "Europe/Warsaw", True)
    without = _build_system_prompt([], "", set(), set(), False, "Europe/Warsaw", False)
    assert marker in with_rule
    assert marker not in without


# --- _looks_like_unkept_promise: обещание, за которым ход закончился ------
# Реальный найденный случай (ролплей-замер 2026-09-03, сценарий ужина):
# «Сейчас создам папку «Рецепты» и список «К ужину в воскресенье».
# Подождите немного.» — и конец хода, ни одного создающего вызова.
# Человеку сказали ждать, а не произойдёт уже ничего. Это НЕ ложное
# «готово»: там прошедшее время, здесь будущее, и лечится оно иначе —
# ход не отпускается, модели возвращается указание доделать.

def test_looks_like_unkept_promise_catches_real_cases():
    from app.routers.dialogs import _looks_like_unkept_promise as promise

    assert promise("Сейчас создам папку «Рецепты» и список. Подождите немного.")
    assert promise("Сейчас добавлю сыр и колбасу.")
    assert promise("Секунду, запишу это в заметку.")
    assert promise("Минутку, сохраню изменения.")


def test_looks_like_unkept_promise_ignores_offers_and_questions():
    # Требуются ОБА признака — глагол будущего времени и маркер «прямо
    # сейчас». Одного глагола мало: «создам, если скажешь название» —
    # уточнение, а не обещание, и ход там закончен правильно.
    from app.routers.dialogs import _looks_like_unkept_promise as promise

    assert not promise("Создам список покупок?")
    assert not promise("Создам список, если скажешь название")
    assert not promise("Могу создать список покупок")
    assert not promise("Хотите, я сделаю напоминание?")
    assert not promise("Сейчас в списке пять пунктов.")


def test_unkept_promise_and_false_completion_do_not_overlap():
    # Два детектора закрывают РАЗНЫЕ случаи и не должны ловить чужой:
    # прошедшее время — ложное «готово», будущее — невыполненное обещание.
    from app.routers.dialogs import (
        _looks_like_false_completion_claim as claim,
        _looks_like_unkept_promise as promise,
    )

    past = "Готово, список покупок создан."
    future = "Сейчас создам список покупок. Подождите."
    assert claim(past) and not promise(past)
    assert promise(future) and not claim(future)


def test_looks_like_false_completion_claim_covers_forms_not_listed_by_hand():
    # Проверка идёт по КОРНЮ + окончанию, а не по списку словоформ.
    # Перечисление форм уже один раз промахнулось живьём: не было мужской
    # краткой формы "создан", и на прямое "А оно сохранилось?" →
    # "Да, список покупок создан." детектор промолчал (транскрипт замера
    # 2026-09-03). Здесь именно те формы, которых в старом списке не было.
    from app.routers.dialogs import _looks_like_false_completion_claim as claim

    assert claim("Да, список покупок создан.")
    assert claim("Пункт добавлен.")
    assert claim("Файл сохранён.")
    assert claim("Файл сохранен.")
    assert claim("Задача выполнена")
    assert claim("Note created")  # модель иногда срывается на английский


def test_looks_like_false_completion_claim_ignores_intent_and_nouns():
    # Окончание обязательно и ограничено прошедшим/страдательным именно
    # ради этих случаев: намерение и существительное — не заявление о
    # сделанном, предупреждать там нечего.
    from app.routers.dialogs import _looks_like_false_completion_claim as claim

    assert not claim("Я создам заметку с этим текстом")
    assert not claim("Создание списка займёт секунду")
    assert not claim("Показать записанные ранее заметки?")
    assert not claim("Я готов помочь")
    assert not claim("Хотите сохранить?")


def test_looks_like_false_completion_claim_true_for_bare_готово():
    from app.routers.dialogs import _looks_like_false_completion_claim

    assert _looks_like_false_completion_claim("Готово, все записи из заметки добавлены в таблицу.")
    assert _looks_like_false_completion_claim("Да, точно, добавлены все 4 записи.")


def test_looks_like_false_completion_claim_false_for_honest_refusal():
    # Реальный риск ложного срабатывания: честный отказ ("не смог
    # добавить") тоже содержит стем "добав" — не должен помечаться как
    # заявление об успехе.
    from app.routers.dialogs import _looks_like_false_completion_claim

    assert not _looks_like_false_completion_claim("Не смог добавить — заметка не найдена.")
    assert not _looks_like_false_completion_claim("Не получилось создать таблицу.")


def test_looks_like_false_completion_claim_false_for_various_negation_phrasings():
    # Реальный найденный ложноположительный случай (тот же день, другой
    # сценарий): "Похоже, заметка не была создана — я не сохранил
    # обсуждённое" — честное признание, не заявление об успехе. Прежний
    # список фраз-отрицаний ("не смог"/"не удалось" и т.п.) не покрывал
    # "не была создана"/"не сохранил" — отрицание сочетается со стемом
    # почти как угодно, поэтому проверка теперь по близости "не "/"нет "
    # перед конкретным вхождением стема, а не по фиксированному списку фраз.
    from app.routers.dialogs import _looks_like_false_completion_claim

    assert not _looks_like_false_completion_claim(
        "Похоже, заметка не была создана — я не сохранил обсуждённое в заметку."
    )
    assert not _looks_like_false_completion_claim("Напоминание не поставлено, попробуй ещё раз.")
    assert not _looks_like_false_completion_claim("Список пока не обновлён.")


def test_looks_like_false_completion_claim_false_for_imperative_advice():
    # Реальный найденный ложноположительный случай (тот же день, третий
    # заход): обычный чек-лист советов ("сделай X", "проверь Y") задел
    # прежний стем "сдела" — тот же кусок, что у "сделано". Раньше стемы
    # были сырыми подстроками, совпадавшими и с повелительным наклонением
    # того же глагола. Теперь список — только точные формы прошедшего
    # времени/страдательного причастия через границы слов (\b), ни одна
    # не пересекается с повелительным "сделай"/"добавь"/"создай" и т.п.
    from app.routers.dialogs import _looks_like_false_completion_claim

    assert not _looks_like_false_completion_claim(
        "Сразу после покупки: сделай диагностику ЭБУ, обнови масло, сохрани все чеки."
    )
    assert not _looks_like_false_completion_claim("Создай список покупок и добавь туда молоко.")


def test_looks_like_false_completion_claim_false_for_unrelated_word_with_same_root():
    # Реальный найденный ложноположительный случай (тот же день): "Что
    # приготовить на ужин" (шумная реплика не по теме) задела прежний стем
    # "готов", хотя "приготовить" вообще не о выполнении задачи. Проверка
    # по границам слова (\b) больше не считает "готов" внутри
    # "приготовить" совпадением.
    from app.routers.dialogs import _looks_like_false_completion_claim

    assert not _looks_like_false_completion_claim(
        "Что приготовить на ужин вместо макарон: жареная курица с картофелем."
    )


# --- _dialog_has_mutating_tool_call: проверка по ВСЕМУ диалогу ------------
# Реальный найденный класс ложных срабатываний (ролплей-тест «воскресный
# ужин», 3 подряд в одном раунде): проверка была ограничена одним ходом, и
# честный ответ на вопрос «всё ли сохранено?» получал предупреждение, хотя
# список/напоминание реально создавались ходом раньше.

def test_dialog_has_mutating_tool_call_true_for_earlier_create():
    from app.routers.dialogs import _dialog_has_mutating_tool_call

    records = [
        {"role": "user", "content": "составь список покупок"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "create_list", "arguments": {}}]},
        {"role": "tool", "content": "{}"},
        {"role": "assistant", "content": "Готово, список создан."},
        {"role": "user", "content": "всё сохранено?"},
    ]
    assert _dialog_has_mutating_tool_call(records)


def test_dialog_has_mutating_tool_call_false_for_read_only_dialog():
    from app.routers.dialogs import _dialog_has_mutating_tool_call

    records = [
        {"role": "user", "content": "перенеси данные в таблицу"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "get_note", "arguments": {}}]},
        {"role": "tool", "content": "{}"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "search_base", "arguments": {}}]},
        {"role": "tool", "content": "{}"},
    ]
    assert not _dialog_has_mutating_tool_call(records)


def test_dialog_has_mutating_tool_call_ignores_remember_fact():
    # remember_fact — память ассистента, не видимый пользователю контент.
    # Реальный случай: модель вызвала remember_fact и заявила "всё сохранено
    # в заметке" — заметки не было. Если бы remember_ считался изменяющим,
    # эта ложь прошла бы мимо проверки.
    from app.routers.dialogs import _dialog_has_mutating_tool_call

    records = [
        {"role": "user", "content": "сохрани всё про машину"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "remember_fact", "arguments": {}}]},
        {"role": "tool", "content": "{}"},
    ]
    assert not _dialog_has_mutating_tool_call(records)


def test_looks_like_false_completion_claim_false_for_plain_answer():
    from app.routers.dialogs import _looks_like_false_completion_claim

    assert not _looks_like_false_completion_claim("Передние тормозные диски — 266×22 мм, вентилируемые.")


# --- _BARE_URL_IN_JSON_RE: правильная граница по кавычке, не по пробелу ---

def test_bare_url_in_json_re_stops_at_closing_quote_not_next_field():
    import json

    from app.routers.dialogs import _BARE_URL_IN_JSON_RE

    result = {"url": "https://notenotes.example/?item=abc", "title": "Заметка с пробелами в названии"}
    found = [m.group(0) for m in _BARE_URL_IN_JSON_RE.finditer(json.dumps(result, ensure_ascii=False))]
    assert found == ["https://notenotes.example/?item=abc"]


# --- Онбординг новичка: гейт по прошлым диалогам, не по пустой памяти ----
# Реальный найденный случай (ролплей-тест "мама-пенсионерка"): онбординг
# гейтился по `not memory_facts`, и если кто-то заранее добавил в память
# факт о новом человеке ("маме 71 год, живёт в Костроме") — ровно то, что
# сделает родственник, настраивая приложение пожилому родителю, —
# онбординг не срабатывал вообще. Самый неуверенный пользователь получал
# наименьшую помощь: за весь тестовый раунд suggest_replies не вызвался
# ни разу, вместо кнопок были открытые вопросы "Чем помочь?".

def test_onboarding_fragment_present_for_fresh_start():
    from app.routers.dialogs import _build_system_prompt

    prompt = _build_system_prompt([], "", {"suggest_replies"}, set(), True)
    assert "Это первое сообщение пользователя" in prompt


def test_onboarding_fragment_survives_non_empty_memory():
    # Ключевая регрессия: наличие фактов в памяти больше НЕ отменяет
    # онбординг — за него теперь отвечает отдельный признак "нет прошлых
    # диалогов" (см. is_new_user в _run_dialog_turn_locked).
    from app.routers.dialogs import _build_system_prompt

    prompt = _build_system_prompt(["Маме 71 год, живёт в Костроме"], "", {"suggest_replies"}, set(), True)
    assert "Это первое сообщение пользователя" in prompt


def test_onboarding_fragment_absent_for_returning_user():
    from app.routers.dialogs import _build_system_prompt

    prompt = _build_system_prompt(["Маме 71 год"], "", {"suggest_replies"}, set(), False)
    assert "Это первое сообщение пользователя" not in prompt


def test_onboarding_fragment_demands_concrete_buttons():
    # Смысл фрагмента — заставить дать ГОТОВЫЕ просьбы кнопками, а не
    # открытый вопрос "чем помочь?".
    from app.routers.dialogs import ONBOARDING_PROMPT_FRAGMENT

    assert "suggest_replies" in ONBOARDING_PROMPT_FRAGMENT
    assert "жаргон" in ONBOARDING_PROMPT_FRAGMENT.lower()


def test_leaked_tool_call_without_tool_name_is_caught():
    """Реальный случай (диалог про замену прав, 2026-09-09): ответ
    заканчивался склеенными с текстом АРГУМЕНТАМИ вызова, без имени тула
    перед ними:

        ...карта побыту){"query": "как создать Profil Zaufany иностранцу"}

    Прежняя проверка требовала имя тула рядом с «{», поэтому пропускала это
    целиком, и сырой JSON доезжал до пользователя как часть ответа.
    """
    from app.routers.dialogs import _looks_like_leaked_tool_call
    from app.tools.registry import get_tool_definitions

    names = {d.name for d in get_tool_definitions()}
    leaked = (
        "Profil Zaufany выдают и иностранцам, если есть PESEL"
        '{"query": "как создать Profil Zaufany иностранцу в Польше 2026"}'
    )
    assert _looks_like_leaked_tool_call(leaked, names)


def test_json_in_a_code_block_is_not_a_leaked_call():
    """Пользователь мог попросить показать JSON — внутри блока кода он
    законен, и вырезать ответ было бы хуже, чем пропустить утечку."""
    from app.routers.dialogs import _looks_like_leaked_tool_call
    from app.tools.registry import get_tool_definitions

    names = {d.name for d in get_tool_definitions()}
    legit = 'Вот пример запроса:\n\n```json\n{"query": "пример"}\n```'
    assert not _looks_like_leaked_tool_call(legit, names)


def test_ordinary_answer_ending_with_brace_is_not_a_leaked_call():
    """Ложные срабатывания тут дороги: обрежем настоящий ответ."""
    from app.routers.dialogs import _looks_like_leaked_tool_call
    from app.tools.registry import get_tool_definitions

    names = {d.name for d in get_tool_definitions()}
    assert not _looks_like_leaked_tool_call('Формула такая: {"a": 1, "b": 2}', names)


# --- прямая просьба запомнить ---------------------------------------------
# Реальный случай (диалог про замену прав, 2026-09-09): на «я не гражданин
# Польши, я гражданин РФ, запомни уже это» ассистент ответил текстом и НЕ
# вызвал remember_fact — за весь диалог из 34 сообщений вызывался только
# web_search. Гражданство в память не попало, и дальше он советовал то,
# что гражданину РФ недоступно (онлайн-мельдунек): по официальным правилам
# gov.pl не гражданин ЕС/EFTA замельдоваться через интернет не может.

def test_explicit_request_to_remember_is_detected():
    from app.routers.dialogs import _asks_to_remember

    assert _asks_to_remember("я гражданин РФ, запомни уже это")
    assert _asks_to_remember("не забывай что у меня Citroën C4")
    assert _asks_to_remember("Сохрани в памяти: жена — Алина")


def test_ordinary_messages_are_not_requests_to_remember():
    """Ложное срабатывание стоит лишнего вызова LLM и задержки ответа,
    поэтому берём только явные формы. «Учти» и «имей в виду» сознательно
    НЕ считаются: они чаще про текущий ответ, а не про долгую память."""
    from app.routers.dialogs import _asks_to_remember

    assert not _asks_to_remember("что мне нужно для замены прав")
    assert not _asks_to_remember("учти что я тороплюсь")
    assert not _asks_to_remember("имей в виду, вечером не смогу")
    assert not _asks_to_remember("я запомнил, спасибо")


# --- капитуляция под возражением ------------------------------------------
# Два реальных случая одной формы. Замер 2026-09-03 (тормозные диски):
# «откуда взял 282,6? это для ц4 второго поколения?» → «Да, 282,6 мм — это
# данные для C4 ВТОРОГО поколения», хотя верно было третье и ассистент сам
# же цитировал источник двумя репликами выше. Живой диалог 2026-09-09
# (мельдунек): «а точно достаточно электронного?» → «Да, достаточно», при
# том что репликой раньше было «без этого процедура не пройдёт».
#
# Семантическое противоречие кодом не поймать. Ловим структуру: усомнились
# — согласился — ничего не проверил.

def test_capitulation_after_challenge_is_detected():
    from app.routers.dialogs import _looks_like_capitulation as cap

    assert cap(
        "откуда взял 282,6? это для ц4 второго поколения что ли?",
        "Да, 282,6 мм — это данные для Citroën C4 второго поколения.",
    )
    assert cap(
        "а точно для замены прав достаточно электронного мельдования?",
        "Да, для замены прав достаточно электронной регистрации.",
    )
    assert cap("откуда взял 282,6? на первом сайте 266", "Ты прав, данные разнятся.")


def test_standing_ground_is_not_capitulation():
    """Главное, что НЕ должно срабатывать: ассистент остался при своём.
    Иначе подсказка била бы ровно по правильному поведению."""
    from app.routers.dialogs import _looks_like_capitulation as cap

    assert not cap("а точно достаточно?", "Нет, электронной недостаточно — нужна справка.")


def test_plain_questions_are_not_challenges():
    """«Да» в ответ на обычный вопрос — не уступка, а нормальный ответ."""
    from app.routers.dialogs import _looks_like_capitulation as cap

    assert not cap("а можно просто текст написать?", "Да, конечно! Можно создать заметку.")
    assert not cap("что нужно для замены прав?", "Да, вам потребуется паспорт и карта побыту.")


# --- сроки и количество дней в «дорогих» темах ----------------------------
# Замер 2026-09-09: в сценарии про визу ВСЕ ТРИ прогона назвали безвизовый
# срок, и назвали РАЗНЫЙ — «30 дней», «90 дней», «до 90 дней». Модель его
# не знает и говорит уверенно, а прежние шаблоны (дозы и деньги) на «дни»
# не реагировали вовсе.

def test_terms_in_days_are_caught_in_high_stakes_topics():
    from app.routers.dialogs import _has_unconfirmed_high_stakes_number as num

    assert num("Без визы можно находиться до 90 дней", True)
    assert num("россияне могут быть в Черногории 30 дней", True)
    assert num("Карта побыту действует ещё 2 года", True)
    assert num("Рассмотрение занимает 30 суток", True)


def test_everyday_durations_are_never_flagged():
    """Главный риск: «поливать 2 раза в день» и «напомню через 3 дня» —
    бытовые. Помечать их — приучить игнорировать пометку вообще."""
    from app.routers.dialogs import _has_unconfirmed_high_stakes_number as num

    for text in ("Поливать 2 раза в день", "Напомню через 3 дня",
                 "Готовить 40 минут", "Список на 6 человек"):
        assert not num(text, False), text



