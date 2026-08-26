"""dialog_compaction.py — чистые функции, без БД/LLM (см. test_dialogs.py
про то, почему настоящий агентный цикл не тестируется; тут другое —
summarize_records дёргает LLM ровно один раз детерминированно, мокается)."""
from app import dialog_compaction
from app.dialog_compaction import find_cut_index, render_old_messages_for_summary, summarize_records
from app.llm.base import LLMResponse, Message


def _user(text: str) -> dict:
    return {"id": "u", "role": "user", "content": text}


def _assistant(text: str = "", tool_calls: list[dict] | None = None) -> dict:
    r = {"id": "a", "role": "assistant", "content": text}
    if tool_calls:
        r["tool_calls"] = tool_calls
    return r


def _tool(tool_call_id: str, content: str = "{}") -> dict:
    return {"id": "t", "role": "tool", "content": content, "tool_call_id": tool_call_id, "name": "get_note"}


# --- find_cut_index -----------------------------------------------------------

def test_find_cut_index_empty_history():
    assert find_cut_index([], 20) == 0


def test_find_cut_index_shorter_than_keep_last():
    records = [_user("1"), _assistant("2")]
    assert find_cut_index(records, 20) == 0


def test_find_cut_index_snaps_back_to_nearest_user_message():
    # target = len(6) - 2 = 4, records[4] — не user (это "assistant2"),
    # ищем назад до ближайшего user — им окажется records[2].
    records = [
        _user("q1"), _assistant("a1"),
        _user("q2"), _assistant("a2"),
        _user("q3"), _assistant("a3"),
    ]
    cut = find_cut_index(records, 2)
    assert records[cut]["role"] == "user"
    assert cut == 4  # records[4] сам user ("q3") — уже валидная граница


def test_find_cut_index_never_splits_a_tool_call_from_its_result():
    # Пара assistant(tool_calls)+tool лежит МЕЖДУ двумя user-репликами —
    # снятие границы назад до ближайшего user не должно приземлиться между
    # ними, даже если arithmetic target попадает ровно туда.
    records = [
        _user("q1"),
        _assistant("", tool_calls=[{"id": "c1", "name": "get_note", "arguments": {}}]),
        _tool("c1"),
        _assistant("готово"),
        _user("q2"),
        _assistant("a2"),
    ]
    cut = find_cut_index(records, 1)  # target = 6 - 1 = 5, records[5] не user
    assert records[cut]["role"] == "user"
    # Ни один индекс между позицией assistant(tool_calls) и tool не выбран.
    assert cut not in (2, 3)


# --- render_old_messages_for_summary -------------------------------------------

def test_render_user_messages_verbatim():
    out = render_old_messages_for_summary([_user("Привет, как дела?")])
    assert "Пользователь: Привет, как дела?" in out


def test_render_tool_calls_as_compact_description_not_raw_json():
    records = [
        _assistant("", tool_calls=[{"id": "c1", "name": "search_base", "arguments": {"query": "паспорт"}}]),
    ]
    out = render_old_messages_for_summary(records)
    assert "search_base(паспорт)" in out
    assert "{" not in out  # сырой JSON аргументов не просочился


def test_render_tool_role_records_are_dropped_entirely():
    records = [_tool("c1", content='{"huge": "payload", "many": "fields"}')]
    out = render_old_messages_for_summary(records)
    assert out == ""
    assert "huge" not in out


def test_render_passes_through_prior_summary_with_marker():
    records = [_assistant("Уже сжатая суть разговора", tool_calls=None) | {"is_summary": True}]
    out = render_old_messages_for_summary(records)
    assert "[Ранее уже сжатая часть разговора]: Уже сжатая суть разговора" in out


# --- summarize_records ----------------------------------------------------------

class _FakeClient:
    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.calls: list[list[Message]] = []

    async def chat(self, messages, tools):
        self.calls.append(messages)
        return LLMResponse(message=Message(role="assistant", content=self._replies.pop(0)), finish_reason="stop")


async def test_summarize_records_single_chunk_no_reduce_call():
    client = _FakeClient(["Итоговое резюме"])
    result = await summarize_records(client, [_user("Короткий вопрос")])
    assert result == "Итоговое резюме"
    assert len(client.calls) == 1  # только map, reduce не понадобился


async def test_summarize_records_multi_chunk_calls_reduce_with_all_partials(monkeypatch):
    # 40 — больше одной реплики ("Пользователь: " + 20 симв ~= 34 симв),
    # меньше двух подряд — каждая реплика оказывается своим чанком, без
    # грубой нарезки по символам внутри одной реплики.
    monkeypatch.setattr(dialog_compaction, "_MAX_CHUNK_CHARS", 40)
    records = [_user("A" * 20), _user("B" * 20), _user("C" * 20)]
    client = _FakeClient(["сумма1", "сумма2", "сумма3", "финал"])

    result = await summarize_records(client, records)

    assert result == "финал"
    assert len(client.calls) == 4  # 3 map-вызова + 1 reduce
    reduce_input = client.calls[-1][-1].content
    assert "сумма1" in reduce_input and "сумма2" in reduce_input and "сумма3" in reduce_input
