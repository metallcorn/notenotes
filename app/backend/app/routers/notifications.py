import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import realtime
from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Notification, User
from app.schemas.notification import NotificationCreateIn, NotificationOut
from app.security import decode_session_token

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    scope: str = "due", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Notification]:
    """scope="due" (по умолчанию) — как раньше, для колокольчика: только уже
    наступившие/немедленные, не спойлерит будущие напоминания в бейдж.
    scope="all" — для полноэкранного центра активности (ActivityView):
    включая ещё не наступившие, чтобы показать раздел "Предстоящие"."""
    query = select(Notification).where(Notification.user_id == user.id)
    if scope != "all":
        query = query.where(
            or_(Notification.trigger_at.is_(None), Notification.trigger_at <= datetime.now(timezone.utc))
        )
    query = query.order_by(Notification.created_at.desc()).limit(300 if scope == "all" else 100)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
async def create_notification(
    payload: NotificationCreateIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Notification:
    """Прямое REST-создание напоминания — то же самое, что делает
    tools/reminders.py's create_reminder для ассистента, но без прохождения
    через диалог/tool-calling: нужно кнопке "Напомнить" на карточке билета
    (TicketAttachmentCard.tsx), где спрашивать пользователя уже не нужно —
    сама кнопка это подтверждение выбранного времени."""
    trigger_at = payload.trigger_at
    if trigger_at.tzinfo is None:
        trigger_at = trigger_at.replace(tzinfo=timezone.utc)
    notification = Notification(
        user_id=user.id, type="reminder", title=payload.title, body=payload.body, trigger_at=trigger_at
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    """Отмена/скрытие — и для ещё не наступившего напоминания (жалоба в
    отзыве: "как его отменить"), и для старого прочитанного, которое просто
    больше не нужно в истории. Диспетчер (notification_dispatch.py) ищет по
    id из выборки — раз строки не будет, отправка сама собой не случится,
    отдельно "отменять" в диспетчере нечего."""
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Уведомление не найдено")
    await db.delete(notification)
    await db.commit()


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


@router.websocket("/ws")
async def notifications_ws(websocket: WebSocket) -> None:
    """Тот же паттерн, что space_ws (routers/spaces.py) — клиент ничего не
    шлёт, только получает {"kind": "notifications"} при новом/наступившем
    уведомлении, чтобы перезапросить react-query кэш вместо ожидания
    очередного опроса (useNotifications, раньше раз в минуту)."""
    await websocket.accept()

    settings = get_settings()
    session_token = websocket.cookies.get(settings.session_cookie_name)
    user_id = decode_session_token(session_token) if session_token else None
    if user_id is None:
        await websocket.close(code=4401)
        return

    realtime.register_user(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        realtime.unregister_user(user_id, websocket)
