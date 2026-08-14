import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import realtime
from app.core.config import get_settings
from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.models import Space, SpaceMember, User
from app.schemas.space import SpaceCreate, SpaceOut, SpaceUpdate, VaultUnlockInfoOut
from app.security import decode_session_token

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
    # Сейф — соль и verifier обязаны идти вместе с is_vault=true, и
    # только тогда; сервер не умеет и не пытается проверить их
    # осмысленность (нет ключа), только форму запроса.
    if payload.is_vault:
        if not payload.vault_salt or not payload.vault_verifier:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для сейфа нужны vault_salt и vault_verifier")
    elif payload.vault_salt or payload.vault_verifier:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "vault_salt/vault_verifier без is_vault не имеют смысла")

    space = Space(
        name=payload.name,
        owner_id=user.id,
        is_vault=payload.is_vault,
        vault_salt=payload.vault_salt,
        vault_verifier=payload.vault_verifier,
    )
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=user.id))
    await db.commit()
    await db.refresh(space)
    return space


@router.get("/{space_id}/vault-unlock-info", response_model=VaultUnlockInfoOut)
async def get_vault_unlock_info(
    space_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Space:
    await ensure_space_access(db, space_id, user.id)
    space = await db.get(Space, space_id)
    if space is None or not space.is_vault:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сейф не найден")
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


@router.websocket("/{space_id}/ws")
async def space_ws(websocket: WebSocket, space_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Клиент ничего не шлёт — только держит соединение и получает лёгкий
    сигнал {"kind": "items"|"folders"|"dialogs"} при изменениях в этом
    спейсе (своих или от других участников/ассистента), чтобы перезапросить
    соответствующие react-query кэши."""
    await websocket.accept()

    settings = get_settings()
    session_token = websocket.cookies.get(settings.session_cookie_name)
    user_id = decode_session_token(session_token) if session_token else None
    if user_id is None:
        await websocket.close(code=4401)
        return

    try:
        await ensure_space_access(db, space_id, user_id)
    except HTTPException:
        await websocket.close(code=4404)
        return

    realtime.register(space_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        realtime.unregister(space_id, websocket)
