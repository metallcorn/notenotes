from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None)

    database_url: str
    redis_url: str = ""
    upload_dir: str = "/data/uploads"
    public_base_url: str = "http://localhost:8000"
    secret_key: str
    session_cookie_name: str = "notenotes_session"
    session_ttl_days: int = 30

    # Фаза 2: AI-ассистент (ТЗ §10a/§10b). llm_provider — единственная точка
    # переключения (см. app/llm/factory.py); Mistral выбран первым как самый
    # быстрый способ начать тестировать, не единственным навсегда.
    llm_provider: str = "mistral"
    llm_api_key: str = ""
    llm_model: str = "mistral-large-latest"
    tavily_api_key: str = ""
    # CLAUDE.md: хардкап обязателен с первой версии, без исключений —
    # иначе агентный цикл может сжечь месячный бесплатный лимит Tavily
    # за один неудачный запрос.
    web_search_max_calls_per_turn: int = 5

    # Голосовой ассистент (ТЗ §10a, §14). ASR — одноразовая транскрипция
    # записанной реплики (не потоковая), поэтому Deepgram/Whisper — оба
    # простой REST. TTS — Palabra, у него потоковый WebSocket-протокол
    # (см. app/tts/palabra.py).
    asr_provider: str = "deepgram"
    deepgram_api_key: str = ""
    whisper_api_key: str = ""
    tts_provider: str = "palabra"
    palabra_api_key: str = ""
    palabra_region: str = "eu"


@lru_cache
def get_settings() -> Settings:
    return Settings()
