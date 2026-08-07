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
                # language=ru — без него Deepgram молча считает аудио английским
                # и на русской речи возвращает пустой транскрипт с confidence=0,
                # без единой ошибки (поймали живьём при отладке видео-расшифровки,
                # тот же баг был и здесь). Приложение по умолчанию русскоязычное
                # (ТЗ, PalabraClient и т.д.) — используем то же допущение.
                params={"model": "nova-2", "smart_format": "true", "language": "ru"},
                headers={"Authorization": f"Token {self._api_key}", "Content-Type": content_type},
                content=audio,
            )
            resp.raise_for_status()
            data = resp.json()

        try:
            return data["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError):
            return ""

    async def transcribe_with_speakers(self, audio: bytes, content_type: str) -> str:
        """Для видео (app/transcription.py) — с диаризацией: если говорит
        несколько человек, результат размечен по репликам "Спикер N: …", а
        не одним сплошным куском текста. utterances=true — Deepgram сам
        режет на реплики по паузам/сменам говорящего, вручную группировать
        по словам не нужно. Таймаут больше, чем у transcribe(): видео
        дольше короткой голосовой реплики."""
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                DEEPGRAM_API_URL,
                params={
                    "model": "nova-2",
                    "smart_format": "true",
                    "diarize": "true",
                    "utterances": "true",
                    "language": "ru",
                },
                headers={"Authorization": f"Token {self._api_key}", "Content-Type": content_type},
                content=audio,
            )
            resp.raise_for_status()
            data = resp.json()

        try:
            utterances = data["results"]["utterances"]
        except KeyError:
            try:
                return data["results"]["channels"][0]["alternatives"][0]["transcript"]
            except (KeyError, IndexError):
                return ""

        speakers = {u.get("speaker") for u in utterances if u.get("speaker") is not None}
        if len(speakers) <= 1:
            return " ".join(u.get("transcript", "") for u in utterances).strip()

        lines = [f"Спикер {u.get('speaker', 0) + 1}: {u.get('transcript', '')}" for u in utterances]
        return "\n".join(lines)
