import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import TelegramLink, TelegramLinkCode, User
from app.telegram_bot import enqueue_update

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

_CODE_TTL_MINUTES = 10


@router.post("/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # Telegram не шлёт заголовок вовсе, если secret_token не был задан при
    # setWebhook — сравниваем с "", а не None, чтобы не ловить ложный 401,
    # если оператор настроил токен бота, но забыл webhook-секрет.
    if (x_telegram_bot_api_secret_token or "") != settings.telegram_webhook_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    update = await request.json()
    # Кладём в очередь и отвечаем сразу — Telegram ждёт быстрый ответ и
    # ретраит при таймауте; сама обработка (может дёргать Mistral/Deepgram)
    # идёт в фоновом воркере (app/telegram_bot.py:run_worker).
    enqueue_update(update)
    return {"ok": True}


@router.post("/link-code")
async def create_link_code(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.telegram_bot_username:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Telegram-бот не настроен")

    code = secrets.token_urlsafe(16)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)
    db.add(TelegramLinkCode(code=code, user_id=user.id, expires_at=expires_at))
    await db.commit()

    return {
        "deep_link": f"https://t.me/{settings.telegram_bot_username}?start={code}",
        "expires_at": expires_at.isoformat(),
    }


@router.get("/status")
async def get_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    link = await db.get(TelegramLink, user.id)
    return {"linked": link is not None}


@router.delete("/link")
async def unlink(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    link = await db.get(TelegramLink, user.id)
    if link is not None:
        await db.delete(link)
        await db.commit()
    return {"linked": False}
