import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.models import Space, SpaceMember, User
from app.schemas.space import SpaceCreate, SpaceOut, SpaceUpdate

router = APIRouter(prefix="/api/spaces", tags=["spaces"])


@router.get("", response_model=list[SpaceOut])
async def list_spaces(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[Space]:
    result = await db.execute(
        select(Space).join(SpaceMember, SpaceMember.space_id == Space.id).where(SpaceMember.user_id == user.id)
    )
    return list(result.scalars().all())


@router.post("", response_model=SpaceOut, status_code=201)
async def create_space(
    payload: SpaceCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Space:
    space = Space(name=payload.name, owner_id=user.id)
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=user.id))
    await db.commit()
    await db.refresh(space)
    return space


@router.patch("/{space_id}", response_model=SpaceOut)
async def update_space(
    space_id: uuid.UUID,
    payload: SpaceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Space:
    await ensure_space_access(db, space_id, user.id)
    space = await db.get(Space, space_id)
    if space is None:
        # Недостижимо на практике: space_members.space_id — CASCADE на
        # spaces.id, так что раз ensure_space_access нашла членство, сам
        # спейс точно есть. Проверка только чтобы не возвращать Space | None.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Спейс не найден")
    space.name = payload.name
    await db.commit()
    await db.refresh(space)
    return space
