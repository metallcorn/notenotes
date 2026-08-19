from app import document_reflow
from app.core.config import get_settings
from app.llm.base import LLMResponse, Message


class _FakeLLMClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def chat(self, messages, tools):
        user_content = messages[-1].content
        self.calls.append(user_content)
        return LLMResponse(message=Message(role="assistant", content=f"[reflowed]{user_content}"), finish_reason="stop")


class _FailingLLMClient:
    async def chat(self, messages, tools):
        raise RuntimeError("boom")


def _use_fake_client(monkeypatch, client):
    monkeypatch.setattr(get_settings(), "llm_api_key", "test-key")
    monkeypatch.setattr(document_reflow, "get_llm_client", lambda: client)


async def test_reflow_short_text_makes_a_single_call(monkeypatch):
    client = _FakeLLMClient()
    _use_fake_client(monkeypatch, client)

    result = await document_reflow.reflow_document_text("короткий текст")

    assert client.calls == ["короткий текст"]
    assert result == "[reflowed]короткий текст"


async def test_reflow_long_text_splits_and_keeps_every_chunk(monkeypatch):
    # Реальный найденный баг: raw[:_MAX_CHARS] молча обрезал документ — для
    # 24-страничного PDF причёсывались только первые ~5 страниц, остальные
    # пропадали без следа и без ошибки (transcription_status оставался
    # "done"). Здесь текст заведомо длиннее _MAX_CHARS — должно уйти
    # НЕСКОЛЬКО вызовов, и в итоговом результате должен быть текст из
    # КАЖДОГО параграфа, не только из первого куска.
    client = _FakeLLMClient()
    _use_fake_client(monkeypatch, client)

    paragraphs = [f"Абзац номер {i} " + "текст " * 200 for i in range(10)]
    raw = "\n\n".join(paragraphs)
    assert len(raw) > document_reflow._MAX_CHARS  # sanity: тест действительно бьёт лимит

    result = await document_reflow.reflow_document_text(raw)

    assert len(client.calls) > 1
    for i in range(10):
        assert f"Абзац номер {i}" in result


async def test_reflow_falls_back_to_raw_on_llm_error(monkeypatch):
    _use_fake_client(monkeypatch, _FailingLLMClient())

    result = await document_reflow.reflow_document_text("текст, который не удастся причесать")

    assert result == "текст, который не удастся причесать"


async def test_reflow_skips_llm_without_api_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_api_key", "")

    result = await document_reflow.reflow_document_text("текст без ключа")

    assert result == "текст без ключа"


def test_split_into_chunks_keeps_short_text_as_one_chunk():
    assert document_reflow._split_into_chunks("короткий текст", 100) == ["короткий текст"]


def test_split_into_chunks_respects_paragraph_boundaries():
    paragraphs = ["A" * 30, "B" * 30, "C" * 30]
    raw = "\n\n".join(paragraphs)

    chunks = document_reflow._split_into_chunks(raw, max_chars=40)

    assert "".join(chunks).count("A") == 30
    assert "".join(chunks).count("B") == 30
    assert "".join(chunks).count("C") == 30
    for chunk in chunks:
        assert len(chunk) <= 40


def test_split_into_chunks_hard_splits_a_single_oversized_paragraph():
    raw = "X" * 250  # один "абзац" без переносов, сильно длиннее лимита
    chunks = document_reflow._split_into_chunks(raw, max_chars=100)

    assert len(chunks) == 3
    assert "".join(chunks) == raw
    for chunk in chunks[:-1]:
        assert len(chunk) == 100
