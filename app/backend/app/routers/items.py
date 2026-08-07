import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import realtime
from app.autotag import enqueue_autotag, suggest_tags_now
from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.models import Folder, Item, ItemTag, ItemVersion, Tag, User
from app.schemas.item import ItemCreate, ItemOut, ItemUpdate, ItemVersionOut
from app.schemas.tag import ItemTagOut

router = APIRouter(prefix="/api/items", tags=["items"])

# Ниже этой длины контент слишком скудный для осмысленных тегов — не тратим
# вызов LLM впустую (та же экономность, что и у остального автообработки).
_MIN_CONTENT_FOR_AUTOTAG = 20


async def _tags_for_item(db: AsyncSession, item_id: uuid.UUID, user_id: uuid.UUID) -> list[ItemTagOut]:
    result = await db.execute(
        select(Tag, ItemTag.auto)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .where(ItemTag.item_id == item_id, ItemTag.user_id == user_id)
        .order_by(Tag.name)
    )
    return [ItemTagOut(id=t.id, name=t.name, created_at=t.created_at, auto=auto) for t, auto in result.all()]


async def _serialize(db: AsyncSession, item: Item, user_id: uuid.UUID) -> ItemOut:
    tags = await _tags_for_item(db, item.id, user_id)
    return ItemOut(
        id=item.id,
        space_id=item.space_id,
        folder_id=item.folder_id,
        author_id=item.author_id,
        material_type=item.material_type,
        title=item.title,
        content=item.content,
        created_at=item.created_at,
        updated_at=item.updated_at,
        tags=tags,
        icon=item.properties.get("icon"),
        color=item.properties.get("color"),
        pinned=bool(item.properties.get("pinned", False)),
        deleted_at=item.deleted_at,
    )


async def _get_accessible_item(
    db: AsyncSession, user: User, item_id: uuid.UUID, *, include_deleted: bool = False
) -> Item:
    item = await db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заметка не найдена")
    await ensure_space_access(db, item.space_id, user.id)
    if item.deleted_at is not None and not include_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заметка не найдена")
    return item


async def create_item_row(
    db: AsyncSession,
    *,
    space_id: uuid.UUID,
    author_id: uuid.UUID,
    material_type: str,
    title: str = "",
    content: str = "",
    folder_id: uuid.UUID | None = None,
    properties: dict | None = None,
) -> Item:
    """Общая точка создания item — переиспользуется тулами ассистента
    (create_note), чтобы не дублировать и не дёргать свой же HTTP."""
    item = Item(
        space_id=space_id,
        folder_id=folder_id,
        author_id=author_id,
        material_type=material_type,
        title=title,
        content=content,
        properties=properties or {},
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "dialogs" if material_type == "dialog" else "items")
    if material_type == "note" and len(content.strip()) >= _MIN_CONTENT_FOR_AUTOTAG:
        enqueue_autotag(item.id)
    return item


@router.get("", response_model=list[ItemOut])
async def list_items(
    space_id: uuid.UUID,
    folder_id: str | None = None,
    tag_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ItemOut]:
    await ensure_space_access(db, space_id, user.id)
    query = select(Item).where(
        Item.space_id == space_id, Item.material_type.in_(("note", "list")), Item.deleted_at.is_(None)
    )

    if folder_id == "root":
        query = query.where(Item.folder_id.is_(None))
    elif folder_id:
        query = query.where(Item.folder_id == uuid.UUID(folder_id))

    if tag_id is not None:
        query = query.join(ItemTag, ItemTag.item_id == Item.id).where(
            ItemTag.tag_id == tag_id, ItemTag.user_id == user.id
        )

    query = query.order_by(Item.updated_at.desc())
    items = (await db.execute(query)).scalars().all()
    return [await _serialize(db, item, user.id) for item in items]


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: ItemCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    await ensure_space_access(db, payload.space_id, user.id)
    if payload.folder_id is not None:
        folder = await db.get(Folder, payload.folder_id)
        if folder is None or folder.space_id != payload.space_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Папка вне этого спейса")

    item = await create_item_row(
        db,
        space_id=payload.space_id,
        folder_id=payload.folder_id,
        author_id=user.id,
        material_type="note",
        title=payload.title,
        content=payload.content,
    )
    return await _serialize(db, item, user.id)


@router.get("/{item_id}", response_model=ItemOut)
async def get_item(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await _get_accessible_item(db, user, item_id)
    return await _serialize(db, item, user.id)


@router.patch("/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: uuid.UUID,
    payload: ItemUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    item = await _get_accessible_item(db, user, item_id)
    fields = payload.model_fields_set

    content_changed = ("title" in fields and payload.title != item.title) or (
        "content" in fields and payload.content != item.content
    )
    if content_changed:
        db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=user.id))

    if "title" in fields and payload.title is not None:
        item.title = payload.title
    if "content" in fields and payload.content is not None:
        item.content = payload.content
    if "folder_id" in fields:
        if payload.folder_id is not None:
            folder = await db.get(Folder, payload.folder_id)
            if folder is None or folder.space_id != item.space_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Папка вне этого спейса")
        item.folder_id = payload.folder_id

    if fields & {"icon", "color", "pinned"}:
        # Косметика заметки живёт в properties (JSONB) — не заводить под неё
        # типизированные колонки. Переприсваиваем весь dict, а не мутируем
        # in-place: иначе SQLAlchemy не увидит изменение JSONB-колонки.
        properties = dict(item.properties)
        if "icon" in fields:
            if payload.icon:
                properties["icon"] = payload.icon
            else:
                properties.pop("icon", None)
        if "color" in fields:
            if payload.color:
                properties["color"] = payload.color
            else:
                properties.pop("color", None)
        if "pinned" in fields:
            properties["pinned"] = bool(payload.pinned)
        item.properties = properties

    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "items")

    # Заметку обычно создают пустой и печатают в неё — на create_item_row
    # тегировать было нечего. Тегируем один раз, когда контент дорос до
    # осмысленной длины, и только если тегов ещё нет вообще (ни ручных, ни
    # авто) — не переклассифицируем на каждое сохранение.
    if item.material_type == "note" and "content" in fields and len(item.content.strip()) >= _MIN_CONTENT_FOR_AUTOTAG:
        has_tags = (
            await db.execute(
                select(ItemTag.item_id).where(ItemTag.item_id == item.id, ItemTag.user_id == user.id).limit(1)
            )
        ).scalar_one_or_none()
        if has_tags is None:
            enqueue_autotag(item.id)

    return await _serialize(db, item, user.id)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    # Мягкое удаление, не DELETE FROM: с delete_note теперь может дёргать
    # и AI-ассистент, а не только клик человека — цена ошибки должна быть
    # обратимой. Настоящее удаление — только через /permanent из корзины.
    item = await _get_accessible_item(db, user, item_id)
    item.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    await realtime.notify_space(item.space_id, "items")


@router.get("/trash/list", response_model=list[ItemOut])
async def list_trash(
    space_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ItemOut]:
    await ensure_space_access(db, space_id, user.id)
    query = (
        select(Item)
        .where(Item.space_id == space_id, Item.deleted_at.is_not(None))
        .order_by(Item.deleted_at.desc())
    )
    items = (await db.execute(query)).scalars().all()
    return [await _serialize(db, item, user.id) for item in items]


@router.post("/{item_id}/restore", response_model=ItemOut)
async def restore_item(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await _get_accessible_item(db, user, item_id, include_deleted=True)
    item.deleted_at = None
    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    return await _serialize(db, item, user.id)


@router.delete("/{item_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item_permanent(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    # Единственный по-настоящему разрушительный путь во всём API — только
    # из корзины, руками, никогда через AI-тул.
    item = await _get_accessible_item(db, user, item_id, include_deleted=True)
    space_id = item.space_id
    await db.delete(item)
    await db.commit()
    await realtime.notify_space(space_id, "items")


@router.get("/{item_id}/versions", response_model=list[ItemVersionOut])
async def list_versions(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ItemVersion]:
    await _get_accessible_item(db, user, item_id)
    result = await db.execute(
        select(ItemVersion).where(ItemVersion.item_id == item_id).order_by(ItemVersion.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/{item_id}/versions/{version_id}/revert", response_model=ItemOut)
async def revert_version(
    item_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    item = await _get_accessible_item(db, user, item_id)
    version = await db.get(ItemVersion, version_id)
    if version is None or version.item_id != item.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Версия не найдена")

    # Текущее состояние сохраняется как версия перед откатом — откат
    # не разрушает историю, а добавляет к ней (CLAUDE.md: история версий
    # недеструктивна).
    db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=user.id))
    item.title = version.title
    item.content = version.content

    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    return await _serialize(db, item, user.id)


@router.post("/{item_id}/suggest-tags", response_model=ItemOut)
async def suggest_tags(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    """Ручной триггер автотегирования (кнопка «Предложить теги» в редакторе) —
    в отличие от автоматического запуска при создании/редактировании, тут
    работает независимо от того, есть ли у заметки уже теги."""
    item = await _get_accessible_item(db, user, item_id)
    if item.material_type != "note":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Автотеги доступны только для заметок")

    await suggest_tags_now(item.id)
    return await _serialize(db, item, user.id)


@router.post("/{item_id}/tags/{tag_id}", response_model=ItemOut)
async def add_tag(
    item_id: uuid.UUID, tag_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await _get_accessible_item(db, user, item_id)
    tag = await db.get(Tag, tag_id)
    if tag is None or tag.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тег не найден")

    existing = await db.execute(
        select(ItemTag).where(ItemTag.item_id == item.id, ItemTag.tag_id == tag.id, ItemTag.user_id == user.id)
    )
    if existing.scalar_one_or_none() is None:
        db.add(ItemTag(item_id=item.id, tag_id=tag.id, user_id=user.id))
        await db.commit()
        await realtime.notify_space(item.space_id, "items")

    return await _serialize(db, item, user.id)


@router.delete("/{item_id}/tags/{tag_id}", response_model=ItemOut)
async def remove_tag(
    item_id: uuid.UUID, tag_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await _get_accessible_item(db, user, item_id)
    existing = await db.execute(
        select(ItemTag).where(ItemTag.item_id == item.id, ItemTag.tag_id == tag_id, ItemTag.user_id == user.id)
    )
    link = existing.scalar_one_or_none()
    if link is not None:
        await db.delete(link)
        await db.commit()
        await realtime.notify_space(item.space_id, "items")

    return await _serialize(db, item, user.id)
