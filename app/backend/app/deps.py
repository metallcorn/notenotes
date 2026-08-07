import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.models import SpaceMember, User

DbSession = AsyncSession


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не авторизован")

    from app.security import decode_session_token

    user_id = decode_session_token(token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия недействительна")

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия недействительна")
    return user


async def ensure_space_access(db: AsyncSession, space_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Спейс на MVP не имеет инвайтов — доступ есть у владельца/участника space_members."""
    result = await db.execute(
        select(SpaceMember).where(SpaceMember.space_id == space_id, SpaceMember.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Спейс не найден")
