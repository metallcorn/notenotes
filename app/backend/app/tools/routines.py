"""Инструменты ассистента для рутин (app/routines.py) — приёмы лекарств
с подтверждением.

Живой случай 28.10: владелец попросил внешнего ассистента (через MCP)
завести рутину по таблеткам кота — тот честно ответил, что у него есть
только напоминания с повтором, и предложил их вместо рутины. Повторяющееся
напоминание — не то: оно не ждёт отметки «дал», не закрывается у всех
участников сразу и не ведёт журнал приёмов. Поэтому рутины — отдельные
инструменты, а в описании create_reminder-подобных сценариев модель
направляется сюда.

Четыре инструмента по образцу напоминаний (tools/reminders.py):
create_routine / list_routines / mark_dose / update_routine. Все
побочные эффекты (пинги участникам, журнал, следующий приём) — в
app/routines.py, здесь только разбор аргументов и ответ модели.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import realtime, routines
from app.deps import ensure_space_access, is_vault_space
from app.llm.base import ToolDefinition
from app.models import Item, Space, SpaceMember, User
from app.routers.items import create_item_row
from app.routine_schedule import STATUS_DONE, STATUS_MISSED, STATUS_PENDING, STATUS_SKIPPED, describe
from app.schemas.routine import RoutineCreate, RoutineUpdate, ScheduleIn
from app.tools.notes import SPACE_PARAM, _resolve_folder, item_url
from app.tools.registry import ToolContext, ToolError
from app.user_timezone import assume_default_timezone, resolve_timezone

# Параметры расписания — общие для create_routine и update_routine. Модели
# проще назвать времена списком и интервал числом, чем собирать вложенный
# объект schedule с полем mode: режим выводится из того, что передано.
_SCHEDULE_PARAMS: dict[str, Any] = {
    "times": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "Режим «по часам»: времена приёмов за день, ЧЧ:ММ в местном времени "
            "(«утром и вечером» → [\"08:00\", \"20:00\"]). Либо times, либо every_minutes"
        ),
    },
    "every_minutes": {
        "type": "integer",
        "description": "Режим «по интервалу»: каждые N минут от РЕАЛЬНОГО предыдущего приёма («раз в сутки» → 1440, «каждые 8 часов» → 480)",
    },
    "min_gap_minutes": {
        "type": "integer",
        "description": "Только для times: минимальный зазор от реального предыдущего приёма, в минутах — если вечернюю дали поздно, утреннюю сдвинет позже",
    },
    "first_at": {
        "type": "string",
        "description": "Только для every_minutes: во сколько первый приём, ЧЧ:ММ; не указать — через пять минут",
    },
}

_COURSE_PARAMS: dict[str, Any] = {
    "starts_on": {"type": "string", "description": "Первый день курса, ГГГГ-ММ-ДД; не указать — с сегодня"},
    "ends_on": {"type": "string", "description": "Последний день курса, ГГГГ-ММ-ДД; не указать — бессрочно"},
    "notify": {
        "type": "string",
        "enum": ["space", "self"],
        "description": "Кого пинговать: space — всех участников спейса (по умолчанию, семья даёт таблетки по очереди), self — только автора",
    },
    "nag_minutes": {
        "type": "integer",
        "description": "Через сколько минут повторять пинг, пока никто не отметил (по умолчанию 30; 0 — напомнить один раз)",
    },
}

CREATE_ROUTINE = ToolDefinition(
    name="create_routine",
    description=(
        "Создать рутину — регулярный приём с подтверждением: таблетки коту или человеку, капли, "
        "уколы, любое «давать N раз в день». В назначенное время всем участникам спейса приходит "
        "пинг с кнопкой «дал»; пока никто не отметил, пинг повторяется; отметка одного закрывает "
        "приём у всех; ведётся журнал приёмов. Это НЕ напоминание: на просьбу напоминать о "
        "лекарствах/приёмах/курсе создавай рутину, а не create_reminder с повтором — напоминание "
        "не ждёт подтверждения и не знает, дали уже или нет. Перед созданием узнай у "
        "пользователя: что и кому (subject, dose), во сколько (times) или как часто "
        "(every_minutes), сколько дней курс (ends_on). Не создавай, пока он не подтвердил. Где: "
        "space — спейс по названию; folder_id — папка (спейс берётся от неё); ничего не указано — "
        "текущий спейс. Одна рутина — одно лекарство или одна связка, которую дают вместе."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Название, как его назовёт человек («Таблетки Барсику», «Капли в глаза»)"},
            "subject": {"type": "string", "description": "Кому: имя кота, ребёнка, «мне» — коротко"},
            "dose": {"type": "string", "description": "Что и сколько: «½ таблетки Amodip 2,5 мг с едой»"},
            **_SCHEDULE_PARAMS,
            **_COURSE_PARAMS,
            "folder_id": {"type": "string", "description": "id папки из list_folders; не указывать — корень спейса"},
            "space": SPACE_PARAM,
        },
        "required": ["title"],
    },
)


def _schedule_from_args(args: dict[str, Any], *, current: dict | None = None) -> ScheduleIn | None:
    """Расписание из плоских аргументов. None — расписание не трогали
    (update_routine без times/every_minutes)."""
    touched = [k for k in ("times", "every_minutes", "min_gap_minutes", "first_at") if args.get(k) not in (None, "", [])]
    if not touched:
        return None
    base = dict(current or {})
    if args.get("times") and args.get("every_minutes"):
        raise ToolError("Либо times (по часам), либо every_minutes (по интервалу) — не оба сразу")
    if args.get("times"):
        times = args["times"]
        if isinstance(times, str):
            times = [t for t in times.replace(";", ",").split(",")]
        base = {"mode": "times", "times": list(times), "min_gap_minutes": base.get("min_gap_minutes", 0)}
    elif args.get("every_minutes"):
        base = {"mode": "interval", "every_minutes": args["every_minutes"], "first_at": base.get("first_at")}
    if args.get("min_gap_minutes") not in (None, ""):
        if base.get("mode", "times") != "times":
            raise ToolError("min_gap_minutes — только для расписания по часам (times)")
        base["min_gap_minutes"] = args["min_gap_minutes"]
    if args.get("first_at"):
        if base.get("mode") != "interval":
            raise ToolError("first_at — только для расписания по интервалу (every_minutes)")
        base["first_at"] = args["first_at"]
    try:
        return ScheduleIn(**base)
    except ValidationError as exc:
        raise ToolError(f"Расписание не принято — {_validation_text(exc)}; поправь и вызови снова") from None


def _validation_text(exc: ValidationError) -> str:
    return "; ".join(e.get("msg", "").replace("Value error, ", "") for e in exc.errors())


def _local(moment_iso: str | None, tz_name: str | None) -> str | None:
    if not moment_iso:
        return None
    moment = datetime.fromisoformat(moment_iso)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(resolve_timezone(tz_name)).isoformat(timespec="minutes")


def _status_word(props: dict) -> str:
    if props.get("paused"):
        return "на паузе"
    if props.get("status") == "finished":
        return "курс закончен"
    return "активна"


def _summary(item: Item, ctx: ToolContext) -> dict[str, Any]:
    """Одна рутина для ответа модели — то же, что видит человек на экране,
    но словами: расписание, следующий приём, кто и когда давал последним."""
    props = item.properties or {}
    tz_name = props.get("timezone") or ctx.client_timezone
    doses = props.get("doses") or []
    pending = routines.pending_dose(props)
    done = [d for d in doses if d.get("status") == STATUS_DONE]
    last = done[-1] if done else None
    try:
        schedule_text = describe(props.get("schedule") or {})
    except ValueError:
        schedule_text = ""
    course = (
        f"с {props.get('starts_on') or '…'}" + (f" по {props['ends_on']}" if props.get("ends_on") else ", бессрочно")
        if props.get("starts_on") or props.get("ends_on")
        else "бессрочно"
    )
    result: dict[str, Any] = {
        "id": str(item.id),
        "title": item.title,
        "subject": props.get("subject") or "",
        "dose": props.get("dose") or "",
        "schedule": schedule_text,
        "course": course,
        "status": _status_word(props),
        "notify": "всем участникам спейса" if (props.get("notify") or "space") == "space" else "только автору",
        "next_at": _local(pending["planned_at"], tz_name) if pending else None,
        "pending_dose_id": pending["id"] if pending else None,
        "stats": {
            "done": len(done),
            "late": sum(1 for d in done if routines.is_late(d)),
            "missed": sum(1 for d in doses if d.get("status") == STATUS_MISSED),
            "skipped": sum(1 for d in doses if d.get("status") == STATUS_SKIPPED),
        },
        "url": item_url(item.id),
    }
    if last:
        result["last_done"] = {"at": _local(last.get("done_at"), tz_name), "by": last.get("done_by_name")}
    if pending and pending.get("deferred_by"):
        result["pending_deferred_by"] = [d.get("name") for d in pending["deferred_by"] if d.get("name")]
    return result


async def create_routine(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    if not title:
        raise ToolError("title обязателен — как человек называет этот приём («Таблетки Барсику»)")
    schedule = _schedule_from_args(args)
    if schedule is None:
        raise ToolError("Нужно расписание: times (например [\"08:00\", \"20:00\"]) или every_minutes (например 1440 — раз в сутки)")
    folder_id, space_id = await _resolve_folder(ctx, args.get("folder_id"), args.get("space"))
    if await is_vault_space(ctx.db, space_id):
        raise ToolError("В сейфе рутины не поддерживаются — выбери обычный спейс")
    user = await ctx.db.get(User, ctx.user_id)
    if user is None:
        raise ToolError("Пользователь не найден — сессия устарела, пусть человек войдёт заново")
    try:
        payload = RoutineCreate(
            space_id=space_id,
            folder_id=folder_id,
            title=title,
            subject=str(args.get("subject") or "").strip(),
            dose=str(args.get("dose") or "").strip(),
            schedule=schedule,
            starts_on=args.get("starts_on") or None,
            ends_on=args.get("ends_on") or None,
            notify=args.get("notify") or "space",
            nag_minutes=args.get("nag_minutes") if args.get("nag_minutes") is not None else routines.DEFAULT_NAG_MINUTES,
            timezone=ctx.client_timezone,
        )
    except ValidationError as exc:
        raise ToolError(f"Параметры не приняты — {_validation_text(exc)}; поправь и вызови снова") from None

    props = {
        "subject": payload.subject,
        "dose": payload.dose,
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
        ctx.db,
        space_id=space_id,
        folder_id=folder_id,
        author_id=ctx.user_id,
        material_type=routines.MATERIAL_TYPE,
        title=payload.title,
        properties=props,
    )
    item.content = routines.flatten(item)
    await routines.ensure_open_dose(ctx.db, item)
    await ctx.db.commit()
    await ctx.db.refresh(item)
    await realtime.notify_space(item.space_id, "items")

    space = await ctx.db.get(Space, item.space_id)
    recipients = await routines.recipients(ctx.db, item)
    result = _summary(item, ctx)
    result["space_name"] = space.name if space else ""
    # Модель должна сказать человеку, кого будут дёргать: «пинг получит и
    # жена» — та же оговорка, что у create_reminder в общем спейсе.
    result["recipients"] = len(recipients)
    if result["next_at"] is None:
        result["warning"] = "Первый приём не запланирован — проверь курс (ends_on уже прошёл?)"
    return result


LIST_ROUTINES = ToolDefinition(
    name="list_routines",
    description=(
        "Рутины пользователя во всех его спейсах — приёмы лекарств с подтверждением: что, кому, "
        "расписание, следующий приём, кто и когда давал последним, сколько пропущено. Вызывай на "
        "«какие таблетки», «дали ли коту», «когда следующий приём», и ПЕРЕД mark_dose/"
        "update_routine, чтобы взять id. Текущие пинги приёмов есть и в list_reminders/"
        "list_agenda, но журнал и расписание — только здесь."
    ),
    parameters={
        "type": "object",
        "properties": {
            "include_finished": {"type": "boolean", "description": "Показать и закончившиеся курсы (по умолчанию нет)"},
        },
        "required": [],
    },
)


async def _user_routines(ctx: ToolContext) -> list[Item]:
    rows = await ctx.db.execute(
        select(Item)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .join(Space, Space.id == Item.space_id)
        .where(
            SpaceMember.user_id == ctx.user_id,
            Space.is_vault.is_(False),
            Item.material_type == routines.MATERIAL_TYPE,
            Item.deleted_at.is_(None),
        )
        .order_by(Item.created_at)
    )
    return list(rows.scalars().all())


async def list_routines(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    include_finished = bool(args.get("include_finished"))
    items = await _user_routines(ctx)
    spaces = {s.id: s.name for s in (await ctx.db.execute(select(Space).where(Space.id.in_({i.space_id for i in items})))).scalars()} if items else {}
    result = []
    for item in items:
        if not include_finished and (item.properties or {}).get("status") == "finished":
            continue
        entry = _summary(item, ctx)
        entry["space_name"] = spaces.get(item.space_id, "")
        result.append(entry)
    return {"routines": result, **({} if result else {"hint": "Рутин нет — предложи создать через create_routine, если человек просит напоминать о лекарствах"})}


async def _get_routine(ctx: ToolContext, raw: Any) -> Item:
    try:
        routine_id = uuid.UUID(str(raw))
    except (ValueError, TypeError):
        raise ToolError(f"Некорректный routine_id: {raw} — нужен UUID из list_routines, а не название") from None
    item = await routines.lock_item(ctx.db, routine_id)
    if item is None or item.deleted_at is not None:
        raise ToolError("Рутина не найдена — вызови list_routines, чтобы увидеть реальные рутины и их id")
    try:
        await ensure_space_access(ctx.db, item.space_id, ctx.user_id)
    except HTTPException:
        raise ToolError("Рутина не найдена — вызови list_routines, чтобы увидеть реальные рутины и их id") from None
    return item


MARK_DOSE = ToolDefinition(
    name="mark_dose",
    description=(
        "Отметить текущий (открытый) приём рутины: done — «дал» (закрывает приём у всех "
        "участников, пинги затихают, заводится следующий по расписанию), skip — пропустить "
        "намеренно. Используй на «дал коту таблетку», «уже выпила», «сегодня вечером "
        "пропускаем». Подтверждения не спрашивай — сама фраза и есть подтверждение. at — если "
        "дали не сейчас («дал полчаса назад»). routine_id — из list_routines."
    ),
    parameters={
        "type": "object",
        "properties": {
            "routine_id": {"type": "string", "description": "id рутины из list_routines"},
            "action": {"type": "string", "enum": ["done", "skip"], "description": "done (по умолчанию) или skip"},
            "at": {
                "type": "string",
                "description": "Когда на самом деле дали, ISO 8601 в местном времени ('2026-10-28T21:40'); не указывать — сейчас",
            },
        },
        "required": ["routine_id"],
    },
)


async def mark_dose(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_routine(ctx, args.get("routine_id"))
    user = await ctx.db.get(User, ctx.user_id)
    pending = routines.pending_dose(item.properties or {})
    if pending is None:
        status = _status_word(item.properties or {})
        raise ToolError(f"У этой рутины сейчас нет открытого приёма (она {status}) — отмечать нечего")
    action = str(args.get("action") or "done").strip().lower()
    at: datetime | None = None
    if args.get("at"):
        try:
            at = assume_default_timezone(datetime.fromisoformat(str(args["at"])), ctx.client_timezone)
        except ValueError:
            raise ToolError(f"Некорректные дата/время: {args['at']} — нужен формат ISO, например 2026-10-28T21:40") from None
    try:
        if action == "done":
            dose = await routines.mark_done(ctx.db, item, pending["id"], user=user, at=at)
        elif action == "skip":
            dose = await routines.skip(ctx.db, item, pending["id"], user=user)
        else:
            raise ToolError("action — done или skip")
    except routines.RoutineError as exc:
        raise ToolError(str(exc)) from None
    await ctx.db.commit()
    await ctx.db.refresh(item)
    tz_name = (item.properties or {}).get("timezone")
    summary = _summary(item, ctx)
    return {
        "id": str(item.id),
        "title": item.title,
        "dose": {
            "planned_at": _local(dose.get("planned_at"), tz_name),
            "status": dose.get("status"),
            **({"done_at": _local(dose.get("done_at"), tz_name), "late": routines.is_late(dose)} if dose.get("status") == STATUS_DONE else {}),
        },
        # Следующий приём — модель должна назвать его человеку: «следующая в 20:00».
        "next_at": summary["next_at"],
        "status": summary["status"],
    }


UPDATE_ROUTINE = ToolDefinition(
    name="update_routine",
    description=(
        "Изменить рутину: поставить на паузу / снять с паузы (paused), закончить курс "
        "(ends_on сегодня), поменять дозу, время, интервал, получателей. Передавай только то, "
        "что меняешь. Смена расписания или курса пересчитывает ближайший приём. routine_id — из "
        "list_routines. Удалить рутину совсем — delete_note по тому же id."
    ),
    parameters={
        "type": "object",
        "properties": {
            "routine_id": {"type": "string", "description": "id рутины из list_routines"},
            "title": {"type": "string"},
            "subject": {"type": "string"},
            "dose": {"type": "string"},
            **_SCHEDULE_PARAMS,
            **_COURSE_PARAMS,
            "paused": {"type": "boolean", "description": "true — пауза (пинги прекращаются), false — продолжить"},
        },
        "required": ["routine_id"],
    },
)


async def update_routine(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_routine(ctx, args.get("routine_id"))
    user = await ctx.db.get(User, ctx.user_id)
    props = item.properties or {}
    fields: dict[str, Any] = {}
    for key in ("title", "subject", "dose", "notify", "nag_minutes", "paused"):
        if key in args and args[key] is not None:
            fields[key] = args[key]
    for key in ("starts_on", "ends_on"):
        if key in args:
            # Пустая строка — снять границу курса («сделай бессрочной»).
            fields[key] = args[key] or None
    schedule = _schedule_from_args(args, current=props.get("schedule"))
    if schedule is not None:
        fields["schedule"] = schedule
    if not fields:
        raise ToolError("Нечего менять — передай хотя бы одно поле (paused, dose, times, ends_on …)")
    try:
        payload = RoutineUpdate(**fields)
    except ValidationError as exc:
        raise ToolError(f"Параметры не приняты — {_validation_text(exc)}; поправь и вызови снова") from None
    try:
        await routines.apply_update(ctx.db, item, payload, user=user)
    except routines.RoutineError as exc:
        raise ToolError(str(exc)) from None
    await ctx.db.commit()
    await ctx.db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    return _summary(item, ctx)


# Две кнопки из веба, которых не хватало инструментам: «отметил по ошибке»
# и «делает не я».

REOPEN_DOSE = ToolDefinition(
    name="reopen_dose",
    description=(
        "Отменить последнюю отметку приёма («я ошибся, не давал») — последний закрытый приём снова "
        "становится открытым, пинги возвращаются участникам. Только последний: более ранние не "
        "трогаются. routine_id — из list_routines."
    ),
    parameters={"type": "object", "properties": {"routine_id": {"type": "string"}}, "required": ["routine_id"]},
)


async def reopen_dose(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from app.routers.routines import dose_reopen

    item = await _get_routine(ctx, args.get("routine_id"))
    user = await ctx.db.get(User, ctx.user_id)
    closed = [d for d in (item.properties or {}).get("doses") or [] if d.get("status") != STATUS_PENDING]
    if not closed:
        raise ToolError("У этой рутины ещё нет закрытых приёмов — отменять нечего, см. list_routines")
    try:
        await dose_reopen(item.id, closed[-1]["id"], user=user, db=ctx.db)
    except HTTPException as exc:
        raise ToolError(f"{exc.detail} — см. list_routines") from None
    await ctx.db.refresh(item)
    summary = _summary(item, ctx)
    return {"id": str(item.id), "title": item.title, "reopened": True, "next_at": summary["next_at"], "status": summary["status"]}


DEFER_DOSE = ToolDefinition(
    name="defer_dose",
    description=(
        "«Делает не я»: приём остаётся открытым для других участников, но пинги ЭТОМУ пользователю "
        "по нему прекращаются. Используй на «это даст жена», «меня не дёргай». Для «дал» — "
        "mark_dose, для «отложи всем на полчаса» — snooze_reminder по пингу из list_reminders."
    ),
    parameters={"type": "object", "properties": {"routine_id": {"type": "string"}}, "required": ["routine_id"]},
)


async def defer_dose(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_routine(ctx, args.get("routine_id"))
    user = await ctx.db.get(User, ctx.user_id)
    pending = routines.pending_dose(item.properties or {})
    if pending is None:
        raise ToolError(f"У этой рутины сейчас нет открытого приёма (она {_status_word(item.properties or {})}) — передавать нечего")
    try:
        await routines.defer(ctx.db, item, pending["id"], user=user)
    except routines.RoutineError as exc:
        raise ToolError(f"{exc} — см. list_routines") from None
    await ctx.db.commit()
    return {"id": str(item.id), "title": item.title, "deferred": True, "planned_at": _local(pending["planned_at"], (item.properties or {}).get("timezone"))}
