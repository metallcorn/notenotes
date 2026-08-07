import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import ItemTag, Tag, User
from app.schemas.tag import TagCreate, TagMerge, TagOut, TagUpdate

router = APIRouter(prefix="/api/tags", tags=["tags"])


async def _get_own_tag(db: AsyncSession, user: User, tag_id: uuid.UUID) -> Tag:
    tag = await db.get(Tag, tag_id)
    if tag is None or tag.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тег не найден")
    return tag


@router.get("", response_model=list[TagOut])
async def list_tags(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[Tag]:
    result = await db.execute(select(Tag).where(Tag.user_id == user.id).order_by(Tag.name))
    return list(result.scalars().all())


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    payload: TagCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Tag:
    existing = await db.execute(select(Tag).where(Tag.user_id == user.id, Tag.name == payload.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой тег уже есть")

    tag = Tag(user_id=user.id, name=payload.name)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


@router.patch("/{tag_id}", response_model=TagOut)
async def rename_tag(
    tag_id: uuid.UUID, payload: TagUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Tag:
    tag = await _get_own_tag(db, user, tag_id)
    existing = await db.execute(
        select(Tag).where(Tag.user_id == user.id, Tag.name == payload.name, Tag.id != tag_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой тег уже есть")

    tag.name = payload.name
    await db.commit()
    await db.refresh(tag)
    return tag


@router.post("/{tag_id}/merge", response_model=TagOut)
async def merge_tag(
    tag_id: uuid.UUID, payload: TagMerge, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Tag:
    source = await _get_own_tag(db, user, tag_id)
    target = await _get_own_tag(db, user, payload.target_tag_id)
    if source.id == target.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя слить тег с самим собой")

    links = (await db.execute(select(ItemTag).where(ItemTag.tag_id == source.id))).scalars().all()
    for link in links:
        already_tagged = await db.execute(
            select(ItemTag).where(
                ItemTag.item_id == link.item_id, ItemTag.tag_id == target.id, ItemTag.user_id == link.user_id
            )
        )
        if already_tagged.scalar_one_or_none() is None:
            db.add(ItemTag(item_id=link.item_id, tag_id=target.id, user_id=link.user_id))
        await db.delete(link)

    await db.delete(source)
    await db.commit()
    await db.refresh(target)
    return target


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    tag = await _get_own_tag(db, user, tag_id)
    await db.delete(tag)
    await db.commit()
