from functools import lru_cache

from app.core.config import get_settings
from app.llm.base import LLMClient
from app.llm.mistral import MistralClient


@lru_cache
def get_llm_client() -> LLMClient:
    """Единственное место, знающее про конкретных провайдеров. Переключение
    LLM_PROVIDER в конфиге не требует правок нигде за пределами этого файла —
    ради этого и заведена абстракция (ТЗ §20 плюс явная просьба пользователя
    держать возможность подставить Gemini/OpenAI/Claude)."""
    settings = get_settings()
    if settings.llm_provider == "mistral":
        return MistralClient(api_key=settings.llm_api_key, model=settings.llm_model)
    raise ValueError(f"Неизвестный LLM_PROVIDER: {settings.llm_provider}")
