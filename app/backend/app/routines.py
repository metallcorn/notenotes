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
from app.routine_schedule import (
    STATUS_DONE,
    STATUS_MISSED,
    STATUS_PENDING,
    STATUS_SKIPPED,
    describe,
    nag_until,
    next_planned,
)
from app.user_timezone import resolve_timezone

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


async def _finalize_notifications(
    db: AsyncSession, item: Item, dose: dict, line: str, *, now: datetime, except_id: uuid.UUID | None = None
) -> None:
    """Закрыть пинги приёма у всех и перерисовать их сообщения в итог.

    except_id — уведомление, чьё сообщение перерисует сам обработчик
    кнопки (telegram_bot.py): Telegram отдаёт message_id только ему, и
    второй edit того же сообщения был бы лишним запросом.
    """
    from app import telegram_bot

    notifications = await _dose_notifications(db, item, dose["id"])
    links = await _links_for(db, [n.user_id for n in notifications])
    for n in notifications:
        if n.resolved_at is None:
            n.resolved_at = now
        n.dispatched_at = n.dispatched_at or now
        message_id = (n.payload or {}).get("telegram_message_id")
        chat_id = links.get(n.user_id)
        if message_id and chat_id and n.id != except_id:
            await telegram_bot.edit_message(chat_id, message_id, f"{base_text(item, dose)}\n\n{line}", {"inline_keyboard": _open_rows(item)})
        await realtime.notify_user(n.user_id)
    await realtime.notify_space(item.space_id, "items")


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
    except_notification: uuid.UUID | None = None,
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
    await _finalize_notifications(
        db, item, dose, f"✓ {dose['done_by_name']} — в {local:%H:%M}", now=now, except_id=except_notification
    )
    await ensure_open_dose(db, item, now)
    return dose


async def skip(db: AsyncSession, item: Item, dose_id: str, *, user: User, except_notification: uuid.UUID | None = None) -> dict:
    now = _now()
    props = props_of(item)
    dose = find_dose(props, dose_id)
    if dose is None or dose["status"] != STATUS_PENDING:
        raise RoutineError("Этот приём уже закрыт")
    _snapshot(db, item, user.id)
    _close(dose, STATUS_SKIPPED)
    set_props(item, props)
    name = await _user_name(db, user.id)
    await _finalize_notifications(db, item, dose, f"⏭ Пропущен — {name}", now=now, except_id=except_notification)
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
    перерисовать ЭТО сообщение, или None, если данные не наши."""
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
            dose = await mark_done(db, item, dose["id"], user=user, except_notification=n.id)
            await db.commit()
            return f"{base_text(item, dose)}\n\n{_final_line(dose, tz)}", open_rows
        if action == "k" and len(parts) == 2:
            dose = await skip(db, item, dose["id"], user=user, except_notification=n.id)
            await db.commit()
            return f"{base_text(item, dose)}\n\n{_final_line(dose, tz)}", open_rows
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
