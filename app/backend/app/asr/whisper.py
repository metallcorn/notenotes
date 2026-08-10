from __future__ import annotations

import httpx

# Реальный найденный баг: WHISPER_API_KEY в секретах всегда был ключом Groq
# (префикс gsk_, подтверждено живым запросом — Groq отдаёт 200, OpenAI 401
# "Incorrect API key"), а клиент несколько недель бил в api.openai.com —
# транскрипция этим путём была гарантированно сломана. Не задело реальных
# пользователей только потому, что ASR_PROVIDER=deepgram — этот путь просто
# ни разу не выбирался. Переключаем на реальный эндпоинт ключа — Groq тоже
# хостит whisper-large-v3, тем же OpenAI-совместимым протоколом транскрипции.
GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

_EXTENSION_BY_CONTENT_TYPE = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


class WhisperClient:
    """Одноразовая транскрипция через Whisper (whisper-large-v3 на Groq) —
    тот же провайдер-независимый интерфейс ASRClient, что и у Deepgram."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        extension = _EXTENSION_BY_CONTENT_TYPE.get(content_type, "webm")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                GROQ_TRANSCRIPTIONS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                data={"model": "whisper-large-v3"},
                files={"file": (f"audio.{extension}", audio, content_type)},
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("text", "")
