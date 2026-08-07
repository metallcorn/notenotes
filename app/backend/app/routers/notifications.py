import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import Notification, User
from app.schemas.notification import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Notification]:
    result = await db.execute(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100)
    )
    return list(result.scalars().all())


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Notification:
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Уведомление не найдено")
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(notification)
    return notification


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(
        select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    now = datetime.now(timezone.utc)
    for notification in result.scalars().all():
        notification.read_at = now
    await db.commit()
