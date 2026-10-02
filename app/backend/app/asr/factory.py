from functools import lru_cache

from app.asr.base import ASRClient
from app.asr.deepgram import DeepgramClient
from app.asr.whisper import WhisperClient
from app.core.config import get_settings


@lru_cache
def get_asr_client() -> ASRClient:
    """Единственное место, знающее про конкретных ASR-провайдеров — тот же
    приём, что и app/llm/factory.py, ради той же причины (провайдер должен
    быть подменяемым)."""
    settings = get_settings()
    if settings.asr_provider == "deepgram":
        return DeepgramClient(api_key=settings.deepgram_api_key)
    if settings.asr_provider == "whisper":
        return WhisperClient(api_key=settings.groq_api_key)
    raise ValueError(f"Неизвестный ASR_PROVIDER: {settings.asr_provider}")


def asr_available() -> bool:
    """Есть ли ключ у ТЕКУЩЕГО провайдера.

    Вынесено сюда, потому что три места проверяли это руками и все три
    ошибались: `settings.deepgram_api_key or settings.whisper_api_key` —
    поля whisper_api_key в конфиге НЕТ (оно удалено, whisper ходит через
    groq_api_key). Пока ключ Deepgram задан, короткое замыкание прячет
    ошибку; стоит ему опустеть — AttributeError вместо честного «нет
    ключа», и голосовое сообщение падает в «Необработанная ошибка».
    Поймано 02.10.
    """
    settings = get_settings()
    if settings.asr_provider == "deepgram":
        return bool(settings.deepgram_api_key)
    if settings.asr_provider == "whisper":
        return bool(settings.groq_api_key)
    return False
