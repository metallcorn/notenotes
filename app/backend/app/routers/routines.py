"""Рутины — регулярные приёмы с подтверждением (app/routines.py).

Эндпоинты по образцу списков (routers/lists.py): рутина — item с
material_type="routine", отдельный роутер ради действий с приёмами, у
которых есть побочные эффекты на уведомления всех участников.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import realtime, routines
from app.db import get_db
from app.deps import ensure_space_access, get_current_user, is_vault_space
from app.models import Folder, Item, User
from app.routers.items import create_item_row
from app.routine_schedule import STATUS_DONE, STATUS_MISSED, STATUS_PENDING, STATUS_SKIPPED, describe
from app.schemas.routine import DoseDoneIn, DoseOut, DoseSnoozeIn, RoutineCreate, RoutineOut, RoutineStats, RoutineUpdate
from app.user_timezone import DEFAULT_TZ_NAME

router = APIRouter(prefix="/api/routines", tags=["routines"])


def _serialize(item: Item) -> RoutineOut:
    props = item.properties or {}
    doses = props.get("doses") or []
    schedule = props.get("schedule") or {}
    try:
        schedule_text = describe(schedule)
    except ValueError:
        schedule_text = ""
    pending = routines.pending_dose(props)
    stats = RoutineStats(
        done=sum(1 for d in doses if d.get("status") == STATUS_DONE),
        late=sum(1 for d in doses if d.get("status") == STATUS_DONE and routines.is_late(d)),
        missed=sum(1 for d in doses if d.get("status") == STATUS_MISSED),
        skipped=sum(1 for d in doses if d.get("status") == STATUS_SKIPPED),
    )
    return RoutineOut(
        id=item.id,
        space_id=item.space_id,
        folder_id=item.folder_id,
        author_id=item.author_id,
        title=item.title,
        subject=props.get("subject") or "",
        dose=props.get("dose") or "",
        schedule=schedule,
        schedule_text=schedule_text,
        starts_on=props.get("starts_on"),
        ends_on=props.get("ends_on"),
        notify=props.get("notify") or "space",
        nag_minutes=int(props.get("nag_minutes", routines.DEFAULT_NAG_MINUTES) or 0),
        timezone=props.get("timezone") or DEFAULT_TZ_NAME,
        paused=bool(props.get("paused")),
        status=props.get("status") or "active",
        doses=[DoseOut(**{**d, "late": routines.is_late(d)}) for d in doses],
        next_at=pending["planned_at"] if pending else None,
        stats=stats,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _get_routine(db: AsyncSession, user: User, routine_id: uuid.UUID, *, lock: bool = False) -> Item:
    item = await routines.lock_item(db, routine_id) if lock else await db.get(Item, routine_id)
    if item is None or item.material_type != routines.MATERIAL_TYPE or item.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Рутина не найдена")
    await ensure_space_access(db, item.space_id, user.id)
    return item


@router.post("", response_model=RoutineOut, status_code=status.HTTP_201_CREATED)
async def create_routine(
    payload: RoutineCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RoutineOut:
    await ensure_space_access(db, payload.space_id, user.id)
    if await is_vault_space(db, payload.space_id):
        # Расписание и журнал живут в properties открытым текстом, а
        # пинги уходят в Telegram — в сейфе этому не место.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Рутины в сейфе не поддерживаются")
    if payload.folder_id is not None:
        folder = await db.get(Folder, payload.folder_id)
        if folder is None or folder.space_id != payload.space_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Папка вне этого спейса")

    props = {
        "subject": payload.subject.strip(),
        "dose": payload.dose.strip(),
        "schedule": payload.schedule.model_dump(),
        "starts_on": payload.starts_on.isoformat() if payload.starts_on else None,
        "ends_on": payload.ends_on.isoformat() if payload.ends_on else None,
        "notify": payload.notify,
        "nag_minutes": payload.nag_minutes,
        "timezone": routines.tz_name_for(payload.timezone, user),
        "paused": False,
        "status": "active",
        "doses": [],
    }
    item = await create_item_row(
        db,
        space_id=payload.space_id,
        folder_id=payload.folder_id,
        author_id=user.id,
        material_type=routines.MATERIAL_TYPE,
        title=payload.title.strip() or "Новая рутина",
        properties=props,
    )
    item.content = routines.flatten(item)
    await routines.ensure_open_dose(db, item)
    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    return _serialize(item)


@router.get("/{routine_id}", response_model=RoutineOut)
async def get_routine(
    routine_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RoutineOut:
    return _serialize(await _get_routine(db, user, routine_id))


@router.patch("/{routine_id}", response_model=RoutineOut)
async def update_routine(
    routine_id: uuid.UUID,
    payload: RoutineUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoutineOut:
    item = await _get_routine(db, user, routine_id, lock=True)
    try:
        await routines.apply_update(db, item, payload, user=user)
    except routines.RoutineError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    return _serialize(item)


def _handle(exc: routines.RoutineError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.post("/{routine_id}/doses/{dose_id}/done", response_model=RoutineOut)
async def dose_done(
    routine_id: uuid.UUID,
    dose_id: str,
    payload: DoseDoneIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoutineOut:
    item = await _get_routine(db, user, routine_id, lock=True)
    if payload.by is not None and payload.by != user.id:
        # «Дала Аня» — можно отметить за другого, но только за участника.
        if payload.by not in await routines.recipients(db, item):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Этот человек не участник рутины")
    try:
        await routines.mark_done(db, item, dose_id, user=user, at=payload.at, by=payload.by)
    except routines.RoutineError as exc:
        raise _handle(exc) from None
    await db.commit()
    await db.refresh(item)
    return _serialize(item)


@router.post("/{routine_id}/doses/{dose_id}/skip", response_model=RoutineOut)
async def dose_skip(
    routine_id: uuid.UUID, dose_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RoutineOut:
    item = await _get_routine(db, user, routine_id, lock=True)
    try:
        await routines.skip(db, item, dose_id, user=user)
    except routines.RoutineError as exc:
        raise _handle(exc) from None
    await db.commit()
    await db.refresh(item)
    return _serialize(item)


@router.post("/{routine_id}/doses/{dose_id}/defer", response_model=RoutineOut)
async def dose_defer(
    routine_id: uuid.UUID, dose_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RoutineOut:
    item = await _get_routine(db, user, routine_id, lock=True)
    try:
        await routines.defer(db, item, dose_id, user=user)
    except routines.RoutineError as exc:
        raise _handle(exc) from None
    await db.commit()
    await db.refresh(item)
    return _serialize(item)


@router.post("/{routine_id}/doses/{dose_id}/snooze", response_model=RoutineOut)
async def dose_snooze(
    routine_id: uuid.UUID,
    dose_id: str,
    payload: DoseSnoozeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoutineOut:
    item = await _get_routine(db, user, routine_id, lock=True)
    until = datetime.now(timezone.utc) + timedelta(minutes=payload.minutes)
    try:
        await routines.snooze(db, item, dose_id, user=user, until=until)
    except routines.RoutineError as exc:
        raise _handle(exc) from None
    await db.commit()
    await db.refresh(item)
    return _serialize(item)


@router.post("/{routine_id}/doses/{dose_id}/reopen", response_model=RoutineOut)
async def dose_reopen(
    routine_id: uuid.UUID, dose_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RoutineOut:
    """Отметили по ошибке: вернуть последний закрытый приём в открытые.
    Только последний — иначе открытых стало бы два."""
    item = await _get_routine(db, user, routine_id, lock=True)
    props = routines.props_of(item)
    doses = list(props.get("doses") or [])
    closed = [d for d in doses if d.get("status") != STATUS_PENDING]
    if not closed or closed[-1].get("id") != dose_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Вернуть можно только последний закрытый приём")
    # Открытый (следующий) приём закрываем без следа, ошибочно закрытый —
    # выбрасываем из журнала: ensure_open_dose заведёт его заново по
    # расписанию, вместе с пингами участникам.
    await routines.close_open(db, item, user_id=user.id)
    props = routines.props_of(item)
    props["doses"] = [d for d in props.get("doses") or [] if d.get("id") != dose_id]
    routines.set_props(item, props)
    reopened = await routines.ensure_open_dose(db, item)
    if reopened is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Курс закончен")
    await db.commit()
    await db.refresh(item)
    return _serialize(item)
