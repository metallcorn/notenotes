from __future__ import annotations

from typing import Protocol


class ASRClient(Protocol):
    async def transcribe(self, audio: bytes, content_type: str) -> str: ...
