import uuid

import y_py as Y
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app import collab
from app.core.config import get_settings
from app.db import get_db
from app.deps import ensure_space_access, is_vault_space
from app.models import Item
from app.security import decode_session_token

router = APIRouter(prefix="/api/items", tags=["collab"])


@router.websocket("/{item_id}/collab")
async def item_collab_ws(websocket: WebSocket, item_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Реле совместного редактирования одной заметки (app/collab.py) — тот
    же авторизационный паттерн, что space_ws (routers/spaces.py): ручной
    разбор cookie-сессии, ensure_space_access. Вложение — только
    ЗАПРЕЩЕНО для сейфа: сервер держит plaintext Yjs-состояние комнаты, а
    для E2E-заметок это принципиально недопустимо (deps.is_vault_space)."""
    await websocket.accept()

    settings = get_settings()
    session_token = websocket.cookies.get(settings.session_cookie_name)
    user_id = decode_session_token(session_token) if session_token else None
    if user_id is None:
        await websocket.close(code=4401)
        return

    item = await db.get(Item, item_id)
    if item is None:
        await websocket.close(code=4404)
        return
    try:
        await ensure_space_access(db, item.space_id, user_id)
    except HTTPException:
        await websocket.close(code=4404)
        return
    if await is_vault_space(db, item.space_id):
        await websocket.close(code=4400)
        return

    room, is_seeder = await collab.join_room(item_id, websocket)
    try:
        if is_seeder:
            await websocket.send_bytes(bytes([collab.MSG_SEED_REQUEST]))
        else:
            await collab.wait_for_seed(room)
            update = Y.encode_state_as_update(room.doc)
            if update:
                await websocket.send_bytes(bytes([collab.MSG_UPDATE]) + update)

        while True:
            data = await websocket.receive_bytes()
            await collab.handle_message(room, websocket, data)
    except WebSocketDisconnect:
        pass
    finally:
        await collab.leave_room(item_id, room, websocket)
