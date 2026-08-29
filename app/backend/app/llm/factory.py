from functools import lru_cache

from app.core.config import get_settings
from app.llm.base import LLMClient
from app.llm.gemini import GeminiClient
from app.llm.groq import GroqClient
from app.llm.mistral import MistralClient


@lru_cache
def _client_for(provider: str) -> LLMClient:
    """Единственное место, знающее про конкретных провайдеров. Переключение
    провайдера не требует правок нигде за пределами этого файла — ради
    этого и заведена абстракция (ТЗ §20 плюс явная просьба пользователя
    держать возможность подставить Gemini/OpenAI/Claude). @lru_cache — по
    provider-строке, не по пользователю: клиент сам по себе (httpx-клиент
    внутри chat() создаётся на вызов) не хранит per-user состояния, так что
    один инстанс на провайдер безопасно шарить между всеми пользователями."""
    settings = get_settings()
    if provider == "mistral":
        return MistralClient(api_key=settings.llm_api_key, model=settings.llm_model)
    if provider == "gemini":
        return GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    if provider == "groq":
        return GroqClient(api_key=settings.groq_api_key, model=settings.groq_model)
    raise ValueError(f"Неизвестный LLM-провайдер: {provider}")


def get_llm_client(provider: str | None = None) -> LLMClient:
    """provider — per-user override (User.llm_provider, см. settings в
    SettingsModal.tsx) для живого A/B-сравнения без передеплоя; пустая
    строка/None — глобальный дефолт из LLM_PROVIDER."""
    settings = get_settings()
    return _client_for(provider or settings.llm_provider)


# Модель "покрупнее" для тихой эскалации при реальном сбое основной модели
# (routers/dialogs.py, MAX_TOOL_ITERATIONS-цикл) — не по эвристике
# "сложности" вопроса (та ломается на реальных формулировках живых
# пользователей, см. историю правок calendar_reminders/run_python в этом
# же файле), а по факту: провайдер вернул ошибку/пустой ответ, или модель
# написала tool_call текстом вместо настоящего вызова. Бенчмарк на 28
# реальных вопросах пользователя (2026-08) показал, что mistral-large-latest
# НЕ точнее small/medium на этой нагрузке, зато менее надёжна (живой 500 от
# самого Mistral, зависание на 131с) — поэтому потолок эскалации это
# medium, не large; large остаётся только ручным per-user overrid'ом.
_ESCALATION_MODELS: dict[str, str] = {
    "mistral": "mistral-medium-latest",
}


@lru_cache
def _escalated_client_for(provider: str) -> LLMClient | None:
    settings = get_settings()
    escalation_model = _ESCALATION_MODELS.get(provider)
    if escalation_model is None:
        return None
    if provider == "mistral":
        return MistralClient(api_key=settings.llm_api_key, model=escalation_model)
    return None


def get_escalated_llm_client(provider: str | None = None) -> LLMClient | None:
    """Клиент того же провайдера, но крупнее, для повторной попытки ПОСЛЕ
    реального сбоя основного вызова — None, если для этого провайдера
    эскалация не настроена (тогда вызывающий код просто не повторяет)."""
    settings = get_settings()
    return _escalated_client_for(provider or settings.llm_provider)
