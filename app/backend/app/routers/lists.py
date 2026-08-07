import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.models import Folder, Item, User
from app.routers.items import create_item_row
from app.schemas.list_item import ListCreate, ListEntryCreate, ListEntryOut, ListEntryUpdate, ListOut
from app.security import decode_session_token

router = APIRouter(prefix="/api/lists", tags=["lists"])

# Realtime-синк списков (ТЗ §12): один backend-процесс, поэтому обычный
# in-memory реестр подключений достаточен — если когда-нибудь появится
# несколько воркеров, это единственное место, которое придётся переделать
# на Redis pub/sub.
_connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flatten_entries(entries: list[dict]) -> str:
    return "\n".join(f"{'[x]' if e['checked'] else '[ ]'} {e['text']}" for e in entries)


def _serialize(item: Item) -> ListOut:
    entries = item.properties.get("entries", [])
    return ListOut(
        id=item.id,
        space_id=item.space_id,
        folder_id=item.folder_id,
        title=item.title,
        entries=[ListEntryOut(**e) for e in entries],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _get_list_item(db: AsyncSession, user: User, list_id: uuid.UUID) -> Item:
    item = await db.get(Item, list_id)
    if item is None or item.material_type != "list" or item.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Список не найден")
    await ensure_space_access(db, item.space_id, user.id)
    return item


async def _broadcast(list_id: uuid.UUID, payload: dict, *, exclude: WebSocket | None = None) -> None:
    dead = []
    for ws in _connections.get(list_id, set()):
        if ws is exclude:
            continue
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections[list_id].discard(ws)


@router.post("", response_model=ListOut, status_code=status.HTTP_201_CREATED)
async def create_list(
    payload: ListCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ListOut:
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
        material_type="list",
        title=payload.title or "Новый список",
        properties={"entries": []},
    )
    return _serialize(item)


@router.get("/{list_id}", response_model=ListOut)
async def get_list(
    list_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ListOut:
    item = await _get_list_item(db, user, list_id)
    return _serialize(item)


@router.post("/{list_id}/entries", response_model=ListOut)
async def add_entry(
    list_id: uuid.UUID,
    payload: ListEntryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ListOut:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой пункт")

    item = await _get_list_item(db, user, list_id)
    entries = list(item.properties.get("entries", []))
    entries.append({"id": str(uuid.uuid4()), "text": text, "checked": False, "created_at": _now_iso()})
    item.properties = {**item.properties, "entries": entries}
    item.content = _flatten_entries(entries)
    await db.commit()
    await db.refresh(item)

    out = _serialize(item)
    await _broadcast(list_id, out.model_dump(mode="json"))
    return out


@router.patch("/{list_id}/entries/{entry_id}", response_model=ListOut)
async def update_entry(
    list_id: uuid.UUID,
    entry_id: str,
    payload: ListEntryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ListOut:
    item = await _get_list_item(db, user, list_id)
    fields = payload.model_fields_set

    # Строим НОВЫЕ словари, а не мутируем существующие in-place: старый и
    # новый entry делили бы один и тот же объект, при сравнении old==new
    # SQLAlchemy решил бы, что properties не изменился, и тихо не записал
    # бы UPDATE в JSONB-колонку.
    entries = []
    found = False
    for entry in item.properties.get("entries", []):
        if entry["id"] == entry_id:
            found = True
            updated = dict(entry)
            if "text" in fields and payload.text is not None:
                updated["text"] = payload.text.strip()
            if "checked" in fields and payload.checked is not None:
                updated["checked"] = payload.checked
            entries.append(updated)
        else:
            entries.append(entry)

    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пункт не найден")

    item.properties = {**item.properties, "entries": entries}
    item.content = _flatten_entries(entries)
    await db.commit()
    await db.refresh(item)

    out = _serialize(item)
    await _broadcast(list_id, out.model_dump(mode="json"))
    return out


@router.delete("/{list_id}/entries/{entry_id}", response_model=ListOut)
async def delete_entry(
    list_id: uuid.UUID,
    entry_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ListOut:
    item = await _get_list_item(db, user, list_id)
    entries = [e for e in item.properties.get("entries", []) if e["id"] != entry_id]
    item.properties = {**item.properties, "entries": entries}
    item.content = _flatten_entries(entries)
    await db.commit()
    await db.refresh(item)

    out = _serialize(item)
    await _broadcast(list_id, out.model_dump(mode="json"))
    return out


@router.websocket("/{list_id}/ws")
async def list_ws(websocket: WebSocket, list_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Клиент ничего не шлёт — только держит соединение и получает
    ListOut целиком при каждом изменении (optimistic UI на клиенте
    сглаживает задержку; last-write-wins на уровне пункта, не всего списка,
    т.к. entries — плоский массив, а не диффы)."""
    await websocket.accept()

    settings = get_settings()
    session_token = websocket.cookies.get(settings.session_cookie_name)
    user_id = decode_session_token(session_token) if session_token else None
    if user_id is None:
        await websocket.close(code=4401)
        return

    item = await db.get(Item, list_id)
    if item is None or item.material_type != "list":
        await websocket.close(code=4404)
        return
    try:
        await ensure_space_access(db, item.space_id, user_id)
    except HTTPException:
        await websocket.close(code=4403)
        return

    _connections[list_id].add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _connections[list_id].discard(websocket)
