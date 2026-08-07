from __future__ import annotations

import httpx

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"

_EXTENSION_BY_CONTENT_TYPE = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


class WhisperClient:
    """Одноразовая транскрипция через Whisper API (OpenAI) — тот же
    провайдер-независимый интерфейс ASRClient, что и у Deepgram."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        extension = _EXTENSION_BY_CONTENT_TYPE.get(content_type, "webm")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                OPENAI_TRANSCRIPTIONS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                data={"model": "whisper-1"},
                files={"file": (f"audio.{extension}", audio, content_type)},
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("text", "")
