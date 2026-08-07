from functools import lru_cache

from app.core.config import get_settings
from app.tts.base import TTSClient
from app.tts.palabra import PalabraClient


@lru_cache
def get_tts_client() -> TTSClient:
    settings = get_settings()
    if settings.tts_provider == "palabra":
        return PalabraClient(api_key=settings.palabra_api_key, region=settings.palabra_region)
    raise ValueError(f"Неизвестный TTS_PROVIDER: {settings.tts_provider}")
