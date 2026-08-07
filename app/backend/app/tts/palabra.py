from __future__ import annotations

import base64
import io
import json
import wave

import websockets

# Palabra — не одноразовый REST, а потоковый WebSocket-протокол (их продукт —
# real-time speech-to-speech перевод, TTS — часть того же стека). Реализация
# ниже собрана по официальной документации (docs.palabra.ai /
# platform.palabra.ai/docs/text-to-speech/realtime-tts) на момент написания,
# но не проверена вживую — ключа ещё нет. При первом реальном запуске
# возможны расхождения в схеме сообщений, поправить по факту ошибки.
_WS_URL_BY_REGION = {
    "eu": "wss://stream.palabra.ai/tts-api/v1/text-to-speech/stream",
    "us": "wss://stream.us.palabra.ai/tts-api/v1/text-to-speech/stream",
}
SAMPLE_RATE = 24000
TEXT_CHUNK_LIMIT = 1000  # лимит протокола — 1024 символа на одно text-сообщение


def _chunk_text(text: str, limit: int = TEXT_CHUNK_LIMIT) -> list[str]:
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks or [""]


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit PCM
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buf.getvalue()


class PalabraClient:
    def __init__(self, api_key: str, region: str = "eu", language: str = "ru", voice_id: str = "default_low") -> None:
        self._api_key = api_key
        self._url = _WS_URL_BY_REGION.get(region, _WS_URL_BY_REGION["eu"])
        self._language = language
        self._voice_id = voice_id

    async def synthesize(self, text: str) -> bytes:
        chunks = []
        async with websockets.connect(f"{self._url}?token={self._api_key}") as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "init",
                        "language": self._language,
                        "model": "auto",
                        "voice_options": {"voice_id": self._voice_id, "speed": 1.0},
                        "output": {"format": "pcm", "sample_rate": SAMPLE_RATE},
                    }
                )
            )

            text_parts = _chunk_text(text)
            for i, part in enumerate(text_parts):
                await ws.send(json.dumps({"type": "text", "text": part, "is_eos": i == len(text_parts) - 1}))

            async for raw in ws:
                message = json.loads(raw)
                if message.get("message_type") != "audio_chunk":
                    continue
                data = message["data"]
                chunks.append(base64.b64decode(data["audio"]))
                if data.get("last_chunk"):
                    break

        return _pcm_to_wav(b"".join(chunks), SAMPLE_RATE)
