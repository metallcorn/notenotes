import csv
import io
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import ensure_space_access, get_current_user, is_vault_space
from app.models import Folder, Item, User
from app.routers.items import create_item_row
from app.schemas.table_item import (
    TableColumnCreate,
    TableColumnOut,
    TableCreate,
    TableOut,
    TableRowCreate,
    TableRowOut,
    TableRowUpdate,
)
from app.security import decode_session_token

router = APIRouter(prefix="/api/tables", tags=["tables"])

# Свой реестр WS-подключений, не общий со списками (routers/lists.py) —
# иначе один процесс рассылал бы обновления таблиц подписчикам списков и
# наоборот. Тот же однопроцессный in-memory приём, та же оговорка: при
# нескольких воркерах backend'а понадобится Redis pub/sub.
_connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flatten_table(columns: list[dict], rows: list[dict]) -> str:
    """Тот же приём, что routers/lists.py::_flatten_entries — плоский
    текстовый слепок в Item.content, не для показа, а чтобы обычный
    полнотекстовый поиск (search_items — ищет по Item.content) и превью в
    NoteList находили содержимое таблицы, а не только её название."""
    if not columns:
        return ""
    header = " | ".join(c["name"] for c in columns)
    lines = [header]
    for row in rows:
        lines.append(" | ".join(row["cells"].get(c["id"], "") for c in columns))
    return "\n".join(lines)


def _serialize(item: Item) -> TableOut:
    columns = item.properties.get("columns", [])
    rows = item.properties.get("rows", [])
    return TableOut(
        id=item.id,
        space_id=item.space_id,
        folder_id=item.folder_id,
        title=item.title,
        columns=[TableColumnOut(**c) for c in columns],
        rows=[TableRowOut(**r) for r in rows],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _get_table_item(db: AsyncSession, user: User, table_id: uuid.UUID) -> Item:
    item = await db.get(Item, table_id)
    if item is None or item.material_type != "table" or item.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Таблица не найдена")
    await ensure_space_access(db, item.space_id, user.id)
    return item


async def _broadcast(table_id: uuid.UUID, payload: dict, *, exclude: WebSocket | None = None) -> None:
    dead = []
    for ws in _connections.get(table_id, set()):
        if ws is exclude:
            continue
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections[table_id].discard(ws)


@router.post("", response_model=TableOut, status_code=status.HTTP_201_CREATED)
async def create_table(
    payload: TableCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> TableOut:
    await ensure_space_access(db, payload.space_id, user.id)
    if await is_vault_space(db, payload.space_id):
        # Тот же случай, что и у списков (routers/lists.py::create_list) —
        # структурные данные живут в properties, не в title/content,
        # шифрование properties на клиенте — отдельная, ещё не сделанная
        # работа. Честнее отказать, чем молча положить plaintext в "сейф".
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Таблицы в сейфе пока не поддерживаются")
    if payload.folder_id is not None:
        folder = await db.get(Folder, payload.folder_id)
        if folder is None or folder.space_id != payload.space_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Папка вне этого спейса")

    columns = [{"id": str(uuid.uuid4()), "name": c.name.strip(), "type": c.type} for c in payload.columns if c.name.strip()]

    item = await create_item_row(
        db,
        space_id=payload.space_id,
        folder_id=payload.folder_id,
        author_id=user.id,
        material_type="table",
        title=payload.title or "Новая таблица",
        content=_flatten_table(columns, []),
        properties={"columns": columns, "rows": []},
    )
    return _serialize(item)


@router.get("/{table_id}", response_model=TableOut)
async def get_table(
    table_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> TableOut:
    item = await _get_table_item(db, user, table_id)
    return _serialize(item)


@router.post("/{table_id}/columns", response_model=TableOut)
async def add_column(
    table_id: uuid.UUID,
    payload: TableColumnCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TableOut:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое название столбца")

    item = await _get_table_item(db, user, table_id)
    columns = list(item.properties.get("columns", []))
    columns.append({"id": str(uuid.uuid4()), "name": name, "type": payload.type})
    item.properties = {**item.properties, "columns": columns}
    item.content = _flatten_table(columns, item.properties.get("rows", []))
    await db.commit()
    await db.refresh(item)

    out = _serialize(item)
    await _broadcast(table_id, out.model_dump(mode="json"))
    return out


@router.patch("/{table_id}/columns/{column_id}", response_model=TableOut)
async def update_column(
    table_id: uuid.UUID,
    column_id: str,
    payload: TableColumnCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TableOut:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое название столбца")

    item = await _get_table_item(db, user, table_id)
    columns = []
    found = False
    for col in item.properties.get("columns", []):
        if col["id"] == column_id:
            found = True
            columns.append({"id": col["id"], "name": name, "type": payload.type})
        else:
            columns.append(col)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Столбец не найден")

    item.properties = {**item.properties, "columns": columns}
    item.content = _flatten_table(columns, item.properties.get("rows", []))
    await db.commit()
    await db.refresh(item)

    out = _serialize(item)
    await _broadcast(table_id, out.model_dump(mode="json"))
    return out


@router.delete("/{table_id}/columns/{column_id}", response_model=TableOut)
async def delete_column(
    table_id: uuid.UUID,
    column_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TableOut:
    item = await _get_table_item(db, user, table_id)
    columns = [c for c in item.properties.get("columns", []) if c["id"] != column_id]
    # Удаление столбца целиком — включая соответствующий ключ ячейки в
    # КАЖДОЙ строке, иначе он остался бы мусором в properties и всплыл бы
    # при повторном создании столбца с тем же именем (другим id, но старые
    # данные под старым id никуда не делись бы).
    rows = [{**r, "cells": {k: v for k, v in r["cells"].items() if k != column_id}} for r in item.properties.get("rows", [])]
    item.properties = {**item.properties, "columns": columns, "rows": rows}
    item.content = _flatten_table(columns, rows)
    await db.commit()
    await db.refresh(item)

    out = _serialize(item)
    await _broadcast(table_id, out.model_dump(mode="json"))
    return out


@router.post("/{table_id}/rows", response_model=TableOut)
async def add_row(
    table_id: uuid.UUID,
    payload: TableRowCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TableOut:
    item = await _get_table_item(db, user, table_id)
    rows = list(item.properties.get("rows", []))
    rows.append({"id": str(uuid.uuid4()), "cells": dict(payload.cells), "created_at": _now_iso()})
    item.properties = {**item.properties, "rows": rows}
    item.content = _flatten_table(item.properties.get("columns", []), rows)
    await db.commit()
    await db.refresh(item)

    out = _serialize(item)
    await _broadcast(table_id, out.model_dump(mode="json"))
    return out


@router.patch("/{table_id}/rows/{row_id}", response_model=TableOut)
async def update_row(
    table_id: uuid.UUID,
    row_id: str,
    payload: TableRowUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TableOut:
    item = await _get_table_item(db, user, table_id)

    # Строим НОВЫЕ словари, а не мутируем существующие in-place — тот же
    # приём, что в routers/lists.py::update_entry: иначе SQLAlchemy не
    # увидит изменение JSONB-колонки (старый и новый объект будут одним и
    # тем же, сравнение old==new не найдёт разницы).
    rows = []
    found = False
    for row in item.properties.get("rows", []):
        if row["id"] == row_id:
            found = True
            merged_cells = {**row["cells"], **payload.cells}
            rows.append({**row, "cells": merged_cells})
        else:
            rows.append(row)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Строка не найдена")

    item.properties = {**item.properties, "rows": rows}
    item.content = _flatten_table(item.properties.get("columns", []), rows)
    await db.commit()
    await db.refresh(item)

    out = _serialize(item)
    await _broadcast(table_id, out.model_dump(mode="json"))
    return out


@router.delete("/{table_id}/rows/{row_id}", response_model=TableOut)
async def delete_row(
    table_id: uuid.UUID,
    row_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TableOut:
    item = await _get_table_item(db, user, table_id)
    rows = [r for r in item.properties.get("rows", []) if r["id"] != row_id]
    item.properties = {**item.properties, "rows": rows}
    item.content = _flatten_table(item.properties.get("columns", []), rows)
    await db.commit()
    await db.refresh(item)

    out = _serialize(item)
    await _broadcast(table_id, out.model_dump(mode="json"))
    return out


@router.get("/{table_id}/export.csv")
async def export_csv(
    table_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    """Реальный запрос: "смогу ли я потом это скопировать и обработать?" —
    без SQL-движка, пара строк поверх уже имеющихся columns/rows (отдельно
    обсуждали и отказались от идеи SQLite-файла на таблицу — см. историю
    планирования этой фичи)."""
    item = await _get_table_item(db, user, table_id)
    columns = item.properties.get("columns", [])
    rows = item.properties.get("rows", [])

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c["name"] for c in columns])
    for row in rows:
        writer.writerow([row["cells"].get(c["id"], "") for c in columns])

    filename = (item.title or "table").replace('"', "") + ".csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.websocket("/{table_id}/ws")
async def table_ws(websocket: WebSocket, table_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Тот же протокол, что у списков (routers/lists.py::list_ws): клиент
    только слушает, получает TableOut целиком при каждом изменении."""
    await websocket.accept()

    settings = get_settings()
    session_token = websocket.cookies.get(settings.session_cookie_name)
    user_id = decode_session_token(session_token) if session_token else None
    if user_id is None:
        await websocket.close(code=4401)
        return

    item = await db.get(Item, table_id)
    if item is None or item.material_type != "table":
        await websocket.close(code=4404)
        return
    try:
        await ensure_space_access(db, item.space_id, user_id)
    except HTTPException:
        await websocket.close(code=4403)
        return

    _connections[table_id].add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _connections[table_id].discard(websocket)
