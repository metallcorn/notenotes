from __future__ import annotations

from typing import Protocol


class TTSClient(Protocol):
    async def synthesize(self, text: str) -> bytes:
        """Возвращает готовый WAV (с заголовком, проигрываемый браузером напрямую)."""
        ...
