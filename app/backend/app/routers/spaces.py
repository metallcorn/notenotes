import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import realtime
from app.core.config import get_settings
from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.models import Item, Notification, Space, SpaceInvite, SpaceMember, Upload, User
from app.routers.uploads import _staged_upload_path, _upload_path
from app.schemas.space import (
    SpaceCreate,
    SpaceInviteOut,
    SpaceMemberAddIn,
    SpaceMemberOut,
    SpaceOut,
    SpaceUpdate,
    VaultRotatePasswordIn,
    VaultUnlockInfoOut,
)
from app.security import decode_session_token

router = APIRouter(prefix="/api/spaces", tags=["spaces"])

# Ссылка-приглашение — тот же принцип живучести, что у InviteCode
# регистрации (routers/auth.py): 7 дней, чтобы забытая в чате ссылка не
# оставалась годной вечно. token_urlsafe даёт непредсказуемый URL-safe
# токен — сам факт владения ссылкой и есть доказательство приглашения,
# перебор 24 случайных байт практически неосуществим.
_SPACE_INVITE_TOKEN_BYTES = 24
_SPACE_INVITE_TTL_DAYS = 7


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


@router.get("/{space_id}/members", response_model=list[SpaceMemberOut])
async def list_space_members(
    space_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[SpaceMemberOut]:
    await ensure_space_access(db, space_id, user.id)
    result = await db.execute(
        select(SpaceMember, User)
        .join(User, User.id == SpaceMember.user_id)
        .where(SpaceMember.space_id == space_id)
        .order_by(SpaceMember.joined_at)
    )
    return [
        SpaceMemberOut(user_id=member_user.id, username=member_user.username, name=member_user.name, joined_at=member.joined_at)
        for member, member_user in result.all()
    ]


@router.post("/{space_id}/members", response_model=SpaceMemberOut, status_code=status.HTTP_201_CREATED)
async def add_space_member(
    space_id: uuid.UUID,
    payload: SpaceMemberAddIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpaceMemberOut:
    """Добавление по нику — без отдельного шага подтверждения (маленький
    круг доверия: сама регистрация уже требует инвайт-код существующего
    пользователя, см. routers/auth.py). Любой участник спейса может звать
    новых — симметрично уже существующей модели равных прав на
    редактирование (ensure_space_access не различает владельца и
    участника нигде в кодовой базе)."""
    await ensure_space_access(db, space_id, user.id)
    username = payload.username.strip().lower()
    target = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь с таким ником не найден")

    existing = (
        await db.execute(
            select(SpaceMember).where(SpaceMember.space_id == space_id, SpaceMember.user_id == target.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Уже участник спейса")

    space = await db.get(Space, space_id)
    member = SpaceMember(space_id=space_id, user_id=target.id)
    db.add(member)
    # type="space_invite" — уже предусмотрено докстрингом модели Notification
    # (models.py) заранее под эту фичу.
    db.add(
        Notification(
            user_id=target.id,
            type="space_invite",
            title="Вас добавили в спейс",
            body=f'{user.name} добавил(а) вас в спейс «{space.name if space else ""}»',
            payload={"space_id": str(space_id)},
        )
    )
    await db.commit()
    await db.refresh(member)
    await realtime.notify_user(target.id)
    return SpaceMemberOut(user_id=target.id, username=target.username, name=target.name, joined_at=member.joined_at)


@router.delete("/{space_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_space_member(
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Без owner-only проверки — owner_id нигде в кодовой базе не участвует
    в авторизации (см. ensure_space_access), не заводим её только здесь.
    Позволяет и выйти самому, и убрать другого участника."""
    await ensure_space_access(db, space_id, user.id)
    member = await db.get(SpaceMember, {"space_id": space_id, "user_id": user_id})
    if member is None:
        return
    await db.delete(member)
    await db.commit()


@router.post("/{space_id}/invites", response_model=SpaceInviteOut, status_code=status.HTTP_201_CREATED)
async def create_space_invite(
    space_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SpaceInvite:
    await ensure_space_access(db, space_id, user.id)
    invite = SpaceInvite(
        space_id=space_id,
        created_by_id=user.id,
        token=secrets.token_urlsafe(_SPACE_INVITE_TOKEN_BYTES),
        expires_at=datetime.now(timezone.utc) + timedelta(days=_SPACE_INVITE_TTL_DAYS),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite


@router.get("/{space_id}/invites", response_model=list[SpaceInviteOut])
async def list_space_invites(
    space_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[SpaceInvite]:
    await ensure_space_access(db, space_id, user.id)
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(SpaceInvite)
        .where(SpaceInvite.space_id == space_id, SpaceInvite.revoked_at.is_(None), SpaceInvite.expires_at > now)
        .order_by(SpaceInvite.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete("/{space_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_space_invite(
    space_id: uuid.UUID,
    invite_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ensure_space_access(db, space_id, user.id)
    invite = await db.get(SpaceInvite, invite_id)
    if invite is None or invite.space_id != space_id:
        return
    invite.revoked_at = datetime.now(timezone.utc)
    await db.commit()


@router.post("/invites/{token}/accept", response_model=SpaceOut)
async def accept_space_invite(
    token: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Space:
    """Идемпотентно — принять уже принятую ссылку просто возвращает тот же
    спейс, не ошибку, чтобы повторный клик/двойная вкладка не пугали
    пользователя сообщением об ошибке на ровном месте."""
    result = await db.execute(select(SpaceInvite).where(SpaceInvite.token == token))
    invite = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if invite is None or invite.revoked_at is not None or invite.expires_at < now:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка недействительна или истекла")

    existing = (
        await db.execute(
            select(SpaceMember).where(SpaceMember.space_id == invite.space_id, SpaceMember.user_id == user.id)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(SpaceMember(space_id=invite.space_id, user_id=user.id))
        await db.commit()

    space = await db.get(Space, invite.space_id)
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Спейс не найден")
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


@router.post("/{space_id}/vault-rotate-password", response_model=SpaceOut)
async def rotate_vault_password(
    space_id: uuid.UUID,
    payload: VaultRotatePasswordIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Space:
    """Смена пароля сейфа. Клиент уже расшифровал всё старым ключом и
    зашифровал новым (сервер ни разу не видел ни одного из ключей) — см.
    VaultRotatePasswordIn и stage_upload_replacement (routers/uploads.py:
    первая фаза, файлы уже лежат перешифрованными во временных .new-копиях).
    Здесь — вторая, коммитящая фаза: ОДНА транзакция сразу на все заметки
    и саму соль/verifier спейса — либо применяется всё разом, либо старый
    пароль остаётся рабочим и ничего не рассогласовано. Физическая подмена
    файлов — только ПОСЛЕ успешного commit."""
    await ensure_space_access(db, space_id, user.id)
    space = await db.get(Space, space_id)
    if space is None or not space.is_vault:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сейф не найден")

    staged_paths: list[tuple[uuid.UUID, Path]] = []
    for upload_id in payload.upload_ids:
        upload = await db.get(Upload, upload_id)
        if upload is None or upload.space_id != space_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Файл {upload_id} не найден в этом сейфе")
        staged = _staged_upload_path(upload_id)
        if not staged.is_file():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Перешифрованная копия файла {upload_id} не найдена — повторите"
            )
        staged_paths.append((upload_id, staged))

    for entry in payload.items:
        item = await db.get(Item, entry.id)
        if item is None or item.space_id != space_id or item.material_type != "note":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Заметка {entry.id} не найдена в этом сейфе")
        item.properties = {**item.properties, "vault": entry.vault}

    space.vault_salt = payload.new_salt
    space.vault_verifier = payload.new_verifier
    await db.commit()

    # Физическая подмена — уже ПОСЛЕ commit: смена пароля к этому моменту
    # уже подтверждена и необратима, сбой здесь (крайне маловероятная
    # локальная ФС-ошибка) не должен откатывать её обратно.
    for upload_id, staged in staged_paths:
        os.replace(staged, _upload_path(upload_id))

    await db.refresh(space)
    await realtime.notify_space(space_id, "items")
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
