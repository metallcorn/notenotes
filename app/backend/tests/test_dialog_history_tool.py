"""get_compacted_history (app/tools/dialog_history.py) — реальный запрос
пользователя: если сводки после сжатия истории (dialog_compaction.py)
недостаточно точно для ответа, модель должна суметь сама прочитать
дословный оригинал сжатого куска, а не только откатывать сжатие целиком."""
import uuid

import pytest

from app.models import Item
from app.tools.dialog_history import get_compacted_history
from app.tools.registry import ToolContext, ToolError


async def _make_dialog_with_snapshot(auth_client, db_session):
    r = await auth_client.post("/api/spaces", json={"name": "History"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/dialogs", json={"space_id": space_id})
    dialog_id = r.json()["id"]

    item = await db_session.get(Item, uuid.UUID(dialog_id))
    snapshot_id = str(uuid.uuid4())
    replaced = [
        {"id": "m1", "role": "user", "content": "10.06 была тренировка ног"},
        {"id": "m2", "role": "assistant", "content": "Записал: приседания 80кг"},
    ]
    item.properties = {
        **item.properties,
        "compaction_snapshots": [
            {"id": snapshot_id, "created_at": "2026-08-25T00:00:00+00:00", "replaced_messages": replaced}
        ],
    }
    await db_session.commit()
    return space_id, dialog_id, snapshot_id


async def test_get_compacted_history_returns_verbatim_transcript(auth_client, db_session, test_user):
    space_id, dialog_id, snapshot_id = await _make_dialog_with_snapshot(auth_client, db_session)
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))

    out = await get_compacted_history(ctx, {"dialog_id": dialog_id, "snapshot_id": snapshot_id})

    assert "10.06 была тренировка ног" in out["transcript"]
    assert "приседания 80кг" in out["transcript"]


async def test_get_compacted_history_unknown_snapshot_raises(auth_client, db_session, test_user):
    space_id, dialog_id, _ = await _make_dialog_with_snapshot(auth_client, db_session)
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))

    with pytest.raises(ToolError):
        await get_compacted_history(ctx, {"dialog_id": dialog_id, "snapshot_id": str(uuid.uuid4())})


async def test_get_compacted_history_rejects_non_dialog_item(auth_client, db_session, test_user):
    r = await auth_client.post("/api/spaces", json={"name": "History2"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "Note", "content": "x"})
    item_id = r.json()["id"]
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))

    with pytest.raises(ToolError):
        await get_compacted_history(ctx, {"dialog_id": item_id, "snapshot_id": str(uuid.uuid4())})
