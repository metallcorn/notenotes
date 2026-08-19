import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Notification, SpaceMember, User
from app.security import hash_password
from app.tools.registry import ToolContext
from app.tools.reminders import create_reminder


async def test_create_reminder_on_shared_item_notifies_all_members(auth_client, db_session, test_user):
    # Тот же fan-out, что уже покрыт для REST-эндпоинта
    # (test_notifications.py) — здесь для пути ассистента (tools/reminders.py),
    # который использует отдельный код.
    other = User(username="tool_remind_other", password_hash=hash_password("x"), name="Other")
    db_session.add(other)
    await db_session.flush()

    r = await auth_client.post("/api/spaces", json={"name": "Shared tool space"})
    space_id = uuid.UUID(r.json()["id"])
    db_session.add(SpaceMember(space_id=space_id, user_id=other.id))
    await db_session.flush()

    r = await auth_client.post("/api/items", json={"space_id": str(space_id), "title": "T", "content": "x"})
    item_id = r.json()["id"]

    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=space_id)
    trigger_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    result = await create_reminder(ctx, {"title": "Общее", "trigger_at": trigger_at, "item_id": item_id})

    notifications = (
        await db_session.execute(select(Notification).where(Notification.title == "Общее"))
    ).scalars().all()
    recipient_ids = {n.user_id for n in notifications}
    assert recipient_ids == {test_user.id, other.id}
    assert result["id"] in [str(n.id) for n in notifications if n.user_id == test_user.id]


async def test_create_reminder_without_item_stays_private(auth_client, db_session, test_user):
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.uuid4())
    trigger_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await create_reminder(ctx, {"title": "Личное дело", "trigger_at": trigger_at})

    notifications = (
        await db_session.execute(select(Notification).where(Notification.title == "Личное дело"))
    ).scalars().all()
    assert len(notifications) == 1
    assert notifications[0].user_id == test_user.id
