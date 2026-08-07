from __future__ import annotations

from typing import Protocol


class TTSClient(Protocol):
    async def synthesize(self, text: str, voice_id: str | None = None) -> bytes:
        """Возвращает готовый WAV (с заголовком, проигрываемый браузером напрямую).
        voice_id — переопределение голоса per-request (настройка пользователя),
        без него используется дефолт клиента."""
        ...
