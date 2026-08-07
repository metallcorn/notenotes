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
        return WhisperClient(api_key=settings.whisper_api_key)
    raise ValueError(f"Неизвестный ASR_PROVIDER: {settings.asr_provider}")
