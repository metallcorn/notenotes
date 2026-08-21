import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.models import Item, UrlCheckWidget, User
from app.schemas.url_check import UrlCheckWidgetOut
from app.url_check import check_url

router = APIRouter(prefix="/api/url-checks", tags=["url-checks"])


async def _get_widget_with_access(widget_id: uuid.UUID, user: User, db: AsyncSession) -> UrlCheckWidget:
    widget = await db.get(UrlCheckWidget, widget_id)
    if widget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Виджет не найден")
    item = await db.get(Item, widget.item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Виджет не найден")
    await ensure_space_access(db, item.space_id, user.id)
    return widget


def _serialize(widget: UrlCheckWidget) -> UrlCheckWidgetOut:
    return UrlCheckWidgetOut(
        url=widget.url,
        fields=widget.fields,
        last_result=widget.last_result,
        last_fetched_at=widget.last_fetched_at,
        last_status=widget.last_status,
        has_credentials=widget.headers is not None,
    )


@router.get("/{widget_id}", response_model=UrlCheckWidgetOut)
async def get_url_check_widget(
    widget_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UrlCheckWidgetOut:
    """Гидратация карточки (UrlCheckCard.tsx) при монтировании — в content
    заметки лежит только id, реальное состояние (включая url и заголовки
    авторизации — последние не отдаются наружу, см. has_credentials)
    читается отсюда."""
    widget = await _get_widget_with_access(widget_id, user, db)
    return _serialize(widget)


@router.post("/{widget_id}/refresh", response_model=UrlCheckWidgetOut)
async def refresh_url_check_widget(
    widget_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UrlCheckWidgetOut:
    """Кнопка «Обновить» — прямой REST, без участия ассистента. В отличие
    от первой версии этой фичи, НЕ трогает item.content/Yjs/ItemVersion
    вообще: обновляет только эту строку. Заголовки авторизации (если
    есть) резолвятся здесь же, на сервере — с клиента сюда ничего не
    приходит и клиенту сам секрет никогда не отдаётся."""
    widget = await _get_widget_with_access(widget_id, user, db)
    result = await check_url(widget.url, widget.headers)
    if "error" not in result:
        widget.last_result = result.get("body")
        widget.last_fetched_at = datetime.now(timezone.utc)
        widget.last_status = result.get("status_code")
        await db.commit()
        await db.refresh(widget)
    return _serialize(widget)
