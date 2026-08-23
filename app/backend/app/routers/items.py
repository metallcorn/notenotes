import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import collab, realtime
from app.autotag import enqueue_autotag, suggest_tags_now
from app.db import get_db
from app.deps import ensure_space_access, get_current_user, is_vault_space
from app.models import Folder, Item, ItemTag, ItemVersion, Notification, Space, SpaceMember, Tag, Upload, User
from app.schemas.item import (
    DetectedEventDismissIn,
    DetectedEventOut,
    ItemCreate,
    ItemMoveSpace,
    ItemOut,
    ItemTitleSearchResult,
    ItemUpdate,
    ItemVersionOut,
    ShareItemIn,
    ShareItemOut,
)
from app.schemas.tag import ItemTagOut
from app.security import hash_password

# Публичные страницы (routers/public.py) — тот же приём, что у
# SpaceInvite.token (routers/spaces.py): непредсказуемый URL-safe токен,
# сам факт владения ссылкой и есть доказательство доступа.
_SHARE_TOKEN_BYTES = 24

router = APIRouter(prefix="/api/items", tags=["items"])

# Ниже этой длины контент слишком скудный для осмысленных тегов — не тратим
# вызов LLM впустую (та же экономность, что и у остального автообработки).
_MIN_CONTENT_FOR_AUTOTAG = 20

# Тот же substring-приём, что в cleanup.py (комментарий там: "простой
# substring-скан по content дешевле и надёжнее, чем городить отдельный
# индекс связей файл-заметка") — только точечно для одной заметки, чтобы
# найти реально используемые в ней файлы при переносе в другой спейс.
_UPLOAD_URL_RE = re.compile(r"/api/uploads/([0-9a-fA-F-]{36})")

# Общий вес вложений одной заметки — защита от использования заметок как
# файлообменника (реальный запрос), не архитектурное ограничение. Видео/
# аудио сюда сознательно не считаются — у них уже свой потолок 300 МБ НА
# ФАЙЛ (uploads.py, MAX_UPLOAD_BYTES), и одна честная часовая запись
# встречи (реальный названный случай — 50 МБ) сама по себе легко
# превышала бы общий лимит заметки, если бы считалась сюда же. Для
# vault-заметок content на сервере — заглушка "🔒 Зашифровано" (реальный
# markdown с ссылками на /api/uploads/ существует только расшифрованным на
# клиенте), так что скан здесь просто ничего не найдёт — сервер не может
# проверить то, что не может прочитать, и не пытается.
_MAX_NOTE_ATTACHMENTS_BYTES = 100 * 1024 * 1024


async def _check_note_attachments_size(db: AsyncSession, content: str) -> None:
    upload_ids = {uuid.UUID(m) for m in _UPLOAD_URL_RE.findall(content)}
    if not upload_ids:
        return
    result = await db.execute(select(Upload).where(Upload.id.in_(upload_ids)))
    from app.routers.uploads import _is_media_content_type, _upload_path

    total = 0
    for upload in result.scalars():
        if _is_media_content_type(upload.content_type):
            continue
        path = _upload_path(upload.id)
        if path.is_file():
            total += path.stat().st_size
    if total > _MAX_NOTE_ATTACHMENTS_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Общий размер вложений заметки превышает {_MAX_NOTE_ATTACHMENTS_BYTES // (1024 * 1024)} МБ",
        )


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
        vault=item.properties.get("vault"),
        detected_addresses=item.properties.get("detected_addresses") or [],
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
    space_id: uuid.UUID | None = None,
    folder_id: str | None = None,
    tag_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ItemOut]:
    if space_id is not None:
        await ensure_space_access(db, space_id, user.id)
        query = select(Item).where(
            Item.space_id == space_id, Item.material_type.in_(("note", "list", "ticket", "table")), Item.deleted_at.is_(None)
        )
    elif tag_id is not None:
        # Тег — сущность пользователя (Tag.user_id), не спейса: заметки под
        # одним тегом реально лежат в разных спейсах. Без space_id (клик по
        # тегу в сайдбаре, не по папке) фильтруем кросс-спейсово — иначе тег,
        # у которого все заметки не в текущем активном спейсе, выглядел бы
        # пустым, хотя заметки есть (реальная жалоба). Тот же join, что уже
        # в search_items (routers/search.py).
        query = (
            select(Item)
            .join(SpaceMember, SpaceMember.space_id == Item.space_id)
            .join(Space, Space.id == Item.space_id)
            .where(
                SpaceMember.user_id == user.id,
                Item.material_type.in_(("note", "list", "ticket", "table")),
                Item.deleted_at.is_(None),
                # Кросс-спейсовый список (по тегу, не по конкретному спейсу)
                # — та же логика, что в search.py/list_all_items: сейф не
                # должен засветиться там, куда пользователь не заходил явно.
                Space.is_vault.is_(False),
            )
        )
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен space_id или tag_id")

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
        properties={"vault": payload.vault} if payload.vault else None,
    )
    return await _serialize(db, item, user.id)


@router.get("/recent", response_model=list[ItemOut])
async def list_recent_items(
    limit: int = 30, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ItemOut]:
    """Кросс-спейсовая лента "Недавнее" для ActivityView — тот же join, что
    у поиска по тегу без space_id (search.py/list_items с tag_id): пользователь
    видит недавние заметки independent от того, в каком спейсе сейчас
    находится. Регистрируется ДО /{item_id} — иначе "recent" сам попытался
    бы распарситься как UUID и словил бы 422 вместо этого хендлера."""
    query = (
        select(Item)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .join(Space, Space.id == Item.space_id)
        .where(
            SpaceMember.user_id == user.id,
            Item.material_type.in_(("note", "list", "ticket", "table")),
            Item.deleted_at.is_(None),
            # Тот же принцип, что у поиска и list_all_items — сейф не
            # должен светиться в кросс-спейсовой ленте.
            Space.is_vault.is_(False),
        )
        .order_by(Item.updated_at.desc())
        .limit(limit)
    )
    items = (await db.execute(query)).scalars().all()
    return [await _serialize(db, item, user.id) for item in items]


@router.get("/detected-events", response_model=list[DetectedEventOut])
async def list_detected_events(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[DetectedEventOut]:
    """Даты/события, найденные LLM в заметках (app/autotag.py) — пассивные,
    БЕЗ Notification: никуда не рассылаются (Telegram/push/колокольчик), их
    единственное назначение — попасться на глаза в ActivityView. Регистрируется
    ДО /{item_id} по той же причине, что /recent выше."""
    query = (
        select(Item)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .join(Space, Space.id == Item.space_id)
        .where(
            SpaceMember.user_id == user.id,
            Item.material_type == "note",
            Item.deleted_at.is_(None),
            Space.is_vault.is_(False),
            Item.properties.has_key("detected_events"),
        )
    )
    items = (await db.execute(query)).scalars().all()
    # Реальная жалоба: LLM-инструкция "не включай явно прошедшие даты"
    # (autotag.py) соблюдается не всегда — модель верно распознаёт
    # событие, но не всегда сама фильтрует давно прошедшее (например,
    # дату из заметки годичной давности). Не полагаемся на то, что модель
    # сама отсеет — фильтруем детерминированно на дату, как и остальные
    # такие разрывы в проекте (тот же принцип, что transliterate.py).
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    out: list[DetectedEventOut] = []
    for item in items:
        for event in item.properties.get("detected_events") or []:
            at = event.get("at")
            title = event.get("title")
            if not at or not title:
                continue
            try:
                at_dt = datetime.fromisoformat(at)
            except ValueError:
                continue
            if at_dt.tzinfo is None:
                at_dt = at_dt.replace(tzinfo=timezone.utc)
            if at_dt < today_start:
                continue
            out.append(
                DetectedEventOut(
                    item_id=item.id,
                    space_id=item.space_id,
                    item_title=item.title or "Без названия",
                    event_title=title,
                    event_at=at,
                )
            )
    return out


@router.post("/{item_id}/detected-events/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_detected_event(
    item_id: uuid.UUID,
    payload: DetectedEventDismissIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Ложное срабатывание LLM-детектора дат (app/autotag.py) — тот же
    принцип, что у авто-тегов (ТЗ §8.2, CLAUDE.md): предлагает, не
    перекладывает молча, пользователь может убрать. Переклассификация при
    следующем сохранении заметки может вернуть то же событие снова, если
    формулировка в тексте не изменилась — это ожидаемо, не баг."""
    item = await _get_accessible_item(db, user, item_id)
    events = item.properties.get("detected_events") or []
    remaining = [e for e in events if not (e.get("at") == payload.event_at and e.get("title") == payload.event_title)]
    if len(remaining) != len(events):
        item.properties = (
            {**item.properties, "detected_events": remaining}
            if remaining
            else {k: v for k, v in item.properties.items() if k != "detected_events"}
        )
        await db.commit()
        await realtime.notify_space(item.space_id, "items")


@router.get("/search-titles", response_model=list[ItemTitleSearchResult])
async def search_item_titles(
    q: str, space_id: uuid.UUID | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ItemTitleSearchResult]:
    """Автокомплит для вставки ссылки на другую заметку ([[название,
    extensions/NoteLink.ts, ТЗ §7). Не полнотекстовый поиск (search.py) —
    тот заточен под релевантность по СОДЕРЖИМОМУ; тут нужна именно
    подстрока в НАЗВАНИИ, предсказуемая для живого набора по мере ввода.

    ВАЖНО: зарегистрирован ДО GET /{item_id} ниже — Starlette матчит
    маршруты по форме пути, а не по типу параметра, и "/search-titles" —
    один сегмент, как и "/{item_id}"; если бы этот роут стоял ПОСЛЕ, запрос
    сюда сначала попал бы на /{item_id} и упал с 422 (не UUID)."""
    q = q.strip()
    if not q:
        return []
    query = (
        select(Item)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .join(Space, Space.id == Item.space_id)
        .where(
            SpaceMember.user_id == user.id,
            Item.material_type.in_(("note", "list", "ticket", "table")),
            Item.deleted_at.is_(None),
            # Сейф не должен засветиться в автокомплите — тот же принцип,
            # что у кросс-спейсового списка по тегу выше: title/content там
            # заглушка "🔒 Зашифровано" на сервере, реального совпадения по
            # названию всё равно не будет, но лучше не показывать вообще.
            Space.is_vault.is_(False),
            Item.title.ilike(f"%{q}%"),
        )
    )
    if space_id is not None:
        query = query.where(Item.space_id == space_id)
    query = query.order_by(Item.updated_at.desc()).limit(10)
    items = (await db.execute(query)).scalars().all()
    return [
        ItemTitleSearchResult(id=i.id, title=i.title, space_id=i.space_id, material_type=i.material_type)
        for i in items
    ]


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
        await _check_note_attachments_size(db, payload.content)
        item.content = payload.content
    if "folder_id" in fields:
        if payload.folder_id is not None:
            folder = await db.get(Folder, payload.folder_id)
            if folder is None or folder.space_id != item.space_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Папка вне этого спейса")
        item.folder_id = payload.folder_id

    if fields & {"icon", "color", "pinned", "vault"}:
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
        if "vault" in fields:
            if payload.vault:
                properties["vault"] = payload.vault
            else:
                properties.pop("vault", None)
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


@router.post("/{item_id}/move", response_model=ItemOut)
async def move_item_space(
    item_id: uuid.UUID,
    payload: ItemMoveSpace,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    """Перенос заметки/списка в другой спейс пользователя. Отдельный
    endpoint, а не поле в ItemUpdate: у переноса есть побочные эффекты
    (папка теряет смысл, вложенные файлы могут стать недоступны новым
    участникам целевого спейса, нужно уведомить оба спейса по WS), которые
    было бы менее явно размазывать по общему PATCH."""
    item = await _get_accessible_item(db, user, item_id)
    if item.material_type not in ("note", "list", "ticket", "table"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Перенос доступен только для заметок, списков, билетов и таблиц")

    if payload.space_id == item.space_id:
        # Тот же спейс, но другая (в т.ч. вложенная) папка — реальный
        # найденный баг: этот ранний return раньше отдавал item как есть,
        # молча игнорируя folder_id, если MoveItemModal нацеливался на
        # текущий спейс ("visually correct, but doesn't work" — клик
        # проходил, модалка закрывалась, а заметка оставалась на месте).
        if payload.folder_id is not None:
            target_folder = await db.get(Folder, payload.folder_id)
            if target_folder is None or target_folder.space_id != payload.space_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Папка вне этого спейса")
        item.folder_id = payload.folder_id
        await db.commit()
        await db.refresh(item)
        await realtime.notify_space(item.space_id, "items")
        return await _serialize(db, item, user.id)

    # Доступ к ЦЕЛЕВОМУ спейсу — без этого можно было бы закинуть заметку
    # в чужой спейс, куда пользователь не приглашён.
    await ensure_space_access(db, payload.space_id, user.id)

    # Обычный move меняет только space_id — title/content остаются как
    # есть. Перенос ИЗ сейфа наружу так и остаётся не реализован (нужна
    # расшифровка на клиенте перед сохранением plaintext — вне скоупа).
    # Перенос В сейф — реализован на фронте (NoteEditor.tsx): клиент
    # СНАЧАЛА шифрует title/content (и перезаливает вложенные файлы уже
    # зашифрованными в целевой сейф) через обычный PATCH, и только потом
    # зовёт move. Здесь — только страховка: без реально проставленного
    # properties.vault перенос в сейф отклоняем, чтобы баг на фронте не
    # мог протащить plaintext в сейф в обход шифрования. Списки/билеты — не
    # шифруются вообще (properties устроены иначе, чем title/content),
    # для них перенос в сейф закрыт независимо от properties.vault.
    if await is_vault_space(db, item.space_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Перенос из сейфа недоступен")
    if await is_vault_space(db, payload.space_id):
        if item.material_type != "note":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "В сейф можно переносить только заметки")
        if not item.properties.get("vault"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Заметка не зашифрована для сейфа — сначала сохраните её с зашифрованным содержимым",
            )

    old_space_id = item.space_id
    item.space_id = payload.space_id
    # Папки принадлежат спейсу (Folder.space_id) — старая папка в целевом
    # спейсе не существует. По умолчанию сбрасываем в корень (как раньше),
    # но если вызывающий уже знает папку ЦЕЛЕВОГО спейса (см. MoveItemModal
    # на фронте — реальная жалоба на неудобство "перенести и разложить" в
    # два отдельных шага) — раскладываем сразу одним действием.
    if payload.folder_id is not None:
        target_folder = await db.get(Folder, payload.folder_id)
        if target_folder is None or target_folder.space_id != payload.space_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Папка вне целевого спейса")
    item.folder_id = payload.folder_id

    upload_ids = {uuid.UUID(m) for m in _UPLOAD_URL_RE.findall(item.content)}
    if upload_ids:
        await db.execute(
            update(Upload)
            .where(Upload.id.in_(upload_ids), Upload.space_id == old_space_id)
            .values(space_id=payload.space_id)
        )

    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(old_space_id, "items")
    await realtime.notify_space(payload.space_id, "items")
    return await _serialize(db, item, user.id)


def _share_out(item: Item) -> ShareItemOut:
    return ShareItemOut(
        is_public=item.is_public,
        share_token=item.share_token if item.is_public else None,
        has_password=item.share_password_hash is not None,
        share_expires_at=item.share_expires_at,
        share_single_use=item.share_single_use,
        share_used_at=item.share_used_at,
    )


@router.get("/{item_id}/share", response_model=ShareItemOut)
async def get_item_share(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ShareItemOut:
    item = await _get_accessible_item(db, user, item_id)
    return _share_out(item)


@router.post("/{item_id}/share", response_model=ShareItemOut)
async def share_item(
    item_id: uuid.UUID,
    payload: ShareItemIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShareItemOut:
    """Публикация только для заметок в спейсе «Публичные страницы»
    (Space.is_public_pages) — заметку сначала кладут туда, только тогда
    для неё можно настроить ссылку. Любой участник спейса может
    публиковать/снимать с публикации — та же философия равных прав, что
    и у остального в этом спейсе (ensure_space_access не различает
    владельца и участника нигде в кодовой базе)."""
    item = await _get_accessible_item(db, user, item_id)
    if item.material_type != "note":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Публиковать можно только заметки")
    space = await db.get(Space, item.space_id)
    if space is None or not space.is_public_pages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Заметка не в спейсе «Публичные страницы»")

    item.is_public = True
    item.share_token = secrets.token_urlsafe(_SHARE_TOKEN_BYTES)
    item.share_password_hash = hash_password(payload.password) if payload.password else None
    item.share_expires_at = (
        datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    )
    item.share_single_use = payload.single_use
    item.share_used_at = None
    await db.commit()
    await db.refresh(item)
    return _share_out(item)


@router.post("/{item_id}/unshare", response_model=ShareItemOut)
async def unshare_item(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ShareItemOut:
    """is_public=False + токен обнуляется целиком (не просто прячется) —
    старая ссылка перестаёт работать безвозвратно, повторная публикация
    всегда выдаёт новый токен."""
    item = await _get_accessible_item(db, user, item_id)
    item.is_public = False
    item.share_token = None
    item.share_password_hash = None
    item.share_expires_at = None
    item.share_single_use = False
    item.share_used_at = None
    await db.commit()
    await db.refresh(item)
    return _share_out(item)


# Реальный запрос: не всегда хочется удалять заметку (даже мягко, через
# корзину — та автоматически чистится, см. cleanup.py) — часто нужно
# просто убрать с глаз то, что "вроде уже не надо, а вдруг понадобится".
# Обычная папка, не отдельная сущность: переиспользует всё, что уже есть у
# папок (видна в дереве, из неё можно достать заметку тем же "Переместить").
ARCHIVE_FOLDER_NAME = "Архив"


@router.post("/{item_id}/archive", response_model=ItemOut)
async def archive_item(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    """Перенос в папку «Архив» текущего спейса (создаётся при первом
    использовании) — альтернатива удалению для заметок, которые не нужны
    прямо сейчас, но жалко терять насовсем."""
    item = await _get_accessible_item(db, user, item_id)
    if item.material_type not in ("note", "list", "ticket", "table"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "В архив можно переносить только заметки, списки, билеты и таблицы")

    folder = (
        await db.execute(
            select(Folder).where(
                Folder.space_id == item.space_id,
                Folder.parent_id.is_(None),
                Folder.name == ARCHIVE_FOLDER_NAME,
            )
        )
    ).scalars().first()
    if folder is None:
        folder = Folder(space_id=item.space_id, parent_id=None, name=ARCHIVE_FOLDER_NAME)
        db.add(folder)
        await db.flush()

    item.folder_id = folder.id
    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
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
    # Реальная жалоба: Notification.payload — JSONB без FK на items.id
    # (свободная структура, разные типы уведомлений хранят в ней разное),
    # каскад на уровне БД её никак не заденет — уведомление о напоминании
    # для этой заметки осталось бы висеть и ссылаться на уже несуществующий
    # item_id (ошибка при попытке открыть его из уведомления).
    await db.execute(delete(Notification).where(Notification.payload["item_id"].astext == str(item_id)))
    await db.delete(item)
    await db.commit()
    await realtime.notify_space(space_id, "items")


@router.delete("/trash/empty", status_code=status.HTTP_204_NO_CONTENT)
async def empty_trash(
    space_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    """Удалить навсегда всё содержимое корзины спейса разом — тот же
    разрушительный путь, что и /{item_id}/permanent, просто за один клик
    вместо по одной заметке."""
    await ensure_space_access(db, space_id, user.id)
    items = (
        await db.execute(select(Item).where(Item.space_id == space_id, Item.deleted_at.is_not(None)))
    ).scalars().all()
    if not items:
        return
    for item in items:
        await db.execute(delete(Notification).where(Notification.payload["item_id"].astext == str(item.id)))
        await db.delete(item)
    await db.commit()
    await realtime.notify_space(space_id, "items")


@router.get("/{item_id}/backlinks", response_model=list[ItemOut])
async def item_backlinks(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ItemOut]:
    """Заметки, ссылающиеся НА эту (ТЗ §7 — "бэкенд парсит и строит
    связи"). NoteLink.ts хранит в content только data-item-id — тот же
    substring-скан по всем content'ам, что уже применяется в cleanup.py
    для upload_id (масштаб 2-10 пользователей делает отдельную таблицу
    связей избыточной — не заводим её ради этого)."""
    await _get_accessible_item(db, user, item_id)
    query = (
        select(Item)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .where(
            SpaceMember.user_id == user.id,
            Item.deleted_at.is_(None),
            Item.id != item_id,
            Item.content.like(f"%{item_id}%"),
        )
        .order_by(Item.updated_at.desc())
    )
    items = (await db.execute(query)).scalars().all()
    return [await _serialize(db, item, user.id) for item in items]


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
    if item.material_type == "list":
        # У списка правда живёт в properties.entries, не в content (тот —
        # только плоский текстовый слепок для поиска/предпросмотра, см.
        # routers/lists.py::_flatten_entries). Просто откатить content без
        # entries выглядело бы так, будто откат ничего не сделал —
        # ListEditor.tsx читает entries, не content. Отложенный импорт —
        # lists.py уже импортирует из этого модуля, обычный top-level был
        # бы циклом (тот же приём, что vision.py → tickets.py).
        from app.routers.lists import parse_entries_text

        item.properties = {**item.properties, "entries": parse_entries_text(version.content)}

    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    # Реальный найденный баг: этот эндпоинт пишет item.content НАПРЯМУЮ, в
    # обход Yjs, точно тем же способом, что уже был найден и исправлен для
    # vision.py/pdf_processing.py/tickets.py/tools/notes.py — но сюда чинку
    # тогда не довели. Без invalidate_room у заметки с открытой живой
    # коллаборацией результат отката никогда не долетал до редактора: он
    # продолжал показывать устаревший Y.Doc, и ближайший автосейв из него
    # молча затирал только что восстановленную версию обратно.
    await collab.invalidate_room(item.id)
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
