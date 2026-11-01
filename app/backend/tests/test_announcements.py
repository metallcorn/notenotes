"""Объявления участникам спейса (app/announcements.py, tools/announcements.py).

Просьба владельца 01.11: «ушёл из дома, вернусь к десяти» одной фразой —
всем в спейсе в Telegram, а след в журнале. Данные вымышленные: Jan
Kowalski и Anna.
"""

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import announcements
from app.models import Folder, Item, ItemVersion, Notification, User
from app.security import hash_password
from app.tools.announcements import announce, close_announcement, parse_until
from app.tools.registry import ToolContext, ToolError

TZ = "Europe/Warsaw"


async def _space(auth_client, name="Rodzina"):
    r = await auth_client.post("/api/spaces", json={"name": name})
    return uuid.UUID(r.json()["id"])


async def _member(db_session, auth_client, space_id, username="anna_k"):
    other = User(username=username, password_hash=hash_password("x"), name="Anna")
    db_session.add(other)
    await db_session.commit()
    r = await auth_client.post(f"/api/spaces/{space_id}/members", json={"username": username})
    assert r.status_code == 201, r.text
    return other


def _ctx(db_session, user, space_id):
    return ToolContext(db=db_session, user_id=user.id, space_id=space_id, client_timezone=TZ)


async def _notifications(db_session, item_id):
    rows = await db_session.execute(
        select(Notification).where(Notification.type == announcements.NOTIFICATION_TYPE, Notification.payload["item_id"].astext == str(item_id))
    )
    return list(rows.scalars().all())


async def test_announce_writes_journal_and_notifies_every_member(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    personal = await _space(auth_client, "Osobiste")
    ctx = _ctx(db_session, test_user, personal)

    result = await announce(ctx, {"text": "ушёл из дома, вернусь к десяти", "until": "23:59", "space": "w rodzinie", "details": "Ключи под ковриком.\nКот накормлен."})

    assert result["recipients"] == 2, "автор тоже получает — так проверяется доставка"
    assert result["space_name"] == "Rodzina"
    assert result["until"].endswith(("+01:00", "+02:00")) and "T23:59" in result["until"]
    item = await db_session.get(Item, uuid.UUID(result["journal_id"]))
    assert item.space_id == space_id and item.material_type == "note"
    assert item.title.startswith("Объявления · ")
    folder = await db_session.get(Folder, item.folder_id)
    assert folder.name == "Объявления" and folder.space_id == space_id
    assert item.content.startswith("- ") and "🚪 Test User: ушёл из дома, вернусь к десяти · до ~23:59" in item.content
    assert "  Ключи под ковриком.\n  Кот накормлен." in item.content
    events = item.properties["detected_events"]
    assert len(events) == 1 and events[0]["source"] == "announcements" and events[0]["title"].endswith("до ~23:59")

    sent = await _notifications(db_session, item.id)
    assert sorted(n.user_id for n in sent) == sorted([test_user.id, other.id])
    assert all(n.trigger_at is None and n.dispatched_at is None for n in sent), "немедленные: диспетчер подхватит на ближайшем проходе"
    assert sent[0].title == "🚪 Test User: ушёл из дома, вернусь к десяти"
    assert sent[0].body == "до ~23:59\nКлючи под ковриком.\nКот накормлен."
    assert sent[0].payload["entry_id"] == result["entry_id"]

    # Второе объявление в том же месяце — та же заметка, свежее сверху, версия в истории.
    # «текущий» — пользователь спейс не назвал, берётся спейс диалога.
    second = await announce(_ctx(db_session, test_user, space_id), {"text": "интернет отключат на час", "kind": "info", "space": "текущий"})
    assert second["journal_id"] == result["journal_id"]
    await db_session.refresh(item)
    assert len(item.properties["entries"]) == 2
    assert item.content.index("📣 Test User: интернет отключат") < item.content.index("🚪 Test User: ушёл")
    assert len(item.properties["detected_events"]) == 1, "без until в «Скоро» не попадает"
    versions = (await db_session.execute(select(ItemVersion).where(ItemVersion.item_id == item.id))).scalars().all()
    assert len(versions) == 2


async def test_close_marks_latest_open_and_notifies(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    ctx = _ctx(db_session, test_user, space_id)
    opened = await announce(ctx, {"text": "ушёл в магазин", "until": "23:58"})

    with pytest.raises(ToolError, match="Пустой text"):
        await close_announcement(ctx, {"text": " "})

    closed = await close_announcement(ctx, {"text": "дома"})
    assert closed["entry_id"] == opened["entry_id"]
    assert closed["closed_text"] == "дома" and closed["recipients"] == 2
    item = await db_session.get(Item, uuid.UUID(opened["journal_id"]))
    assert "· 🏠 " in item.content and item.content.rstrip().endswith("дома")
    assert "detected_events" not in item.properties, "закрытое из «Скоро» уходит"
    assert item.properties["entries"][0]["closed_at"]
    titles = [n.title for n in await _notifications(db_session, item.id)]
    assert titles.count("🏠 Test User: дома") == 2

    # Больше открытых нет.
    with pytest.raises(ToolError, match="Открытых объявлений нет"):
        await close_announcement(ctx, {"text": "дома"})

    # Чужое открытое объявление «я дома» не закрывает.
    await announce(_ctx(db_session, other, space_id), {"text": "ушла на работу"})
    with pytest.raises(ToolError, match="Открытых объявлений нет"):
        await close_announcement(ctx, {"text": "дома"})


async def test_close_in_two_spaces_asks_which(auth_client, db_session, test_user):
    family = await _space(auth_client, "Rodzina")
    band = await _space(auth_client, "Zespół")
    first = await announce(_ctx(db_session, test_user, family), {"text": "ушёл из дома"})
    second = await announce(_ctx(db_session, test_user, band), {"text": "еду на репетицию"})

    result = await close_announcement(_ctx(db_session, test_user, family), {"text": "на месте"})
    assert result["ambiguous"] is True
    assert [e["entry_id"] for e in result["open"]] == [second["entry_id"], first["entry_id"]], "свежие первыми"

    picked = await close_announcement(_ctx(db_session, test_user, family), {"text": "дома", "entry_id": first["entry_id"]})
    assert picked["entry_id"] == first["entry_id"]
    # Второе осталось открытым и теперь закрывается без уточнения.
    rest = await close_announcement(_ctx(db_session, test_user, family), {"text": "на месте"})
    assert rest["entry_id"] == second["entry_id"]


def test_parse_until_handles_clock_and_iso():
    tz = ZoneInfo(TZ)
    now = datetime(2026, 11, 1, 17, 40, tzinfo=tz).astimezone(timezone.utc)
    assert parse_until("22:00", TZ, now).astimezone(tz) == datetime(2026, 11, 1, 22, 0, tzinfo=tz)
    assert parse_until("9.30", TZ, now).astimezone(tz) == datetime(2026, 11, 2, 9, 30, tzinfo=tz), "прошедшее сегодня — завтра"
    assert parse_until("2026-11-03T09:00", TZ, now).astimezone(tz) == datetime(2026, 11, 3, 9, 0, tzinfo=tz)
    assert parse_until("", TZ, now) is None
    with pytest.raises(ToolError, match="Некорректное время"):
        parse_until("25:00", TZ, now)
    with pytest.raises(ToolError, match="Некорректное until"):
        parse_until("вечером", TZ, now)


async def test_announce_rejects_past_until_and_empty_text(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    ctx = _ctx(db_session, test_user, space_id)
    with pytest.raises(ToolError, match="Пустой text"):
        await announce(ctx, {"text": ""})
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(ToolError, match="уже прошло"):
        await announce(ctx, {"text": "ушёл", "until": past})


def test_render_puts_newest_first_and_labels_other_day():
    tz = ZoneInfo(TZ)
    day = datetime(2026, 11, 1, 17, 40, tzinfo=tz)
    entries = [
        {"id": "a", "author_name": "Jan", "kind": "away", "text": "ушёл", "details": "", "at": day.isoformat(),
         "until": (day + timedelta(days=2)).isoformat(), "closed_at": None, "closed_text": None},
        {"id": "b", "author_name": "Anna", "kind": "info", "text": "реп в 10", "details": "", "at": (day + timedelta(hours=1)).isoformat(),
         "until": None, "closed_at": (day + timedelta(hours=3)).isoformat(), "closed_text": "закончили"},
    ]
    assert announcements.render(entries, tz) == (
        "- 01.11 18:40 📣 Anna: реп в 10 · 🏠 20:40 закончили\n"
        "- 01.11 17:40 🚪 Jan: ушёл · до ~03.11 17:40\n"
    )
