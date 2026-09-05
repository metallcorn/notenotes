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
    # Только для Playwright E2E (scripts/e2e-test.sh) — тот бэкенд сидит на
    # голом http://, а Secure-кука на http:// браузер молча не сохранит и
    # не пришлёт обратно (тот же эффект, что раньше ловили на httpx-клиенте
    # в pytest — см. auth.py). В проде app.env этот флаг не задаёт, дефолт
    # остаётся True.
    session_cookie_secure: bool = True

    # Фаза 2: AI-ассистент (ТЗ §10a/§10b). llm_provider — единственная точка
    # переключения (см. app/llm/factory.py); Mistral выбран первым как самый
    # быстрый способ начать тестировать, не единственным навсегда.
    llm_provider: str = "mistral"
    llm_api_key: str = ""
    llm_model: str = "mistral-large-latest"
    # Температура сэмплирования. НЕ задавалась вовсе до 2026-09-05 — работали
    # на дефолте провайдера (у Mistral это 0.3 у всех моделей, проверено через
    # GET /v1/models). Вынесено в настройку, потому что это подозреваемый
    # источник шума замера: один и тот же вариант, прогнанный дважды, давал
    # по сценарию «ужин» 4,4,3 и 1,3,1 — часть этого разброса просто
    # сэмплирование. Значение None = не передавать параметр вовсе, то есть
    # прежнее поведение (дефолт провайдера).
    llm_temperature: float | None = None
    # Второй провайдер для живого A/B-сравнения (пользователь может
    # переключиться в настройках per-user, не трогая глобальный дефолт
    # выше) — см. llm/factory.py и llm/gemini.py.
    gemini_api_key: str = ""
    # 3.5-flash даёт всего 20 запросов/день на free tier (проверено вживую
    # — реальный лимит из тела 429-ответа, не из документации) — для
    # агентного цикла с несколькими tool-call'ами за ход это буквально
    # 2-3 полноценных хода в сутки. 2.5-flash (старше, дешевле в
    # обслуживании для Google) даёт рабочий запас для тестирования.
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    # ВНИМАНИЕ: на бесплатном тарифе Groq этот провайдер сейчас нерабочий,
    # и это не наша поломка. Проверено вживую 2026-09-03:
    #   - llama-3.3-70b-versatile (стоял здесь раньше, его free tier на
    #     12000 TPM единственный вмещал наш запрос) — Groq УДАЛИЛ модель,
    #     её нет в /v1/models, любой вызов = 404;
    #   - все оставшиеся модели с tool calling (gpt-oss-120b, gpt-oss-20b,
    #     qwen3.8-27b, qwen3.6-27b) имеют free tier 8000 TPM, а наш
    #     запрос — 12805 токенов (схемы 40 тулов + системный промпт), то
    #     есть 413 "Request too large" на КАЖДЫЙ вызов;
    #   - groq/compound-mini вмещается, но tool calling не поддерживает
    #     вовсе (400), а без тулов ассистент бесполезен.
    # Оставляем gpt-oss-120b: он хотя бы существует и даёт понятную ошибку
    # про размер запроса вместо 404 про несуществующую модель, и сразу
    # заработает на платном тарифе. Groq по-прежнему используется для
    # распознавания речи (whisper-large-v3) — там лимиты другие и всё в
    # порядке, см. asr/whisper.py.
    groq_model: str = "openai/gpt-oss-120b"
    tavily_api_key: str = ""
    # CLAUDE.md: хардкап обязателен с первой версии, без исключений —
    # иначе агентный цикл может сжечь месячный бесплатный лимит Tavily
    # за один неудачный запрос.
    web_search_max_calls_per_turn: int = 5

    # Голосовой ассистент (ТЗ §10a, §14). ASR — одноразовая транскрипция
    # записанной реплики (не потоковая), поэтому Deepgram/Whisper — оба
    # простой REST. TTS — Palabra, у него потоковый WebSocket-протокол
    # (см. app/tts/palabra.py). asr_provider="whisper" использует Groq
    # (whisper-large-v3) через groq_api_key выше, отдельного ключа не было
    # и не нужно — раньше был WHISPER_API_KEY, но его значение всегда было
    # ключом от Groq (реальный найденный баг, см. asr/whisper.py).
    asr_provider: str = "deepgram"
    deepgram_api_key: str = ""
    tts_provider: str = "palabra"
    palabra_api_key: str = ""
    palabra_region: str = "eu"

    # Telegram-бот как канал захвата заметок (ТЗ, Фаза 2 «Каналы») —
    # обычный Bot API с вебхуком, не MTProto (тот — Фаза 3, доступ к
    # каналам пользователя, отдельная и более рискованная задача).
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""

    # Приём почты на персональный адрес как заметки (ТЗ, Фаза 2 «Каналы») —
    # Mailgun inbound-parse webhook, EU-регион. Порт 25 не нужен: почта идёт
    # на MX Mailgun, они шлют нам обычный HTTPS POST через уже существующий
    # Caddy-домен (см. routers/mail_webhook.py). mail_domain — поддомен,
    # подключённый в Mailgun (например mail.notenotes.metallcorn.online),
    # используется только для сборки полного адреса local_part@mail_domain.
    mailgun_api_key: str = ""
    mailgun_webhook_signing_key: str = ""
    mail_domain: str = ""

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
