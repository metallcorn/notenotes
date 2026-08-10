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
    # Второй провайдер для живого A/B-сравнения (пользователь может
    # переключиться в настройках per-user, не трогая глобальный дефолт
    # выше) — см. llm/factory.py и llm/gemini.py.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
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

    # Telegram-бот как канал захвата заметок (ТЗ, Фаза 2 «Каналы») —
    # обычный Bot API с вебхуком, не MTProto (тот — Фаза 3, доступ к
    # каналам пользователя, отдельная и более рискованная задача).
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""

    # Web Push (уведомления вне открытой вкладки/закрытого приложения) —
    # VAPID-пара, сгенерированная один раз (не платформенный ключ вендора,
    # self-hosted). Приватный ключ и публичный — оба "raw" urlsafe-base64
    # (не PEM): pywebpush.Vapid.from_string и браузерный
    # applicationServerKey принимают этот формат напрямую, без конвертации.
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
