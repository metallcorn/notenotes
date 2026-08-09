from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import PushSubscription, User

router = APIRouter(prefix="/api/push", tags=["push"])


class PushSubscribeIn(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class PushUnsubscribeIn(BaseModel):
    endpoint: str


@router.get("/vapid-public-key")
async def vapid_public_key() -> dict:
    return {"key": get_settings().vapid_public_key}


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    payload: PushSubscribeIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    existing = (
        await db.execute(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    ).scalar_one_or_none()
    if existing is not None:
        # Тот же endpoint может переподписаться (обновились ключи) —
        # обновляем на месте, не плодим дубликаты по unique(endpoint).
        existing.user_id = user.id
        existing.p256dh = payload.p256dh
        existing.auth = payload.auth
    else:
        db.add(PushSubscription(user_id=user.id, endpoint=payload.endpoint, p256dh=payload.p256dh, auth=payload.auth))
    await db.commit()


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    payload: PushUnsubscribeIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == payload.endpoint, PushSubscription.user_id == user.id
        )
    )
    await db.commit()
