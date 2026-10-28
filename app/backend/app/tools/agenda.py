"""Что у человека впереди — одним ответом.

Дыра, найденная вопросом «увидит ли Клод мою адженду». Оказалось, что не
увидит её и НАШ СОБСТВЕННЫЙ ассистент, и Telegram-бот: спросить «что у
меня на неделе» было одинаково бесполезно везде.

Причина в том, что «Активность» в вебе — не одна вещь, а склейка двух
источников, и второй жил вообще без инструмента:

  * напоминания и уведомления — их list_reminders отдаёт (все
    неразрешённые, не только с датой);
  * РАСПОЗНАННЫЕ СОБЫТИЯ — даты, которые LLM сама нашла в заметках,
    письмах и билетах (app/autotag.py). Их 58 у владельца базы, и они
    пассивные: никуда не рассылаются, нигде не всплывают, кроме
    ActivityView. То есть ассистент находил заметку поиском, но не знал,
    что в ней распознан срок на послезавтра.

Второе, по-моему, и есть настоящая адженда: человек не заводил эти
события руками, они появились сами — и именно поэтому про них легче всего
забыть.

Отдельный инструмент, а не расширение list_reminders: у того своя роль
(показать, что можно закрыть через resolve_reminder), и подмешивать туда
записи, которые закрыть нельзя, значило бы ломать её.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import select

from app.llm.base import ToolDefinition
from app.models import Item, Notification, Space, SpaceMember
from app.event_dedup import same_event
from app.tools.notes import item_url
from app.tools.registry import ToolContext
from app.user_timezone import now_local_date

# Горизонт по умолчанию. Две недели — «что впереди», а не «весь календарь»:
# длинный список перестаёт быть ответом на вопрос.
DEFAULT_HORIZON_DAYS = 14
MAX_HORIZON_DAYS = 365

DEFINITION = ToolDefinition(
    name="list_agenda",
    description=(
        "Что у пользователя впереди: напоминания, которые он ставил сам, И события, "
        "распознанные автоматически в его заметках, письмах и билетах (даты вылетов, "
        "приёмов, сроков действия документов). Вторые он НЕ заводил руками и обычно про "
        "них не помнит — поэтому вызывай этот инструмент на любой вопрос вида «что у меня "
        "на этой неделе», «что предстоит», «не забыл ли я чего», а также прежде чем "
        "советовать что-то запланировать: возможно, у него уже занято. "
        "Записи с «уже_прошло»: true сегодня УЖЕ состоялись — не объявляй их предстоящими, "
        "но и не замалчивай («сегодня в 11:00 был …, уже прошёл»). "
        "kind=\"срок документа\" — это НЕ мероприятие: там «срок_истекает» (когда документ "
        "перестанет действовать) и «напомнить» (когда мы предупреждаем, обычно за два "
        "месяца) — не путай эти две даты и не называй такое событием. "
        "Зашифрованный сейф не просматривается."
    ),
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": (
                    f"На сколько дней вперёд смотреть. По умолчанию {DEFAULT_HORIZON_DAYS}. "
                    "Больше — только если пользователь спросил про далёкое будущее."
                ),
            },
        },
        "required": [],
    },
)


def _local_midnight_utc(now: datetime, tz_name: str | None) -> datetime:
    """Начало сегодняшнего дня по месту человека, выраженное в UTC."""
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local_start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc)


async def collect_agenda(
    db, user_id: uuid.UUID, *, days: int = DEFAULT_HORIZON_DAYS, tz_name: str | None = None
) -> dict[str, Any]:
    """Что впереди — общая часть для инструмента и утренней сводки.

    Вынесено из handle(), чтобы сводка в Telegram (app/daily_digest.py) и
    ответ ассистенту собирались ОДНИМ кодом: иначе они разошлись бы в
    том, что считать «сегодняшним» или «активным», и человек получал бы
    утром одно, а на вопрос «что у меня сегодня» — другое.
    """
    days = max(1, min(int(days), MAX_HORIZON_DAYS))

    now = datetime.now(timezone.utc)
    # Нижняя граница — начало СЕГОДНЯШНЕГО дня, а не текущий момент:
    # событие в 9 утра, о котором спрашивают в 11, ещё сегодняшнее и из
    # ответа выпадать не должно.
    #
    # Начало дня — в ПОЯСЕ ЧЕЛОВЕКА, не в UTC. Раньше бралось UTC-полночь:
    # для Варшавы (UTC+2) окно начиналось в 02:00 по местному, и всё, что
    # ночью между полуночью и двумя, выпадало из «сегодня».
    since = _local_midnight_utc(now, tz_name)
    until = now + timedelta(days=days)

    entries: list[dict[str, Any]] = []

    # 1. Напоминания и уведомления. Условие то же, что у list_reminders
    # (неразрешённые), — чтобы два инструмента не расходились в том, что
    # считать активным.
    reminders = (
        await db.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.resolved_at.is_(None),
                Notification.trigger_at.isnot(None),
                Notification.trigger_at >= since,
                Notification.trigger_at <= until,
            )
            .order_by(Notification.trigger_at.asc())
        )
    ).scalars().all()
    for n in reminders:
        # Ссылка на заметку-источник, если напоминание привязано к ней
        # (срок документа, билет, «напомни про эту заметку»). Нужна и
        # ассистенту — чтобы сослаться на источник, а не утверждать от
        # себя, — и кнопке «Открыть» в утренней сводке.
        payload = n.payload or {}
        source_item = payload.get("item_id")
        # Срок документа — НЕ мероприятие, и путать их нельзя.
        #
        # Живой случай 10.10: на голосовой вопрос «какие мероприятия на
        # этой неделе» ассистент ответил «11 октября в 12:00 — Срок
        # истекает 10.12.2026: Сервисная книжка». Две даты спорят друг с
        # другом, и человек прочитал это как бред — справедливо.
        #
        # Причина в том, что у такого напоминания ДВЕ разные даты:
        # trigger_at — когда предупредить (за 60 дней, document_expiry.py),
        # а payload.expires_on — собственно срок. В адженде было только
        # первое, второе оставалось внутри названия текстом, и модели
        # приходилось догадываться. Теперь оба поля явные.
        expires_on = payload.get("expires_on")
        entries.append({
            "at": n.trigger_at.isoformat(),
            "title": n.title,
            # Приём рутины (app/routines.py) — не «напоминание»: ассистент
            # должен говорить «приём таблетки в 20:00», а не «напоминание».
            "kind": "срок документа" if expires_on else ("приём" if payload.get("dose_id") else "напоминание"),
            # id нужен, чтобы можно было закрыть через resolve_reminder,
            # не разыскивая его отдельным вызовом.
            "reminder_id": str(n.id),
            # Приём — ещё и routine_id: отметить можно через mark_dose,
            # посмотреть журнал — list_routines.
            **({"routine_id": payload.get("item_id")} if payload.get("dose_id") else {}),
            **({"срок_истекает": expires_on, "напомнить": n.trigger_at.date().isoformat()} if expires_on else {}),
            **({"url": item_url(source_item)} if source_item else {}),
            **({"details": n.body} if n.body else {}),
        })

    # 2. Распознанные события. Права и исключение сейфа повторяют
    # routers/items.py::list_detected_events буквально — расхождение
    # означало бы утечку чужих записей или содержимого сейфа.
    items = (
        await db.execute(
            select(Item)
            .join(SpaceMember, SpaceMember.space_id == Item.space_id)
            .join(Space, Space.id == Item.space_id)
            .where(
                SpaceMember.user_id == user_id,
                Item.deleted_at.is_(None),
                Space.is_vault.is_(False),
                Item.properties.has_key("detected_events"),
            )
        )
    ).scalars().all()
    for item in items:
        for event in item.properties.get("detected_events") or []:
            at, title = event.get("at"), event.get("title")
            if not at or not title:
                continue
            try:
                at_dt = datetime.fromisoformat(at)
            except ValueError:
                # Модель иногда пишет дату в своём формате. Пропускаем —
                # но не падаем: одна кривая запись не должна отнимать
                # у человека весь ответ.
                continue
            if at_dt.tzinfo is None:
                at_dt = at_dt.replace(tzinfo=timezone.utc)
            if not (since <= at_dt <= until):
                continue
            entries.append({
                "at": at,
                "title": title,
                "kind": "распознано в заметке",
                # Откуда взялось — обязательно. Событие распознала модель,
                # и человек имеет право проверить источник, а ассистент —
                # сослаться на него вместо утверждения от себя.
                "source_note": item.title or "Без названия",
                "item_id": str(item.id),
                "url": item_url(item.id),
            })

    entries.sort(key=lambda e: e["at"])

    # Прошедшее сегодняшнее ПОМЕЧАЕМ, а не выбрасываем.
    #
    # Нижняя граница окна — начало сегодняшнего дня (см. выше): событие в
    # 9 утра, о котором спрашивают в 11, ещё сегодняшнее. Но до 10.10
    # модель не имела никакого признака, прошло оно или нет, — и на
    # вопрос в 18:38 про «мероприятия на этой неделе» молча выбросила
    # марш, который был в 11:00. Могла с тем же успехом объявить его
    # предстоящим: ровно так и вышло с рейсом, о котором предупредили,
    # когда человек уже сидел в самолёте.
    #
    # Выбрасывать здесь нельзя: «что у меня было сегодня» — законный
    # вопрос, и адженда на него отвечает. Поэтому факт, а не фильтр.
    for entry in entries:
        try:
            at_dt = datetime.fromisoformat(entry["at"])
        except ValueError:
            continue
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=timezone.utc)
        if at_dt < now:
            entry["уже_прошло"] = True

    # Схлопываем одинаковое: то же время + то же (или почти то же) название.
    #
    # Дубли берутся не из ошибки инструмента, а из данных. Проверено на
    # боевой базе дважды. Письмо «Налоги 08-2026» пришло на почту дважды,
    # стало двумя заметками, и в каждой распозналось одно и то же
    # событие. А 10.10 сводка пришла такой:
    #
    #   📌 11:00 Marsz Kejterka в Познани — 🐕 Marsz Kejterka уже в субботу
    #   📌 11:00 Марш Кейтерка в Познани  — 🐕 В Познани снова пройдёт Марш
    #
    # Один собачий марш двумя строками: poznan.pl написал о нём дважды,
    # разными статьями, одна заметка по-польски, другая по-русски.
    # Показывать обе честно, но человеку, спросившему «что впереди», это
    # шум — а шум и есть главный способ обесценить такой ответ.
    #
    # Сравнение по ВРЕМЕНИ СТРОГОЕ, по НАЗВАНИЮ — похожесть (event_dedup.py,
    # порог замерен). Строгое равенство названий не поймало бы случай выше,
    # а похожесть без равенства времени склеила бы фестиваль 12-го с
    # фестивалем 13-го — поэтому ровно так, а не иначе.
    unique: list[dict[str, Any]] = []
    for entry in entries:
        twin = next(
            (
                u
                for u in unique
                # Только однородное: у напоминания и распознанного события
                # разное назначение (первое закрывают через resolve, второе
                # убирают через dismiss), и склеивать их нельзя даже при
                # одинаковом названии.
                if u["kind"] == entry["kind"]
                and u["at"] == entry["at"]
                and same_event(u["title"], entry["title"])
            ),
            None,
        )
        if twin is None:
            unique.append(entry)
            continue
        # Про второй источник не умалчиваем: ассистент сможет сказать
        # «это одно и то же, в базе две заметки», а молчаливое
        # исчезновение заметки выглядело бы потерей.
        others = twin.setdefault("duplicate_sources", [])
        source = entry.get("source_note") or entry.get("title")
        if source and source not in others:
            others.append(source)

    return {
        "today": now_local_date(tz_name).isoformat(),
        "horizon_days": days,
        "entries": unique,
    }


async def handle(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    raw_days = args.get("days")
    try:
        days = int(raw_days) if raw_days is not None else DEFAULT_HORIZON_DAYS
    except (TypeError, ValueError):
        days = DEFAULT_HORIZON_DAYS
    return await collect_agenda(ctx.db, ctx.user_id, days=days, tz_name=ctx.client_timezone)
