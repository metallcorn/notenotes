from __future__ import annotations

import httpx

DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"


class DeepgramClient:
    """Одноразовая (не потоковая) транскрипция целого аудио-блоба через
    Deepgram REST — подходит для записанной пользователем реплики, не для
    live-стриминга."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                DEEPGRAM_API_URL,
                params={"model": "nova-2", "smart_format": "true"},
                headers={"Authorization": f"Token {self._api_key}", "Content-Type": content_type},
                content=audio,
            )
            resp.raise_for_status()
            data = resp.json()

        try:
            return data["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError):
            return ""
