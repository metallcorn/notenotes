from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app import routines
from app.deps import space_member_ids
from app.llm.base import ToolDefinition
from app.models import Notification, User
from app.tools.notes import _get_item_cross_space
from app.recurrence import HUMAN, RULES
from app.tools.registry import ToolContext, ToolError
from app.user_timezone import assume_default_timezone, resolve_timezone

# Напоминания переиспользуют центр уведомлений (ТЗ §13), не отдельную
# таблицу — trigger_at в будущем просто не отдаётся списком, пока время не
# наступит (см. routers/notifications.py). Планировщика/воркера не нужно:
# "видимость" уведомления — это фильтр в выборке, не активное событие.

CREATE_REMINDER = ToolDefinition(
    name="create_reminder",
    description=(
        "Создать напоминание — появится в центре уведомлений в указанное время (не сразу, не "
        "прямо сейчас). ВСЕГДА сначала спроси пользователя, нужно ли напоминание и на какое время "
        "— никогда не создавай сам просто потому что в разговоре упомянута дата или дедлайн, только "
        "по явному согласию (как /remind в Slack — спрашивает, прежде чем поставить). Можно "
        "привязать к конкретной заметке/списку (item_id) и, если это список, к конкретному пункту "
        "(entry_id из get_list) — клик по уведомлению откроет ровно эту заметку или этот пункт, а "
        "не список целиком. Если заметка лежит в спейсе с другими участниками — напоминание "
        "получат ВСЕ участники этого спейса, не только тот, кто его поставил (права на спейс общие) "
        "— полезно упомянуть это пользователю при подтверждении, если у спейса есть другие люди."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Короткий заголовок напоминания"},
            "body": {"type": "string", "description": "Необязательные подробности"},
            "trigger_at": {
                "type": "string",
                "description": "Когда показать напоминание, ISO 8601 ('2026-08-08T09:00:00') — только то, что явно назвал пользователь",
            },
            "repeat": {
                "type": "string",
                "enum": ["daily", "weekly", "monthly", "yearly"],
                "description": (
                    "Повторять ли: daily/weekly/monthly/yearly. Ставь, только если пользователь "
                    "сказал про регулярность («каждый понедельник», «раз в месяц», «ежегодно»). "
                    "Разовую просьбу («напомни завтра») повторяющейся НЕ делай."
                ),
            },
            "item_id": {"type": "string", "description": "id заметки/списка, к которому относится напоминание — необязательно"},
            "entry_id": {
                "type": "string",
                "description": "id конкретного пункта списка (из get_list) — необязательно, только если item_id это список",
            },
        },
        "required": ["title", "trigger_at"],
    },
)


# Тул отдаёт время В ТОМ ЖЕ ПОЯСЕ, в котором его прислала модель, а не в
# UTC. Это исправление реального бага, пойманного замером 2026-09-05
# (сценарий воскресного ужина, проваливался ВО ВСЕХ замерах подряд):
#
#   АССИСТЕНТ: Начинать нужно в 13:30
#   create_reminder(trigger_at='...T13:30')
#   TOOL_RESULT: {"trigger_at": "2026-09-06T11:30:00+00:00"}   ← UTC, верно
#   create_reminder(trigger_at='...T11:30')                    ← поверил эху
#   TOOL_RESULT: {"trigger_at": "2026-09-06T09:30:00+00:00"}   ← дубль
#
# Модель задала верное время, увидела в ответе UTC-значение на два часа
# меньше, решила что ошиблась — и создала ВТОРОЕ напоминание на два часа
# раньше. Она не доверяет собственному правильному вводу, потому что эхо
# выглядит иначе.
#
# Чинится не промптом, а форматом ответа: эхо должно подтверждать ввод.
# Модель мыслит в местном времени пользователя (промпт так и устроен — см.
# now_in_default_timezone), поэтому и отвечать надо в нём. UTC остаётся
# отдельным полем: для хранения он и есть правда, и при разборе проблем
# его полезно видеть.
def _echo_times(dt: datetime, tz_name: str | None) -> dict[str, str]:
    local = dt.astimezone(resolve_timezone(tz_name))
    return {"trigger_at": local.isoformat(), "trigger_at_utc": dt.astimezone(timezone.utc).isoformat()}

async def create_reminder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    if not title:
        raise ToolError("Название напоминания не может быть пустым — коротко сформулируй, о чём напомнить")

    repeat = str(args.get("repeat") or "").strip().lower() or None
    if repeat is not None and repeat not in RULES:
        raise ToolError(
            f"Неизвестное правило повтора: {repeat} — допустимы daily, weekly, monthly, yearly "
            "или вообще без него, если повторять не нужно"
        )

    trigger_raw = args.get("trigger_at")
    if not trigger_raw:
        raise ToolError("trigger_at обязателен — время в формате ISO, например 2026-09-04T14:30 (в местном времени пользователя)")
    try:
        trigger_at = datetime.fromisoformat(str(trigger_raw))
    except ValueError:
        raise ToolError(f"Некорректные дата/время: {trigger_raw} — нужен формат ISO, например 2026-09-04T14:30 (в местном времени пользователя)") from None
    # Реальный найденный баг: наивное время (модель обычно так и отдаёт
    # trigger_at по просьбе "напомни в 9 утра") трактовалось как UTC — для
    # пользователя в Польше (CEST, UTC+2 летом) напоминание срабатывало на
    # 2 часа позже, чем он просил. assume_default_timezone трактует его как
    # ЖИВОЙ пояс из браузера (ctx.client_timezone) — "9 утра" в прямом
    # обращении к ассистенту означает 9 утра там, где пользователь сейчас
    # физически находится, не где он обычно живёт (app/user_timezone.py).
    trigger_at = assume_default_timezone(trigger_at, ctx.client_timezone)

    payload: dict[str, Any] = {}
    recipient_ids = [ctx.user_id]
    item_id_raw = args.get("item_id")
    if item_id_raw:
        item = await _get_item_cross_space(ctx, item_id_raw)
        payload["item_id"] = str(item.id)
        payload["space_id"] = str(item.space_id)
        payload["material_type"] = item.material_type

        entry_id_raw = args.get("entry_id")
        if entry_id_raw:
            entries = item.properties.get("entries", [])
            if not any(e["id"] == str(entry_id_raw) for e in entries):
                raise ToolError("Пункт списка не найден — сначала вызови get_list, чтобы увидеть реальные пункты и их id")
            payload["entry_id"] = str(entry_id_raw)

        # Заметка/список могут быть общими на весь спейс — права на спейс
        # распространяются на всех его участников, значит и напоминание,
        # поставленное в такой заметке, должно сработать у каждого, а не
        # только у автора (реальный запрос: раньше срабатывало молча только
        # у того, кто поставил, даже если заметку вместе редактируют).
        recipient_ids = await space_member_ids(ctx.db, item.space_id)
        if ctx.user_id not in recipient_ids:
            recipient_ids.append(ctx.user_id)

    body = str(args.get("body", "")).strip()
    own_notification: Notification | None = None
    for recipient_id in recipient_ids:
        notification = Notification(
            user_id=recipient_id,
            type="reminder",
            repeat_rule=repeat,
            title=title,
            body=body,
            payload=payload,
            trigger_at=trigger_at,
        )
        ctx.db.add(notification)
        if recipient_id == ctx.user_id:
            own_notification = notification
    await ctx.db.commit()
    await ctx.db.refresh(own_notification)
    return {
        "id": str(own_notification.id),
        "title": title,
        # Повтор возвращаем словами: модель должна сказать человеку, что
        # напоминание теперь регулярное, а не промолчать об этом.
        **({"repeat": HUMAN[repeat]} if repeat else {}),
        **_echo_times(trigger_at, ctx.client_timezone),
    }


# "Выполнено" — независимая ось от trigger_at (ТЗ живой жалобы: время
# напоминания прошло не значит, что дело сделано, юзер продолжает считать
# его активным, пока сам не отметит). list_reminders — чтобы модель могла
# найти нужное напоминание по смыслу перед resolve_reminder, не зная id
# заранее (тот же паттерн, что get_list/toggle_list_entry для пунктов
# списка).

LIST_REMINDERS = ToolDefinition(
    name="list_reminders",
    description=(
        "Список активных (ещё не отмеченных выполненными) напоминаний пользователя — id, "
        "заголовок, текст, время срабатывания. Используй перед resolve_reminder, чтобы найти "
        "нужное напоминание по смыслу, если пользователь ссылается на него не по id, а по теме "
        "(например «отметь, что с банком я разобрался»).\n\n"
        "Реальный найденный случай: на вопрос «какие у меня дела на сегодня?» модель вызвала "
        "search_base (полнотекстовый поиск по заметкам) вместо этого тула — и ответила "
        "выдуманными «делами», собранными из содержимого случайно найденных заметок, при том "
        "что реальных напоминаний на сегодня не было вообще. Это ЕДИНСТВЕННЫЙ источник правды "
        "о том, что у пользователя реально запланировано/напомнится (сегодня, завтра, на "
        "неделе и т.п.) — вызывай его на ЛЮБОЙ такой вопрос, даже если в нём нет слова "
        "«напоминание». search_base ищет по ТЕКСТУ заметок и не имеет отношения к реальным "
        "срокам — заметка, в которой просто УПОМИНАЕТСЯ дата, не значит, что событие "
        "запланировано на неё."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)


async def list_reminders(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.db.execute(
        select(Notification)
        .where(Notification.user_id == ctx.user_id, Notification.resolved_at.is_(None))
        .order_by(Notification.trigger_at.asc().nulls_first())
    )
    reminders = result.scalars().all()
    return {
        "reminders": [
            {
                "id": str(n.id),
                "title": n.title,
                "body": n.body,
                **({"repeat": HUMAN[n.repeat_rule]} if n.repeat_rule in HUMAN else {}),
                **(
                    _echo_times(n.trigger_at, ctx.client_timezone)
                    if n.trigger_at
                    else {"trigger_at": None}
                ),
            }
            for n in reminders
        ]
    }


RESOLVE_REMINDER = ToolDefinition(
    name="resolve_reminder",
    description=(
        "Отметить напоминание выполненным — уходит из активных, вне зависимости от того, "
        "наступило ли уже его время. Используй, когда пользователь говорит, что уже сделал или "
        "разобрался с тем, о чём было напоминание. Не спрашивай подтверждения — сама просьба "
        "пользователя уже и есть подтверждение (в отличие от create_reminder, где спрашивать "
        "обязательно)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "notification_id": {"type": "string", "description": "id напоминания, взятый из list_reminders"},
        },
        "required": ["notification_id"],
    },
)


async def resolve_reminder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    notification_id_raw = args.get("notification_id")
    if not notification_id_raw:
        raise ToolError("notification_id обязателен — id напоминания из результата list_reminders")
    try:
        notification_id = uuid.UUID(str(notification_id_raw))
    except ValueError:
        raise ToolError("Некорректный notification_id — нужен UUID из результата list_reminders") from None

    notification = await ctx.db.get(Notification, notification_id)
    if notification is None or notification.user_id != ctx.user_id:
        raise ToolError("Напоминание не найдено — вызови list_reminders, чтобы увидеть реальные напоминания и их id")

    if notification.type == routines.NOTIFICATION_TYPE:
        # Пинг приёма рутины: «сделано» = «дал», закрывает приём у всех
        # участников и заводит следующий (app/routines.py).
        payload = notification.payload or {}
        item = await routines.lock_item(ctx.db, uuid.UUID(str(payload.get("item_id"))))
        user = await ctx.db.get(User, ctx.user_id)
        if item is None or item.deleted_at is not None or user is None:
            raise ToolError("Рутина этого приёма не найдена — пинг устарел, рутину удалили; вызови list_reminders, чтобы увидеть актуальные")
        try:
            await routines.mark_done(ctx.db, item, str(payload.get("dose_id")), user=user)
        except routines.RoutineError as exc:
            raise ToolError(str(exc)) from None
        await ctx.db.commit()
        return {"id": str(notification.id), "title": notification.title, "resolved": True, "routine": True}

    if notification.resolved_at is None:
        notification.resolved_at = datetime.now(timezone.utc)
        await ctx.db.commit()
    return {"id": str(notification.id), "title": notification.title, "resolved": True}


SNOOZE_REMINDER = ToolDefinition(
    name="snooze_reminder",
    description=(
        "Отложить напоминание — оно сработает ЗАНОВО в новое время (придёт в Telegram и "
        "колокольчик ещё раз). Используй на «отложи», «напомни позже», «перенеси на завтра» про "
        "уже существующее напоминание — НЕ создавай вместо этого новое через create_reminder: "
        "старое осталось бы висеть рядом с дублем. id — из list_reminders. Подтверждения не "
        "спрашивай: сама просьба и есть подтверждение."
    ),
    parameters={
        "type": "object",
        "properties": {
            "notification_id": {"type": "string", "description": "id напоминания, взятый из list_reminders"},
            "until": {
                "type": "string",
                "description": "Когда напомнить снова, ISO 8601 в местном времени пользователя ('2026-08-08T09:00:00')",
            },
        },
        "required": ["notification_id", "until"],
    },
)


async def snooze_reminder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from app.reminder_actions import snooze

    try:
        notification_id = uuid.UUID(str(args.get("notification_id") or ""))
    except ValueError:
        raise ToolError("Некорректный notification_id — нужен UUID из результата list_reminders") from None
    until_raw = args.get("until")
    try:
        until = datetime.fromisoformat(str(until_raw))
    except ValueError:
        raise ToolError(f"Некорректные дата/время: {until_raw} — нужен формат ISO, например 2026-09-04T14:30") from None
    # Наивное время — в живом поясе пользователя, как у create_reminder.
    until = assume_default_timezone(until, ctx.client_timezone)
    if until <= datetime.now(timezone.utc):
        raise ToolError("Это время уже прошло — отложить можно только на будущее")

    notification = await ctx.db.get(Notification, notification_id)
    if notification is None or notification.user_id != ctx.user_id:
        raise ToolError("Напоминание не найдено — вызови list_reminders, чтобы увидеть реальные напоминания и их id")

    snooze(ctx.db, notification, until)
    await ctx.db.commit()
    return {"id": str(notification.id), "title": notification.title, **_echo_times(until, ctx.client_timezone)}
