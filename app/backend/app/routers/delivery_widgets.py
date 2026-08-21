import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.delivery import track as track_delivery
from app.deps import ensure_space_access, get_current_user
from app.models import DeliveryWidget, Item, User
from app.schemas.delivery import DeliveryWidgetOut

router = APIRouter(prefix="/api/delivery-widgets", tags=["delivery-widgets"])


async def _get_widget_with_access(widget_id: uuid.UUID, user: User, db: AsyncSession) -> DeliveryWidget:
    widget = await db.get(DeliveryWidget, widget_id)
    if widget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Виджет не найден")
    item = await db.get(Item, widget.item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Виджет не найден")
    await ensure_space_access(db, item.space_id, user.id)
    return widget


def _parse(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _serialize(widget: DeliveryWidget) -> DeliveryWidgetOut:
    return DeliveryWidgetOut(
        carrier=widget.carrier,
        tracking_number=widget.tracking_number,
        result=_parse(widget.last_result),
        last_fetched_at=widget.last_fetched_at,
    )


@router.get("/{widget_id}", response_model=DeliveryWidgetOut)
async def get_delivery_widget(
    widget_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DeliveryWidgetOut:
    """Гидратация карточки-виджета (DeliveryWidgetCard.tsx) при монтировании —
    в content заметки лежит только id, состояние читается отсюда."""
    widget = await _get_widget_with_access(widget_id, user, db)
    return _serialize(widget)


@router.post("/{widget_id}/refresh", response_model=DeliveryWidgetOut)
async def refresh_delivery_widget(
    widget_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DeliveryWidgetOut:
    """Кнопка «Обновить» — прямой REST, без ассистента. Опрашивает API
    перевозчика через delivery.track по сохранённым carrier+number и пишет
    только эту строку (не content/Yjs/ItemVersion). Если перевозчик не
    отдал статус — last_result остаётся прежним, ошибку решает клиент."""
    widget = await _get_widget_with_access(widget_id, user, db)
    result = await track_delivery(widget.tracking_number, widget.carrier)
    if not result.get("need_carrier"):
        widget.last_result = json.dumps(result, ensure_ascii=False)
        widget.last_fetched_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(widget)
    return _serialize(widget)
