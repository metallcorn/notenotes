from app.core.config import get_settings
from app.llm.factory import _escalated_client_for, get_escalated_llm_client
from app.llm.mistral import MistralClient


def test_escalated_client_for_mistral_uses_medium_model():
    # Бенчмарк на реальных вопросах (2026-08) показал: mistral-large-latest
    # не точнее small/medium на этой нагрузке, зато менее надёжна — потолок
    # тихой эскалации это medium, не large.
    _escalated_client_for.cache_clear()
    client = _escalated_client_for("mistral")
    assert isinstance(client, MistralClient)
    assert client._model == "mistral-medium-latest"


def test_escalated_client_for_unknown_provider_is_none():
    _escalated_client_for.cache_clear()
    assert _escalated_client_for("groq") is None
    assert _escalated_client_for("gemini") is None


def test_get_escalated_llm_client_falls_back_to_global_provider(monkeypatch):
    _escalated_client_for.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    client = get_escalated_llm_client(None)
    assert isinstance(client, MistralClient)
