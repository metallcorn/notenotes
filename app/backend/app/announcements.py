"""Объявления участникам спейса: «ушёл из дома, вернусь к 20:00».

Просьба владельца 01.11: сказать семье одной фразой — в бота, в веб или
через MCP, — чтобы всем участникам спейса сразу прилетело в Telegram и
push, а сам факт (когда ушёл, когда обещал и когда вернулся) где-то
остался. Напоминание для этого не годится: оно требует время в
будущем и переспрашивает перед созданием.

Хранение — журнал, не заметка на каждый уход (двадцать уходов в неделю
дали бы двадцать заметок): одна заметка на месяц в папке «Объявления»
спейса, каждое объявление — строка, свежее сверху. Структурно записи
лежат в properties["entries"] той же заметки, как приёмы у рутины:
«я дома» дописывает последнюю открытую, а не парсит текст. Открытые
записи с ожидаемым временем продублированы в detected_events, чтобы без
отдельного кода попасть в «Скоро» на главной, адженду и утреннюю сводку.

Уведомление получают все участники спейса, включая автора: ему это
подтверждение того, что ушло остальным, а в личном спейсе — способ
проверить доставку (так владелец и собирался тестировать).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app import collab, realtime
from app.deps import space_member_ids
from app.models import Folder, Item, ItemVersion, SpaceMember, Notification, User

JOURNAL_FOLDER = "Объявления"
JOURNAL_KIND = "announcements"
NOTIFICATION_TYPE = "announcement"

KIND_AWAY = "away"
KIND_INFO = "info"
ICONS = {KIND_AWAY: "🚪", KIND_INFO: "📣"}
CLOSE_ICON = "🏠"

_MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


class AnnouncementError(Exception):
    """Текст для человека: что не так и что сделать."""


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).isoformat() if moment else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def journal_title(day: date) -> str:
    return f"{JOURNAL_FOLDER} · {_MONTHS[day.month - 1]} {day.year}"


def display_name(user: User) -> str:
    return user.name or user.username


def until_label(until: datetime, now: datetime, tz: ZoneInfo) -> str:
    """«до ~20:00», а если не сегодня — «до ~03.11 09:00»."""
    local = until.astimezone(tz)
    if local.date() == now.astimezone(tz).date():
        return f"до ~{local:%H:%M}"
    return f"до ~{local:%d.%m %H:%M}"


def headline(entry: dict, now: datetime, tz: ZoneInfo) -> str:
    """Строка-заголовок: «🚪 Дима: ушёл из дома · до ~20:00»."""
    parts = [f"{ICONS.get(entry.get('kind'), ICONS[KIND_INFO])} {entry['author_name']}: {entry['text']}"]
    until = _dt(entry.get("until"))
    if until:
        parts.append(until_label(until, now, tz))
    return " · ".join(parts)


def render(entries: list[dict], tz: ZoneInfo) -> str:
    """Журнал месяца Markdown-списком, свежее сверху; подробности —
    абзацем под строкой, чтобы длинное объявление не растягивало строку."""
    lines: list[str] = []
    for entry in sorted(entries, key=lambda e: e["at"], reverse=True):
        at = _dt(entry["at"]).astimezone(tz)
        closed_at = _dt(entry.get("closed_at"))
        line = f"- {at:%d.%m %H:%M} {headline(entry, at, tz)}"
        # Не закрыл — строка остаётся с планом: честнее, чем домысливать.
        if closed_at:
            line += f" · {CLOSE_ICON} {closed_at.astimezone(tz):%H:%M}"
            if entry.get("closed_text"):
                line += f" {entry['closed_text']}"
        lines.append(line)
        if entry.get("details"):
            lines.append("")
            lines.append("  " + str(entry["details"]).strip().replace("\n", "\n  "))
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def open_entries(entries: list[dict]) -> list[dict]:
    return [e for e in entries if not e.get("closed_at")]


def _detected_events(entries: list[dict], now: datetime, tz: ZoneInfo) -> list[dict]:
    """Открытые объявления с ожидаемым временем — в «Скоро» и адженду.
    Помечены source, чтобы автотеггер их не переписал (autotag.py) и
    адженда назвала объявлением, а не «распознано в заметке»."""
    events = []
    for entry in open_entries(entries):
        until = _dt(entry.get("until"))
        if until is None:
            continue
        events.append({"id": entry["id"], "at": until.isoformat(), "title": headline(entry, now, tz), "source": JOURNAL_KIND})
    return events


async def _folder(db: AsyncSession, space_id: uuid.UUID) -> uuid.UUID:
    existing = (
        await db.execute(select(Folder).where(Folder.space_id == space_id, Folder.parent_id.is_(None), Folder.name == JOURNAL_FOLDER))
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    folder = Folder(space_id=space_id, parent_id=None, name=JOURNAL_FOLDER)
    db.add(folder)
    await db.flush()
    await realtime.notify_space(space_id, "folders")
    return folder.id


async def journal_for(db: AsyncSession, space_id: uuid.UUID, author_id: uuid.UUID, day: date) -> Item:
    """Заметка-журнал этого месяца в спейсе; создаётся при первом объявлении."""
    month = f"{day.year}-{day.month:02d}"
    existing = (
        await db.execute(
            select(Item).where(
                Item.space_id == space_id,
                Item.deleted_at.is_(None),
                Item.properties["kind"].astext == JOURNAL_KIND,
                Item.properties["month"].astext == month,
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing
    item = Item(
        space_id=space_id,
        folder_id=await _folder(db, space_id),
        author_id=author_id,
        material_type="note",
        title=journal_title(day),
        content="",
        properties={"kind": JOURNAL_KIND, "month": month, "entries": []},
    )
    db.add(item)
    await db.flush()
    return item


async def _write(db: AsyncSession, item: Item, entries: list[dict], *, author_id: uuid.UUID, now: datetime, tz: ZoneInfo) -> None:
    """Перерисовать журнал из записей: версия в историю, текст, события,
    комната совместного редактирования — тот же набор, что у update_note."""
    db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=author_id))
    props = {**(item.properties or {}), "entries": entries}
    events = _detected_events(entries, now, tz)
    if events:
        props["detected_events"] = events
    else:
        props.pop("detected_events", None)
    item.properties = props
    flag_modified(item, "properties")
    item.content = render(entries, tz)


async def _notify(db: AsyncSession, item: Item, entry: dict, *, title: str, body: str) -> int:
    recipients = await space_member_ids(db, item.space_id)
    for user_id in recipients:
        db.add(
            Notification(
                user_id=user_id,
                type=NOTIFICATION_TYPE,
                title=title[:255],
                body=body,
                payload={"item_id": str(item.id), "space_id": str(item.space_id), "entry_id": entry["id"]},
            )
        )
    return len(recipients)


async def announce(
    db: AsyncSession,
    *,
    space_id: uuid.UUID,
    author: User,
    text: str,
    details: str = "",
    until: datetime | None = None,
    kind: str = KIND_AWAY,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> tuple[Item, dict, int]:
    """Записать объявление в журнал месяца и разослать участникам спейса.
    Возвращает заметку, запись и число получателей."""
    now = now or datetime.now(timezone.utc)
    text = " ".join(text.split())
    if not text:
        raise AnnouncementError("Пустое объявление — скажи, что передать")
    if until is not None and until <= now:
        raise AnnouncementError(f"Время «до» уже прошло ({until.astimezone(tz):%d.%m %H:%M}) — назови время в будущем")
    item = await journal_for(db, space_id, author.id, now.astimezone(tz).date())
    entries = list((item.properties or {}).get("entries") or [])
    entry = {
        "id": uuid.uuid4().hex,
        "author_id": str(author.id),
        "author_name": display_name(author),
        "kind": kind if kind in ICONS else KIND_INFO,
        "text": text,
        "details": details.strip(),
        "at": _iso(now),
        "until": _iso(until),
        "closed_at": None,
        "closed_text": None,
    }
    entries.append(entry)
    await _write(db, item, entries, author_id=author.id, now=now, tz=tz)
    body_lines = [l for l in (until_label(until, now, tz) if until else "", entry["details"]) if l]
    recipients = await _notify(db, item, entry, title=headline({**entry, "until": None}, now, tz), body="\n".join(body_lines))
    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    await collab.invalidate_room(item.id)
    return item, entry, recipients


async def find_open(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[Item, dict]]:
    """Открытые объявления этого человека во всех его спейсах, свежие первыми."""
    items = (
        await db.execute(
            select(Item)
            .join(SpaceMember, SpaceMember.space_id == Item.space_id)
            .where(
                SpaceMember.user_id == user_id,
                Item.deleted_at.is_(None),
                Item.properties["kind"].astext == JOURNAL_KIND,
            )
        )
    ).scalars().all()
    found = [
        (item, entry)
        for item in items
        for entry in (item.properties or {}).get("entries") or []
        if entry.get("author_id") == str(user_id) and not entry.get("closed_at")
    ]
    found.sort(key=lambda pair: pair[1]["at"], reverse=True)
    return found


async def close(
    db: AsyncSession,
    *,
    author: User,
    text: str,
    tz: ZoneInfo,
    entry_id: str | None = None,
    now: datetime | None = None,
) -> tuple[Item, dict, int]:
    """«Я дома»: закрыть последнее открытое объявление автора (или
    указанное), дописать время в журнал, сказать участникам."""
    now = now or datetime.now(timezone.utc)
    text = " ".join(text.split())
    if not text:
        raise AnnouncementError("Пустой текст — скажи, что передать: «дома», «на месте», «закончили»")
    candidates = await find_open(db, author.id)
    if not candidates:
        raise AnnouncementError("Открытых объявлений нет — закрывать нечего; новое делается через announce")
    if entry_id:
        candidates = [pair for pair in candidates if pair[1]["id"] == entry_id]
        if not candidates:
            raise AnnouncementError("Такого открытого объявления нет — возьми entry_id из списка открытых или не указывай его")
    item, entry = candidates[0]
    entries = list((item.properties or {}).get("entries") or [])
    for stored in entries:
        if stored["id"] == entry["id"]:
            stored["closed_at"] = _iso(now)
            stored["closed_text"] = text
            entry = stored
    await _write(db, item, entries, author_id=author.id, now=now, tz=tz)
    recipients = await _notify(db, item, entry, title=f"{CLOSE_ICON} {display_name(author)}: {text}", body="")
    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    await collab.invalidate_room(item.id)
    return item, entry, recipients


def entry_summary(item: Item, entry: dict, tz: ZoneInfo) -> dict[str, Any]:
    until = _dt(entry.get("until"))
    closed = _dt(entry.get("closed_at"))
    return {
        "entry_id": entry["id"],
        "journal_id": str(item.id),
        "space_id": str(item.space_id),
        "text": entry["text"],
        **({"details": entry["details"]} if entry.get("details") else {}),
        "at": _dt(entry["at"]).astimezone(tz).isoformat(),
        **({"until": until.astimezone(tz).isoformat()} if until else {}),
        **({"closed_at": closed.astimezone(tz).isoformat(), "closed_text": entry.get("closed_text")} if closed else {}),
    }
