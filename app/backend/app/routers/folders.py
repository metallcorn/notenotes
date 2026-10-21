import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import realtime
from app.db import get_db
from app.deps import ensure_space_access, get_current_user, is_vault_space
from app.models import Folder, Item, Upload, User
from app.routers.items import _UPLOAD_URL_RE
from app.schemas.folder import FolderCreate, FolderMoveSpace, FolderOut, FolderUpdate

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
            # Папку в её же подпапку — цикл: ни одна из них больше не
            # корень, и обе молча исчезают из дерева. С перетаскиванием
            # мышкой такой бросок — дело одного неточного движения.
            ancestor = parent
            while ancestor is not None:
                if ancestor.id == folder.id:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя вложить папку в её же подпапку")
                ancestor = await db.get(Folder, ancestor.parent_id) if ancestor.parent_id else None
        folder.parent_id = new_parent_id

    await db.commit()
    await db.refresh(folder)
    await realtime.notify_space(folder.space_id, "folders")
    return folder


@router.post("/{folder_id}/move", response_model=FolderOut)
async def move_folder_space(
    folder_id: uuid.UUID,
    payload: FolderMoveSpace,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Folder:
    """Реальная жалоба: переноса ЦЕЛОЙ папки в другой спейс не было вообще
    — только заметка за заметкой (items.py::move_item_space). Папка везёт
    с собой всё поддерево (вложенные папки рекурсивно) и все заметки/
    списки/таблицы внутри них, включая те, что в корзине (иначе они
    остались бы в старом спейсе с folder_id, ссылающимся на папку, которой
    там больше нет — та же дисциплина, что и everywhere в проекте: не
    терять данные тихо)."""
    folder = await _get_owned_folder(db, user, folder_id)
    if payload.space_id == folder.space_id:
        return folder
    await ensure_space_access(db, payload.space_id, user.id)

    # Сейф шифрует title/content на клиенте — массовый перенос с сервера не
    # может ни расшифровать, ни зашифровать content на лету для целой
    # папки заметок сразу. Тот же самый принцип, что и у move_item_space
    # (там перенос ИЗ сейфа тоже недоступен, а В сейф — только через
    # клиентское шифрование одной заметки за раз), просто здесь проще
    # отказать целиком, чем городить пакетное шифрование.
    if await is_vault_space(db, folder.space_id) or await is_vault_space(db, payload.space_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Перенос папок с сейфом не поддерживается")

    old_space_id = folder.space_id

    all_folders = (await db.execute(select(Folder).where(Folder.space_id == old_space_id))).scalars().all()
    children_by_parent: dict[uuid.UUID | None, list[Folder]] = defaultdict(list)
    for f in all_folders:
        children_by_parent[f.parent_id].append(f)

    subtree = [folder]
    stack = [folder.id]
    while stack:
        current_id = stack.pop()
        for child in children_by_parent.get(current_id, []):
            subtree.append(child)
            stack.append(child.id)
    subtree_ids = {f.id for f in subtree}

    for f in subtree:
        f.space_id = payload.space_id
    # Родитель (если был) мог остаться вне поддерева — в целевом спейсе его
    # не существует (та же логика, что у move_item_space: "в целевом
    # старой папки не существует").
    folder.parent_id = None

    items = (await db.execute(select(Item).where(Item.folder_id.in_(subtree_ids)))).scalars().all()
    upload_ids: set[uuid.UUID] = set()
    for item in items:
        item.space_id = payload.space_id
        upload_ids |= {uuid.UUID(m) for m in _UPLOAD_URL_RE.findall(item.content)}

    if upload_ids:
        await db.execute(
            update(Upload).where(Upload.id.in_(upload_ids), Upload.space_id == old_space_id).values(space_id=payload.space_id)
        )

    await db.commit()
    await db.refresh(folder)
    await realtime.notify_space(old_space_id, "folders")
    await realtime.notify_space(old_space_id, "items")
    await realtime.notify_space(payload.space_id, "folders")
    await realtime.notify_space(payload.space_id, "items")
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
