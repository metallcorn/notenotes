import json

from app.telegram_bot import _build_action_buttons, _extract_image_paths, _find_calendar_event


def _tool_turn(tool_calls: list[dict], results: dict[str, dict]) -> list[dict]:
    """Собирает records одного хода — ровно та форма, что кладёт
    routers/dialogs.py::run_dialog_turn (assistant.tool_calls + отдельные
    tool-записи с tool_call_id/content=JSON)."""
    records = [{"role": "assistant", "content": "", "tool_calls": tool_calls}]
    for tc in tool_calls:
        records.append(
            {"role": "tool", "tool_call_id": tc["id"], "name": tc["name"], "content": json.dumps(results[tc["id"]])}
        )
    return records


def test_action_buttons_for_created_note():
    records = _tool_turn(
        [{"id": "c1", "name": "create_note", "arguments": {}}],
        {"c1": {"id": "abc-123", "title": "Подарок на день рождения"}},
    )
    rows = _build_action_buttons(records, "https://notenotes.example")
    assert rows == [[{"text": "Открыть «Подарок на день рождения»", "url": "https://notenotes.example/?item=abc-123"}]]


def test_action_buttons_for_maps_link():
    records = _tool_turn(
        [{"id": "c1", "name": "create_maps_link", "arguments": {}}],
        {"c1": {"query": "Минск", "url": "https://www.google.com/maps/search/?api=1&query=Минск"}},
    )
    rows = _build_action_buttons(records, "https://notenotes.example")
    assert rows == [[{"text": "Открыть в Google Maps", "url": "https://www.google.com/maps/search/?api=1&query=Минск"}]]


def test_action_buttons_multiple_tool_calls_in_one_turn():
    records = _tool_turn(
        [
            {"id": "c1", "name": "create_list", "arguments": {}},
            {"id": "c2", "name": "search_base", "arguments": {}},
            {"id": "c3", "name": "create_table", "arguments": {}},
        ],
        {
            "c1": {"id": "list-1", "title": "Покупки"},
            "c2": {"results": []},
            "c3": {"id": "table-1", "title": "Расходы"},
        },
    )
    rows = _build_action_buttons(records, "https://notenotes.example")
    assert rows == [
        [{"text": "Открыть «Покупки»", "url": "https://notenotes.example/?item=list-1"}],
        [{"text": "Открыть «Расходы»", "url": "https://notenotes.example/?item=table-1"}],
    ]


def test_action_buttons_skip_errored_tool_result():
    records = _tool_turn(
        [{"id": "c1", "name": "create_note", "arguments": {}}],
        {"c1": {"error": "Заметка не найдена"}},
    )
    assert _build_action_buttons(records, "https://notenotes.example") == []


def test_action_buttons_ignore_unrelated_tools():
    records = _tool_turn(
        [{"id": "c1", "name": "remember_fact", "arguments": {}}],
        {"c1": {"remembered": "любит кофе"}},
    )
    assert _build_action_buttons(records, "https://notenotes.example") == []


def test_find_calendar_event():
    records = _tool_turn(
        [{"id": "c1", "name": "create_calendar_event", "arguments": {}}],
        {"c1": {"title": "Встреча", "start": "2026-09-01T10:00:00", "end": "2026-09-01T11:00:00", "all_day": False}},
    )
    event = _find_calendar_event(records)
    assert event is not None
    assert event["title"] == "Встреча"


def test_find_calendar_event_absent():
    records = _tool_turn(
        [{"id": "c1", "name": "create_note", "arguments": {}}],
        {"c1": {"id": "x", "title": "y"}},
    )
    assert _find_calendar_event(records) is None


def test_extract_image_paths_single():
    stripped, paths = _extract_image_paths("Вот твоя картинка: ![кот](/api/uploads/abc-123)")
    assert paths == ["/api/uploads/abc-123"]
    assert "![" not in stripped
    assert "Вот твоя картинка" in stripped


def test_extract_image_paths_multiple():
    text = "Нашёл два фото: ![](/api/uploads/a) и ![](/api/uploads/b)"
    stripped, paths = _extract_image_paths(text)
    assert paths == ["/api/uploads/a", "/api/uploads/b"]
    assert "/api/uploads/" not in stripped


def test_extract_image_paths_none():
    stripped, paths = _extract_image_paths("Обычный текстовый ответ без картинок")
    assert paths == []
    assert stripped == "Обычный текстовый ответ без картинок"
