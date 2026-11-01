"""Инструменты ассистента для объявлений участникам спейса (app/announcements.py).

Два действия: сказать («ушёл, вернусь к 20:00») и закрыть («я дома»).
В отличие от create_reminder подтверждения не требуют: фраза человека
и есть действие, а переспрос убил бы весь смысл «сказал одной строкой».
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app import announcements
from app.llm.base import ToolDefinition
from app.models import User
from app.tools.notes import SPACE_PARAM, _resolve_space, item_url
from app.tools.registry import ToolContext, ToolError
from app.user_timezone import assume_default_timezone, resolve_timezone

ANNOUNCE = ToolDefinition(
    name="announce",
    description=(
        "Сказать что-то всем участникам спейса прямо сейчас: каждому уходит уведомление в Telegram, "
        "push и колокольчик, а запись ложится строкой в журнал «Объявления» этого месяца. Вызывай, "
        "когда пользователь обращается к другим людям, а не к себе: «скажи семье, что ушёл, вернусь "
        "к десяти», «анонс музыкантам: реп сегодня с 10 до 12», «предупреди всех, что интернет "
        "отключат». Спейс — тот, что назвал пользователь (space по названию), иначе текущий спейс "
        "диалога. НЕ переспрашивай и не проси подтверждения — фраза и есть действие; уточни только "
        "если спейс не назван, а текущий спейс личный и у пользователя есть общие. text — одна "
        "короткая строка, заголовок уведомления (без имени автора — оно подставится само); всё "
        "длинное — в details. until — до какого времени (вернусь к…, занят до…), если пользователь "
        "его назвал. kind=away для «ушёл/уехал/буду там-то», info для остального. Это НЕ напоминание "
        "(create_reminder) и не заметка себе (create_note)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Короткий заголовок объявления: «ушёл из дома, вернусь к 22:00»"},
            "details": {"type": "string", "description": "Подробности, если есть, — любой длины, уйдут в тело уведомления и под строку журнала"},
            "until": {
                "type": "string",
                "description": "До какого времени: ISO 8601 в местном времени («2026-11-01T22:00») или просто «22:00» — сегодня (если уже прошло — завтра)",
            },
            "kind": {"type": "string", "enum": ["away", "info"], "description": "away — ушёл/уехал/буду в другом месте; info — всё остальное"},
            "space": SPACE_PARAM,
        },
        "required": ["text"],
    },
)

CLOSE_ANNOUNCEMENT = ToolDefinition(
    name="close_announcement",
    description=(
        "Закрыть последнее открытое объявление пользователя: «я дома», «вернулся», «на месте», "
        "«закончили». Участники спейса получают короткое уведомление, в строку журнала дописывается "
        "фактическое время. Спейс указывать не нужно — ищется последнее открытое объявление этого "
        "человека во всех его спейсах. text — что передать («дома», «на месте»). Если открытых "
        "несколько и непонятно какое, инструмент вернёт список — спроси пользователя и передай entry_id."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Что сказать участникам: «дома», «на месте», «закончили»"},
            "entry_id": {"type": "string", "description": "id конкретного объявления, если открытых несколько"},
        },
        "required": ["text"],
    },
)

_HHMM_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


def parse_until(raw: Any, tz_name: str | None, now: datetime) -> datetime | None:
    """«22:00» → сегодня в 22:00 по местному поясу (прошло — завтра); ISO — как есть."""
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip()
    tz = resolve_timezone(tz_name)
    match = _HHMM_RE.match(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ToolError(f"Некорректное время «{text}» — нужно ЧЧ:ММ, например 22:00")
        local_now = now.astimezone(tz)
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ToolError(f"Некорректное until «{text}» — передай ISO 8601 («2026-11-01T22:00») или «22:00»") from None
    return assume_default_timezone(parsed, tz_name)


async def _author(ctx: ToolContext) -> User:
    user = await ctx.db.get(User, ctx.user_id)
    if user is None:
        raise ToolError("Пользователь не найден — войди заново")
    return user


def _result(item, entry, recipients: int, tz, *, space_name: str = "") -> dict[str, Any]:
    return {
        **announcements.entry_summary(item, entry, tz),
        "recipients": recipients,
        "journal_title": item.title,
        "url": item_url(item.id),
        **({"space_name": space_name} if space_name else {}),
    }


async def announce(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("Пустой text — передай короткую строку объявления, например «ушёл из дома, вернусь к 22:00»")
    now = datetime.now(timezone.utc)
    until = parse_until(args.get("until"), ctx.client_timezone, now)
    space_id = await _resolve_space(ctx, args.get("space"))
    tz = resolve_timezone(ctx.client_timezone)
    try:
        item, entry, recipients = await announcements.announce(
            ctx.db,
            space_id=space_id,
            author=await _author(ctx),
            text=text,
            details=str(args.get("details") or ""),
            until=until,
            kind=str(args.get("kind") or announcements.KIND_AWAY),
            tz=tz,
            now=now,
        )
    except announcements.AnnouncementError as exc:
        raise ToolError(str(exc)) from None
    from app.models import Space

    space = await ctx.db.get(Space, space_id)
    return _result(item, entry, recipients, tz, space_name=space.name if space else "")


async def close_announcement(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("Пустой text — передай, что сказать участникам: «дома», «на месте»")
    tz = resolve_timezone(ctx.client_timezone)
    author = await _author(ctx)
    entry_id = str(args.get("entry_id") or "").strip() or None
    if entry_id is None:
        candidates = await announcements.find_open(ctx.db, author.id)
        if len(candidates) > 1 and len({item.space_id for item, _ in candidates}) > 1:
            return {
                "ambiguous": True,
                "hint": "Открытых объявлений несколько в разных спейсах — спроси пользователя, какое закрыть, и передай entry_id",
                "open": [announcements.entry_summary(item, entry, tz) for item, entry in candidates],
            }
    try:
        item, entry, recipients = await announcements.close(ctx.db, author=author, text=text, tz=tz, entry_id=entry_id)
    except announcements.AnnouncementError as exc:
        raise ToolError(str(exc)) from None
    return _result(item, entry, recipients, tz)
