from functools import lru_cache

from app.core.config import get_settings
from app.llm.base import LLMClient
from app.llm.gemini import GeminiClient
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
    raise ValueError(f"Неизвестный LLM-провайдер: {provider}")


def get_llm_client(provider: str | None = None) -> LLMClient:
    """provider — per-user override (User.llm_provider, см. settings в
    SettingsModal.tsx) для живого A/B-сравнения без передеплоя; пустая
    строка/None — глобальный дефолт из LLM_PROVIDER."""
    settings = get_settings()
    return _client_for(provider or settings.llm_provider)
