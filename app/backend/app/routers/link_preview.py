from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.link_preview import fetch_preview
from app.models import LinkPreview, User
from app.schemas.link_preview import LinkPreviewOut

router = APIRouter(prefix="/api/link-preview", tags=["link-preview"])

MAX_URL_LENGTH = 2000


@router.get("", response_model=LinkPreviewOut)
async def get_link_preview(
    url: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> LinkPreview:
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректная ссылка")

    existing = (await db.execute(select(LinkPreview).where(LinkPreview.url == url))).scalar_one_or_none()
    if existing is not None:
        return existing

    data = await fetch_preview(url)
    preview = LinkPreview(url=url, **data)
    db.add(preview)
    try:
        await db.commit()
    except Exception:
        # Гонка: два одновременных запроса на одну и ту же новую ссылку
        # (url уникален) — второй проигравший просто читает то, что
        # сохранил первый, вместо падения 500.
        await db.rollback()
        existing = (await db.execute(select(LinkPreview).where(LinkPreview.url == url))).scalar_one_or_none()
        if existing is not None:
            return existing
        raise
    await db.refresh(preview)
    return preview
