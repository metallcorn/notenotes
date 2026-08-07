import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import realtime
from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.models import Folder, User
from app.schemas.folder import FolderCreate, FolderOut, FolderUpdate

router = APIRouter(prefix="/api/folders", tags=["folders"])


async def _get_owned_folder(db: AsyncSession, user: User, folder_id: uuid.UUID) -> Folder:
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
    await ensure_space_access(db, folder.space_id, user.id)
    return folder


@router.get("", response_model=list[FolderOut])
async def list_folders(
    space_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Folder]:
    await ensure_space_access(db, space_id, user.id)
    result = await db.execute(select(Folder).where(Folder.space_id == space_id))
    return list(result.scalars().all())


@router.post("", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    payload: FolderCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Folder:
    await ensure_space_access(db, payload.space_id, user.id)
    if payload.parent_id is not None:
        parent = await db.get(Folder, payload.parent_id)
        if parent is None or parent.space_id != payload.space_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Родительская папка вне этого спейса")

    folder = Folder(space_id=payload.space_id, parent_id=payload.parent_id, name=payload.name)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    await realtime.notify_space(folder.space_id, "folders")
    return folder


@router.patch("/{folder_id}", response_model=FolderOut)
async def update_folder(
    folder_id: uuid.UUID,
    payload: FolderUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Folder:
    folder = await _get_owned_folder(db, user, folder_id)
    fields = payload.model_fields_set

    if "name" in fields and payload.name is not None:
        folder.name = payload.name

    if "parent_id" in fields:
        new_parent_id = payload.parent_id
        if new_parent_id == folder.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Папка не может быть родителем самой себе")
        if new_parent_id is not None:
            parent = await db.get(Folder, new_parent_id)
            if parent is None or parent.space_id != folder.space_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Родительская папка вне этого спейса")
        folder.parent_id = new_parent_id

    await db.commit()
    await db.refresh(folder)
    await realtime.notify_space(folder.space_id, "folders")
    return folder


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    folder = await _get_owned_folder(db, user, folder_id)
    space_id = folder.space_id
    await db.delete(folder)
    await db.commit()
    await realtime.notify_space(space_id, "folders")
