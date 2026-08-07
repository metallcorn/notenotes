import asyncio
import logging

import httpx
import websockets
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.asr.factory import get_asr_client
from app.core.config import Settings, get_settings
from app.deps import get_current_user
from app.models import User
from app.security import decode_session_token
from app.tts.factory import get_tts_client

router = APIRouter(prefix="/api/voice", tags=["voice"])
logger = logging.getLogger(__name__)

PALABRA_ASR_WS_URL = "wss://stream.palabra.ai/asr/v1/speech-to-text/stream"

# Лимит Whisper API (25 МБ) — берём его как общий потолок, с запасом хватает
# и для Deepgram; записанная голосовая реплика в разы меньше.
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class TranscribeOut(BaseModel):
    text: str


class SpeakIn(BaseModel):
    text: str


def _asr_configured(settings: Settings) -> bool:
    if settings.asr_provider == "deepgram":
        return bool(settings.deepgram_api_key)
    if settings.asr_provider == "whisper":
        return bool(settings.whisper_api_key)
    return False


def _tts_configured(settings: Settings) -> bool:
    if settings.tts_provider == "palabra":
        return bool(settings.palabra_api_key)
    return False


@router.post("/transcribe", response_model=TranscribeOut)
async def transcribe(audio: UploadFile = File(...), user: User = Depends(get_current_user)) -> TranscribeOut:
    settings = get_settings()
    if not _asr_configured(settings):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Голосовой ввод ещё не настроен")

    data = await audio.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Аудио слишком большое")

    client = get_asr_client()
    try:
        text = await client.transcribe(data, audio.content_type or "audio/webm")
    except httpx.HTTPError:
        logger.exception("Ошибка обращения к ASR-провайдеру")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Не получилось распознать речь — попробуй ещё раз") from None

    return TranscribeOut(text=text)


@router.post("/speak")
async def speak(payload: SpeakIn, user: User = Depends(get_current_user)) -> Response:
    settings = get_settings()
    if not _tts_configured(settings):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Озвучивание ещё не настроено")

    text = payload.text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой текст")

    client = get_tts_client()
    try:
        audio_bytes = await client.synthesize(text)
    except Exception:
        logger.exception("Ошибка обращения к TTS-провайдеру")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Не получилось озвучить ответ") from None

    return Response(content=audio_bytes, media_type="audio/wav")


@router.websocket("/asr-stream")
async def asr_stream(websocket: WebSocket, language: str = "ru", sample_rate: int = 16000) -> None:
    """Живой стриминг микрофона в Palabra ASR (ТЗ §10a — «разговор с
    ассистентом», не диктовка одной записи). Браузер шлёт бинарные
    PCM s16le-фреймы, мы ретранслируем их в Palabra и гоним её JSON-транскрипты
    обратно — API-ключ никогда не уходит в браузер (это прямое требование
    Palabra: ключ только на сервере)."""
    await websocket.accept()

    settings = get_settings()
    session_token = websocket.cookies.get(settings.session_cookie_name)
    if not session_token or decode_session_token(session_token) is None:
        await websocket.close(code=4401)
        return

    if not settings.palabra_api_key:
        await websocket.send_json(
            {"message_type": "error", "data": {"code": "NOT_CONFIGURED", "desc": "Потоковый голосовой ввод не настроен"}}
        )
        await websocket.close()
        return

    palabra_url = (
        f"{PALABRA_ASR_WS_URL}?token={settings.palabra_api_key}&language={language}"
        f"&format=pcm_s16le&sample_rate={sample_rate}"
    )

    try:
        palabra_ws = await websockets.connect(palabra_url)
    except websockets.InvalidStatusCode as e:
        logger.warning("Palabra ASR отклонил подключение: HTTP %s", e.status_code)
        await websocket.send_json(
            {
                "message_type": "error",
                "data": {"code": "UNAUTHORIZED", "desc": f"Palabra отклонила подключение (HTTP {e.status_code})"},
            }
        )
        await websocket.close()
        return

    try:

        async def relay_audio_in() -> None:
            while True:
                data = await websocket.receive_bytes()
                await palabra_ws.send(data)

        async def relay_transcripts_out() -> None:
            async for message in palabra_ws:
                await websocket.send_text(message)

        tasks = [asyncio.create_task(relay_audio_in()), asyncio.create_task(relay_transcripts_out())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, websockets.ConnectionClosed)):
                raise exc
    except (WebSocketDisconnect, websockets.ConnectionClosed):
        pass
    except Exception:
        logger.exception("Ошибка ASR-стрима через Palabra")
    finally:
        await palabra_ws.close()
        try:
            await websocket.close()
        except RuntimeError:
            pass
