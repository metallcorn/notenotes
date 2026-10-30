"""Рутины: регулярные приёмы с подтверждением — таблетки коту и себе.

Запрос владельца 26.10: напоминать о каждом приёме, пока кто-то не
подтвердит; в Telegram на приём — одно живое сообщение, а не пачка;
отметка одного участника семьи закрывает приём у всех; «делает не я» —
приём не закрыт, но меня больше не дёргают; интервал «раз в сутки»
считается от реального приёма.

КАК ЭТО ЛЕЖИТ В БАЗЕ. Рутина — обычный item с material_type="routine"
(как билет или список), расписание и журнал приёмов — в properties:

    subject, dose              для кого и что («Барсик», «½ таблетки»)
    schedule                   см. routine_schedule.py
    starts_on, ends_on         курс; ends_on пустой — бессрочно
    notify                     "space" — всем участникам, "self" — только автору
    nag_minutes                повтор пинга, 0 — один раз
    timezone                   пояс расписания
    doses                      журнал: [{id, planned_at, status, done_at,
                               done_by, done_by_name, deferred_by,
                               snoozed_until, nag_until}]

В любой момент у рутины НЕ БОЛЬШЕ ОДНОГО открытого (pending) приёма —
следующий заводится, когда этот закрыт (дали, пропустили, истёк). Это
делает ensure_open_dose, вызываемая из тика (tick) и после каждой отметки.

Пинг приёма — обычный Notification (type="routine_dose"), по одному на
получателя, как у напоминаний в общей заметке. Повтор — не новая строка,
а та же, взведённая заново (after_dispatch): так в «Активности» и в
колокольчике приём остаётся одной записью, сколько бы раз ни напоминал.
Сообщение Telegram на каждом повторе удаляется и шлётся заново: в чате
одно, но оно звенит.

СОСТОЯНИЕ ПРИЁМА — ОБЩЕЕ и живёт в item, а не в уведомлениях: «дал» одного
закрывает Notification у всех участников (у обычных напоминаний закрытие
по-пользовательское — там это осознанно, здесь было бы ошибкой: кот не
должен получить таблетку дважды).
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app import realtime
from app.core.config import get_settings
from app.deps import space_member_ids
from app.models import Item, ItemVersion, Notification, TelegramLink, User
from app.schemas.routine import RoutineUpdate
from app.routine_schedule import (
    STATUS_DONE,
    STATUS_MISSED,
    STATUS_PENDING,
    STATUS_SKIPPED,
    describe,
    nag_until,
    next_planned,
)
from app.user_timezone import DEFAULT_TZ_NAME, resolve_timezone

logger = logging.getLogger(__name__)

MATERIAL_TYPE = "routine"
NOTIFICATION_TYPE = "routine_dose"
# Префикс callback_data кнопок под пингом. «nt:» — напоминания, «dg:» —
# сводка, «sr:» — варианты ответа ассистента; пересекаться нельзя.
CALLBACK_PREFIX = "rt:"
SNOOZE_MINUTES = (30, 60)
DEFAULT_NAG_MINUTES = 30
# Сколько приёмов держать в журнале. 400 — больше полугода по два в день;
# старое уезжает, но остаётся в истории версий.
MAX_LOG = 400
# Опоздание меньше этого — «вовремя»: пятнадцать минут на поймать кота.
LATE_AFTER = timedelta(minutes=15)


class RoutineError(Exception):
    """Ошибка действия с приёмом — текст для человека."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).isoformat() if moment else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def tz_of(item: Item) -> ZoneInfo:
    return resolve_timezone((item.properties or {}).get("timezone"))


def pending_dose(props: dict) -> dict | None:
    for dose in props.get("doses") or []:
        if dose.get("status") == STATUS_PENDING:
            return dose
    return None


def find_dose(props: dict, dose_id: str) -> dict | None:
    for dose in props.get("doses") or []:
        if dose.get("id") == dose_id:
            return dose
    return None


def dose_text(item: Item) -> str:
    props = item.properties or {}
    parts = [p for p in (props.get("subject"), props.get("dose")) if p]
    return " · ".join(parts)


def is_late(dose: dict) -> bool:
    done_at, planned_at = _dt(dose.get("done_at")), _dt(dose.get("planned_at"))
    return bool(done_at and planned_at and done_at - planned_at > LATE_AFTER)


def flatten(item: Item) -> str:
    """Плоский текст для поиска и истории версий — как у списков."""
    props = item.properties or {}
    tz = tz_of(item)
    lines = []
    if dose_text(item):
        lines.append(dose_text(item))
    try:
        lines.append(f"Расписание: {describe(props.get('schedule') or {})}")
    except ValueError:
        pass
    if props.get("starts_on") or props.get("ends_on"):
        span = f"с {props.get('starts_on') or '…'}" + (f" по {props['ends_on']}" if props.get("ends_on") else ", бессрочно")
        lines.append(f"Курс: {span}")
    doses = [d for d in props.get("doses") or [] if d.get("status") != STATUS_PENDING]
    if doses:
        lines.append("")
        lines.append("Журнал:")
        for dose in doses[-60:]:
            planned = _dt(dose["planned_at"]).astimezone(tz)
            if dose["status"] == STATUS_DONE:
                done = _dt(dose["done_at"]).astimezone(tz)
                late = " (с опозданием)" if is_late(dose) else ""
                lines.append(f"- {planned:%d.%m %H:%M}: дали в {done:%H:%M}, {dose.get('done_by_name') or '—'}{late}")
            elif dose["status"] == STATUS_SKIPPED:
                lines.append(f"- {planned:%d.%m %H:%M}: пропущено намеренно")
            else:
                lines.append(f"- {planned:%d.%m %H:%M}: никто не отметил")
    return "\n".join(lines)


def props_of(item: Item) -> dict:
    """ГЛУБОКАЯ копия properties для изменения.

    Реальный найденный баг: shallow-копия делила вложенные словари приёмов
    со старым значением, SQLAlchemy сравнивал старое и новое через ==,
    находил их равными и не писал UPDATE — отметка «дал» жила только в
    памяти процесса до первого refresh.
    """
    return copy.deepcopy(item.properties or {})


def set_props(item: Item, props: dict) -> None:
    item.properties = props
    flag_modified(item, "properties")
    item.content = flatten(item)


def _snapshot(db: AsyncSession, item: Item, user_id: uuid.UUID | None) -> None:
    """Снимок ДО изменения — тот же приём, что у списков."""
    db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=user_id))


async def recipients(db: AsyncSession, item: Item) -> list[uuid.UUID]:
    props = item.properties or {}
    if props.get("notify") == "self":
        return [item.author_id]
    ids = await space_member_ids(db, item.space_id)
    if item.author_id not in ids:
        ids.append(item.author_id)
    return ids


async def lock_item(db: AsyncSession, item_id: uuid.UUID) -> Item | None:
    """Строка item под блокировкой: два «дал» с двух телефонов в одну
    секунду не должны закрыть один приём дважды."""
    return (
        await db.execute(select(Item).where(Item.id == item_id, Item.material_type == MATERIAL_TYPE).with_for_update())
    ).scalar_one_or_none()


def tz_name_for(value: str | None, user: User) -> str:
    """Пояс расписания: явный, иначе домашний пояс автора, иначе дефолт.
    resolve_timezone молча откатывается на дефолт при кривом имени —
    сохраняем то, что реально будет использоваться."""
    candidate = value or user.timezone or DEFAULT_TZ_NAME
    return str(resolve_timezone(candidate).key)


async def apply_update(db: AsyncSession, item: Item, payload: RoutineUpdate, *, user: User) -> None:
    """Правка рутины — общая для REST (routers/routines.py) и инструмента
    ассистента (tools/routines.py). Поля применяются, только если явно
    переданы (как ItemUpdate). Смена расписания, курса, пояса, получателей
    или паузы пересчитывает открытый приём: он считался по старым
    правилам — закрываем без следа и заводим заново."""
    fields = payload.model_fields_set
    props = props_of(item)
    reschedule = False
    if "title" in fields and payload.title is not None:
        item.title = payload.title.strip() or item.title
    for key in ("subject", "dose", "notify", "nag_minutes", "timezone"):
        if key in fields and getattr(payload, key) is not None:
            value = getattr(payload, key)
            props[key] = tz_name_for(value, user) if key == "timezone" else (value.strip() if isinstance(value, str) else value)
            reschedule = reschedule or key in ("timezone", "notify")
    if "schedule" in fields and payload.schedule is not None:
        props["schedule"] = payload.schedule.model_dump()
        reschedule = True
    for key in ("starts_on", "ends_on"):
        if key in fields:
            value = getattr(payload, key)
            props[key] = value.isoformat() if value else None
            reschedule = True
    if props.get("starts_on") and props.get("ends_on") and props["ends_on"] < props["starts_on"]:
        raise RoutineError("Конец курса раньше начала")
    if "paused" in fields and payload.paused is not None:
        props["paused"] = payload.paused
        reschedule = True
    set_props(item, props)
    if reschedule:
        await close_open(db, item, user_id=user.id)
        props = props_of(item)
        props["status"] = "active"
        set_props(item, props)
        await ensure_open_dose(db, item)


# --- жизненный цикл приёма -----------------------------------------------


async def ensure_open_dose(db: AsyncSession, item: Item, now: datetime | None = None) -> dict | None:
    """Завести следующий приём, если открытого нет. Возвращает открытый."""
    now = now or _now()
    props = props_of(item)
    if item.deleted_at is not None or props.get("paused"):
        return None
    current = pending_dose(props)
    if current is not None:
        return current
    doses = list(props.get("doses") or [])
    previous = doses[-1] if doses else None
    schedule = props.get("schedule") or {}
    tz = tz_of(item)
    try:
        planned = next_planned(
            schedule, tz=tz, now=now, previous=previous,
            starts_on=_date(props.get("starts_on")), ends_on=_date(props.get("ends_on")),
        )
    except ValueError:
        logger.warning("Рутина %s: негодное расписание %r", item.id, schedule)
        return None
    if planned is None:
        if props.get("status") != "finished":
            props["status"] = "finished"
            set_props(item, props)
        return None
    until = nag_until(schedule, planned, tz=tz)
    dose = {
        "id": uuid.uuid4().hex,
        "planned_at": _iso(planned),
        "status": STATUS_PENDING,
        "done_at": None,
        "done_by": None,
        "done_by_name": None,
        "deferred_by": [],
        "snoozed_until": None,
        "nag_until": _iso(until),
    }
    doses.append(dose)
    props["doses"] = doses[-MAX_LOG:]
    props["status"] = "active"
    set_props(item, props)

    nag_minutes = int(props.get("nag_minutes", DEFAULT_NAG_MINUTES) or 0)
    for user_id in await recipients(db, item):
        db.add(
            Notification(
                user_id=user_id,
                type=NOTIFICATION_TYPE,
                title=item.title,
                body=dose_text(item),
                payload={
                    "item_id": str(item.id),
                    "space_id": str(item.space_id),
                    "material_type": MATERIAL_TYPE,
                    "dose_id": dose["id"],
                    "nag_until": _iso(until),
                    "nag_minutes": nag_minutes,
                    "nag_count": 0,
                },
                trigger_at=planned,
            )
        )
    return dose


async def _dose_notifications(db: AsyncSession, item: Item, dose_id: str) -> list[Notification]:
    rows = await db.execute(
        select(Notification).where(
            Notification.type == NOTIFICATION_TYPE,
            Notification.payload["item_id"].astext == str(item.id),
            Notification.payload["dose_id"].astext == dose_id,
        )
    )
    return list(rows.scalars().all())


async def _links_for(db: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not user_ids:
        return {}
    rows = await db.execute(select(TelegramLink).where(TelegramLink.user_id.in_(user_ids)))
    return {link.user_id: link.chat_id for link in rows.scalars().all()}


def _open_rows(item: Item) -> list[list[dict]]:
    # telegram_bot импортируется лениво: он сам импортирует routines ради
    # кнопок (и через routers.items — полдюжины модулей), импорт при
    # загрузке замкнулся бы в цикл.
    from app import telegram_bot

    base_url = get_settings().public_base_url.rstrip("/")
    return [[telegram_bot.open_button("Открыть", f"{base_url}/?item={item.id}")]]


async def _finalize_notifications(db: AsyncSession, item: Item, dose: dict, line: str, *, now: datetime) -> None:
    """Закрыть пинги приёма у всех и убрать их сообщения из Telegram.

    Раньше сообщение перерисовывалось в итог («✓ Дмитрий — в 22:09») и
    оставалось в чате навсегда. Жалоба владельца 30.10: при шести приёмах
    в день чат с ботом через неделю — сплошная лента закрытых пингов, и
    полезное среди них не найти. Теперь закрытый пинг удаляется, а итог
    попадает в одну сводку за день (day_summary), которая у каждого
    получателя перерисовывается на месте. line остаётся в сигнатуре для
    журнала/логов — в чате она больше не показывается.
    """
    from app import telegram_bot

    notifications = await _dose_notifications(db, item, dose["id"])
    links = await _links_for(db, [n.user_id for n in notifications])
    touched: set[uuid.UUID] = set()
    for n in notifications:
        if n.resolved_at is None:
            n.resolved_at = now
        n.dispatched_at = n.dispatched_at or now
        message_id = (n.payload or {}).get("telegram_message_id")
        chat_id = links.get(n.user_id)
        if message_id and chat_id:
            await telegram_bot.delete_message(chat_id, message_id)
            n.payload = {k: v for k, v in (n.payload or {}).items() if k != "telegram_message_id"}
        if chat_id:
            touched.add(n.user_id)
        await realtime.notify_user(n.user_id)
    for user_id in touched:
        await refresh_day_summary(db, user_id, now=now)
    await realtime.notify_space(item.space_id, "items")


# --- дневная сводка в Telegram ---------------------------------------------
#
# Одно сообщение на день у каждого получателя: «💊 Приёмы 30.10 · 4 из 6» и
# строка на каждый приём этого дня — дали (во сколько, кто), пропущен, ждёт,
# ещё впереди. Перерисовывается при каждой отметке. Переотправляется, а не
# редактируется: так сводка всегда последняя в чате, под пингами, которые
# к тому моменту уже удалены. Без звука — звенят только пинги.

_SUMMARY_ICON = {STATUS_DONE: "✓", STATUS_SKIPPED: "⏭", STATUS_MISSED: "✗"}


async def _user_routines(db: AsyncSession, user_id: uuid.UUID) -> list[Item]:
    from app.models import SpaceMember

    rows = await db.execute(
        select(Item)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .where(SpaceMember.user_id == user_id, Item.material_type == MATERIAL_TYPE, Item.deleted_at.is_(None))
    )
    return [i for i in rows.scalars().all() if (i.properties or {}).get("notify") != "self" or i.author_id == user_id]


def day_summary_text(items: list[Item], *, day: date, tz: ZoneInfo, now: datetime) -> str | None:
    """Текст сводки за местный день day. None — приёмов в этот день нет."""
    rows: list[tuple[datetime, str]] = []
    done = total = 0
    for item in items:
        for dose in (item.properties or {}).get("doses") or []:
            planned = _dt(dose["planned_at"])
            if planned is None:
                continue
            # День приёма — по факту, если дали (вечером дали «завтрашнюю
            # утреннюю» заранее — это сегодняшнее событие), иначе по плану.
            done_at = _dt(dose.get("done_at")) if dose.get("status") == STATUS_DONE else None
            if (done_at or planned).astimezone(tz).date() != day:
                continue
            total += 1
            local = planned.astimezone(tz)
            status = dose.get("status")
            if status == STATUS_DONE:
                done += 1
                at = _dt(dose.get("done_at"))
                who = dose.get("done_by_name") or ""
                late = ", с опозданием" if is_late(dose) else ""
                detail = f" · {at.astimezone(tz):%H:%M} {who}{late}".rstrip() if at else ""
                line = f"✓ {local:%H:%M} {item.title}{detail}"
            elif status == STATUS_SKIPPED:
                line = f"⏭ {local:%H:%M} {item.title} · пропущен"
            elif status == STATUS_MISSED:
                line = f"✗ {local:%H:%M} {item.title} · никто не отметил"
            elif planned <= now:
                line = f"⏳ {local:%H:%M} {item.title} · ждёт {_humanize(now - planned)}"
            else:
                line = f"· {local:%H:%M} {item.title}"
            rows.append((planned, line))
    if not rows:
        return None
    rows.sort(key=lambda r: r[0])
    header = f"💊 Приёмы {day:%d.%m} · {done} из {total}"
    return "\n".join([header, *[line for _, line in rows]])


async def refresh_day_summary(db: AsyncSession, user_id: uuid.UUID, *, now: datetime, only_if_missing: bool = False) -> None:
    """Перерисовать сводку сегодняшнего дня у пользователя в Telegram.

    only_if_missing — завести сводку, если её за сегодня ещё нет, и ничего
    не трогать, если есть (первый пинг дня показывает план на день, а
    повторные пинги каждые полчаса сводку не дёргают).
    """
    from app import telegram_bot

    link = (await db.execute(select(TelegramLink).where(TelegramLink.user_id == user_id))).scalar_one_or_none()
    if link is None:
        return
    user = await db.get(User, user_id)
    tz = resolve_timezone(user.timezone if user else None)
    day = now.astimezone(tz).date()
    current = dict(link.routine_summary or {})
    if only_if_missing and current.get("date") == day.isoformat() and current.get("message_id"):
        return
    text = day_summary_text(await _user_routines(db, user_id), day=day, tz=tz, now=now)
    if text is None:
        return
    if current.get("date") == day.isoformat() and current.get("message_id"):
        await telegram_bot.delete_message(link.chat_id, int(current["message_id"]))
    message_id = await telegram_bot.send_message(link.chat_id, text, silent=True)
    link.routine_summary = {"date": day.isoformat(), "message_id": message_id} if message_id else None
    flag_modified(link, "routine_summary")


def base_text(item: Item, dose: dict) -> str:
    planned = _dt(dose["planned_at"]).astimezone(tz_of(item))
    lines = [f"💊 {item.title} · {planned:%H:%M}"]
    if dose_text(item):
        lines.append(dose_text(item))
    return "\n".join(lines)


def _close(dose: dict, status: str) -> None:
    dose["status"] = status


async def _user_name(db: AsyncSession, user_id: uuid.UUID) -> str:
    user = await db.get(User, user_id)
    return (user.name or user.username) if user else "кто-то"


async def mark_done(
    db: AsyncSession, item: Item, dose_id: str, *, user: User, at: datetime | None = None, by: uuid.UUID | None = None,
) -> dict:
    """«Дал». at — когда на самом деле (по умолчанию сейчас), by — кто
    (по умолчанию нажавший). Закрывает приём у всех и заводит следующий."""
    now = _now()
    props = props_of(item)
    dose = find_dose(props, dose_id)
    if dose is None:
        raise RoutineError("Приём не найден")
    if dose["status"] != STATUS_PENDING:
        raise RoutineError("Этот приём уже закрыт")
    at = (at or now).astimezone(timezone.utc)
    if at > now + timedelta(minutes=5):
        raise RoutineError("Время приёма не может быть в будущем")
    by = by or user.id
    _snapshot(db, item, user.id)
    _close(dose, STATUS_DONE)
    dose["done_at"] = _iso(at)
    dose["done_by"] = str(by)
    dose["done_by_name"] = await _user_name(db, by)
    set_props(item, props)
    local = at.astimezone(tz_of(item))
    await _finalize_notifications(db, item, dose, f"✓ {dose['done_by_name']} — в {local:%H:%M}", now=now)
    await ensure_open_dose(db, item, now)
    return dose


async def skip(db: AsyncSession, item: Item, dose_id: str, *, user: User) -> dict:
    now = _now()
    props = props_of(item)
    dose = find_dose(props, dose_id)
    if dose is None or dose["status"] != STATUS_PENDING:
        raise RoutineError("Этот приём уже закрыт")
    _snapshot(db, item, user.id)
    _close(dose, STATUS_SKIPPED)
    set_props(item, props)
    name = await _user_name(db, user.id)
    await _finalize_notifications(db, item, dose, f"⏭ Пропущен — {name}", now=now)
    await ensure_open_dose(db, item, now)
    return dose


async def defer(db: AsyncSession, item: Item, dose_id: str, *, user: User) -> dict:
    """«Делает не я»: приём остаётся открытым, но МОЙ пинг затихает."""
    now = _now()
    props = props_of(item)
    dose = find_dose(props, dose_id)
    if dose is None or dose["status"] != STATUS_PENDING:
        raise RoutineError("Этот приём уже закрыт")
    name = await _user_name(db, user.id)
    deferred = [d for d in dose.get("deferred_by") or [] if d.get("id") != str(user.id)]
    deferred.append({"id": str(user.id), "name": name})
    dose["deferred_by"] = deferred
    set_props(item, props)
    for n in await _dose_notifications(db, item, dose_id):
        if n.user_id == user.id:
            n.resolved_at = n.resolved_at or now
            n.dispatched_at = n.dispatched_at or now
            n.payload = {**(n.payload or {}), "deferred": True}
        await realtime.notify_user(n.user_id)
    await realtime.notify_space(item.space_id, "items")
    return dose


async def snooze(db: AsyncSession, item: Item, dose_id: str, *, user: User, until: datetime) -> dict:
    """«+30 мин»: общее для всех — пинг замолкает у всех до until."""
    now = _now()
    until = until.astimezone(timezone.utc)
    if until <= now:
        raise RoutineError("Отложить можно только на будущее")
    props = props_of(item)
    dose = find_dose(props, dose_id)
    if dose is None or dose["status"] != STATUS_PENDING:
        raise RoutineError("Этот приём уже закрыт")
    dose["snoozed_until"] = _iso(until)
    # Окно напоминаний продлеваем, иначе отложенный на час приём мог бы
    # истечь раньше, чем о нём напомнят снова.
    current_until = _dt(dose.get("nag_until")) or until
    dose["nag_until"] = _iso(max(current_until, until + timedelta(hours=1)))
    set_props(item, props)
    from app import telegram_bot

    name = await _user_name(db, user.id)
    local = until.astimezone(tz_of(item))
    notifications = await _dose_notifications(db, item, dose_id)
    links = await _links_for(db, [n.user_id for n in notifications])
    for n in notifications:
        if n.resolved_at is not None:
            continue
        n.trigger_at = until
        n.dispatched_at = None
        n.read_at = None
        n.payload = {**(n.payload or {}), "nag_until": dose["nag_until"]}
        message_id = (n.payload or {}).get("telegram_message_id")
        chat_id = links.get(n.user_id)
        if message_id and chat_id:
            await telegram_bot.edit_message(
                chat_id, message_id, f"{base_text(item, dose)}\n\n⏰ {name}: отложено до {local:%H:%M}",
                {"inline_keyboard": _open_rows(item)},
            )
        await realtime.notify_user(n.user_id)
    await realtime.notify_space(item.space_id, "items")
    return dose


async def close_open(db: AsyncSession, item: Item, *, user_id: uuid.UUID | None = None) -> None:
    """Закрыть открытый приём без следа «пропущено»: рутину удалили,
    поставили на паузу или поменяли расписание."""
    now = _now()
    props = props_of(item)
    dose = pending_dose(props)
    if dose is None:
        return
    _snapshot(db, item, user_id)
    doses = [d for d in props.get("doses") or [] if d.get("id") != dose["id"]]
    props["doses"] = doses
    set_props(item, props)
    for n in await _dose_notifications(db, item, dose["id"]):
        n.resolved_at = n.resolved_at or now
        n.dispatched_at = n.dispatched_at or now
        await realtime.notify_user(n.user_id)
    await realtime.notify_space(item.space_id, "items")


async def tick(db: AsyncSession, now: datetime | None = None) -> None:
    """Проход диспетчера: истёкшие приёмы — в «пропущено», следующие — завести."""
    now = now or _now()
    items = (
        await db.execute(select(Item).where(Item.material_type == MATERIAL_TYPE, Item.deleted_at.is_(None)))
    ).scalars().all()
    for item in items:
        props = props_of(item)
        if props.get("paused"):
            continue
        dose = pending_dose(props)
        if dose is not None:
            until = _dt(dose.get("nag_until"))
            if until is not None and until <= now:
                _close(dose, STATUS_MISSED)
                set_props(item, props)
                await _finalize_notifications(db, item, dose, "⏭ Никто не отметил — пропущен", now=now)
                dose = None
        if dose is None:
            await ensure_open_dose(db, item, now)


# --- доставка и кнопки ---------------------------------------------------


def _humanize(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} мин"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч {minutes:02d} мин" if minutes else f"{hours} ч"


def ping_text(item: Item, dose: dict, notification: Notification, now: datetime) -> str:
    """Текст пинга: что, во сколько, сколько ждёт, кто передал другим."""
    lines = [base_text(item, dose)]
    planned = _dt(dose["planned_at"])
    waited = now - planned
    count = int((notification.payload or {}).get("nag_count", 0)) + 1
    if waited > timedelta(minutes=2):
        suffix = f" · напоминаю {count}-й раз" if count > 1 else ""
        lines.append(f"Ждёт {_humanize(waited)}{suffix}")
    deferred = [d.get("name") for d in dose.get("deferred_by") or [] if d.get("id") != str(notification.user_id)]
    if deferred:
        lines.append("Делает не я: " + ", ".join(n for n in deferred if n))
    return "\n".join(lines)


def ping_keyboard(item: Item, notification: Notification) -> list[list[dict]]:
    nid = notification.id
    return [
        [
            {"text": "✓ Дал", "callback_data": f"{CALLBACK_PREFIX}d:{nid}"},
            {"text": "Делает не я", "callback_data": f"{CALLBACK_PREFIX}n:{nid}"},
        ],
        [
            {"text": "⏰ +30 мин", "callback_data": f"{CALLBACK_PREFIX}s:30:{nid}"},
            {"text": "⏰ +1 ч", "callback_data": f"{CALLBACK_PREFIX}s:60:{nid}"},
        ],
        [{"text": "Пропустить", "callback_data": f"{CALLBACK_PREFIX}k:{nid}"}, *_open_rows(item)[0]],
    ]


async def deliver(db: AsyncSession, notification: Notification, chat_id: int | None, now: datetime) -> tuple[str, str] | None:
    """Отправить пинг в Telegram (если привязан) и вернуть (title, body)
    для push и колокольчика. None — приём уже закрыт, слать нечего."""
    from app import telegram_bot

    payload = dict(notification.payload or {})
    item = await db.get(Item, uuid.UUID(payload["item_id"]))
    if item is None or item.deleted_at is not None:
        return None
    dose = find_dose(item.properties or {}, payload.get("dose_id", ""))
    if dose is None or dose["status"] != STATUS_PENDING:
        return None
    text = ping_text(item, dose, notification, now)
    if chat_id is not None:
        previous = payload.get("telegram_message_id")
        if previous:
            # Одно живое сообщение на приём: старое убираем, новое звенит.
            await telegram_bot.delete_message(chat_id, previous)
        message_id = await telegram_bot.send_message(chat_id, text, reply_markup={"inline_keyboard": ping_keyboard(item, notification)})
        payload["telegram_message_id"] = message_id
        # Первый пинг дня заводит сводку с планом на день; повторные
        # пинги её не трогают — перерисовка только по отметкам.
        await refresh_day_summary(db, notification.user_id, now=now, only_if_missing=True)
    payload["nag_count"] = int(payload.get("nag_count", 0)) + 1
    notification.payload = payload
    body = text.split("\n", 1)[1] if "\n" in text else ""
    return notification.title, body


def after_dispatch(notification: Notification, now: datetime) -> None:
    """Взвести повтор: та же строка сработает снова через nag_minutes,
    пока не истекло окно приёма."""
    payload = notification.payload or {}
    nag = int(payload.get("nag_minutes") or 0)
    until = _dt(payload.get("nag_until"))
    if nag <= 0 or until is None:
        return
    again = now + timedelta(minutes=nag)
    if again >= until:
        return
    notification.trigger_at = again
    notification.dispatched_at = None


async def handle_callback(db: AsyncSession, user_id: uuid.UUID, data: str) -> tuple[str, list[list[dict]]] | None:
    """Кнопка под пингом. Возвращает (текст, клавиатура), которыми
    перерисовать ЭТО сообщение, или None — данные не наши ЛИБО сообщение
    уже удалено («дал»/«пропустить»: итог уходит в дневную сводку)."""
    if not data.startswith(CALLBACK_PREFIX):
        return None
    parts = data[len(CALLBACK_PREFIX):].split(":")
    try:
        notification_id = uuid.UUID(parts[-1])
    except ValueError:
        return None
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user_id or n.type != NOTIFICATION_TYPE:
        return "Приём не найден", []
    user = await db.get(User, user_id)
    payload = n.payload or {}
    item = await lock_item(db, uuid.UUID(payload["item_id"]))
    if item is None or item.deleted_at is not None:
        return "Рутина удалена", []
    dose = find_dose(item.properties or {}, payload.get("dose_id", ""))
    if dose is None:
        return "Приём не найден", []
    tz = tz_of(item)
    open_rows = _open_rows(item)
    if dose["status"] != STATUS_PENDING:
        return f"{base_text(item, dose)}\n\n{_final_line(dose, tz)}", open_rows

    action = parts[0]
    try:
        if action == "d" and len(parts) == 2:
            # Сообщение пинга уже удалено внутри mark_done, итог — в
            # дневной сводке; перерисовывать нечего.
            await mark_done(db, item, dose["id"], user=user)
            await db.commit()
            return None
        if action == "k" and len(parts) == 2:
            await skip(db, item, dose["id"], user=user)
            await db.commit()
            return None
        if action == "n" and len(parts) == 2:
            await defer(db, item, dose["id"], user=user)
            await db.commit()
            return (
                f"{base_text(item, dose)}\n\nЖдём отметку от других. Тебя больше не дёргаю.",
                [[{"text": "✓ Всё-таки дал я", "callback_data": f"{CALLBACK_PREFIX}d:{n.id}"}], *open_rows],
            )
        if action == "s" and len(parts) == 3 and parts[1].isdigit():
            minutes = int(parts[1])
            if minutes not in SNOOZE_MINUTES:
                return None
            until = _now() + timedelta(minutes=minutes)
            await snooze(db, item, dose["id"], user=user, until=until)
            await db.commit()
            return f"{base_text(item, dose)}\n\n⏰ Отложено до {until.astimezone(tz):%H:%M}", open_rows
    except RoutineError as exc:
        return f"{base_text(item, dose)}\n\n{exc}", open_rows
    return None


def _final_line(dose: dict, tz: ZoneInfo) -> str:
    if dose["status"] == STATUS_DONE:
        return f"✓ {dose.get('done_by_name') or 'дали'} — в {_dt(dose['done_at']).astimezone(tz):%H:%M}"
    if dose["status"] == STATUS_SKIPPED:
        return "⏭ Пропущен"
    return "⏭ Никто не отметил — пропущен"


async def run_worker() -> None:
    """Раз в минуту: истёкшие приёмы — в пропущенные, следующие — завести.
    Сами пинги шлёт общий диспетчер уведомлений (notification_dispatch.py)."""
    import asyncio

    from app.db import async_session

    while True:
        try:
            async with async_session() as db:
                await tick(db)
                await db.commit()
        except Exception:
            logger.exception("Ошибка при обходе рутин")
        await asyncio.sleep(60)
