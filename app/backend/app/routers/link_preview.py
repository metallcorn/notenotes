from datetime import datetime, timedelta, timezone

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

# Успешные превью — бессрочный кэш (см. docstring LinkPreview), но
# fetch_failed раньше кэшировался с той же вечностью — реальная жалоба:
# сайт, отдавший урезанную страницу без <title> одному-единственному
# запросу (например, из-за User-Agent — уже отдельно починено), навсегда
# застревал "не обработалась", даже после того как первопричина устранена
# на нашей стороне. Неудача — не такое надёжное знание о сайте, как
# успех; даёт себе шанс на перефетч, а не требует ручного вмешательства в БД.
_FAILED_RETRY_AFTER = timedelta(hours=24)


@router.get("", response_model=LinkPreviewOut)
async def get_link_preview(
    url: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> LinkPreview:
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректная ссылка")

    existing = (await db.execute(select(LinkPreview).where(LinkPreview.url == url))).scalar_one_or_none()
    stale_failure = (
        existing is not None
        and existing.fetch_failed
        and datetime.now(timezone.utc) - existing.fetched_at > _FAILED_RETRY_AFTER
    )
    if existing is not None and not stale_failure:
        return existing

    data = await fetch_preview(url)
    if existing is not None:
        for key, value in data.items():
            setattr(existing, key, value)
        existing.fetched_at = datetime.now(timezone.utc)
        preview = existing
    else:
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
