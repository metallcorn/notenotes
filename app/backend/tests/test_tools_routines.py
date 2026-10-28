"""Инструменты ассистента для рутин (tools/routines.py).

Живой случай 28.10: через MCP попросили завести рутину по таблеткам кота,
а инструмента не было — ассистент предложил повторяющиеся напоминания.
Все данные вымышленные: Jan Kowalski и кот Burek.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Item, Notification, SpaceMember, User
from app.routine_schedule import STATUS_DONE, STATUS_PENDING, STATUS_SKIPPED
from app.security import hash_password
from app.tools.registry import ToolContext, ToolError, dispatch, get_tool_definitions
from app.tools.routines import create_routine, list_routines, mark_dose, update_routine


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


def _ctx(db_session, test_user, space_id, tz="Europe/Warsaw"):
    return ToolContext(db=db_session, user_id=test_user.id, space_id=space_id, client_timezone=tz)


async def _pings(db_session, routine_id):
    rows = await db_session.execute(select(Notification).where(Notification.payload["item_id"].astext == str(routine_id)))
    return list(rows.scalars().all())


async def test_create_by_times_pings_every_member(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    ctx = _ctx(db_session, test_user, space_id)

    result = await create_routine(
        ctx,
        {"title": "Tabletka dla Burka", "subject": "Burek", "dose": "pół tabletki", "times": ["08:00", "20:00"], "min_gap_minutes": 600},
    )

    assert result["schedule"] == "в 08:00 и 20:00"
    assert result["status"] == "активна"
    assert result["recipients"] == 2
    assert result["next_at"] and result["next_at"].endswith(("+01:00", "+02:00"))
    assert result["pending_dose_id"]
    item = await db_session.get(Item, uuid.UUID(result["id"]))
    assert item.material_type == "routine" and item.space_id == space_id
    assert item.properties["schedule"] == {"mode": "times", "times": ["08:00", "20:00"], "min_gap_minutes": 600, "every_minutes": None, "first_at": None}
    assert item.properties["timezone"] == "Europe/Warsaw"
    assert {n.user_id for n in await _pings(db_session, item.id)} == {test_user.id, other.id}


async def test_create_by_interval_in_named_space_and_folder(auth_client, db_session, test_user):
    home = await _space(auth_client, "Osobiste")
    family = await _space(auth_client, "Rodzinny")
    r = await auth_client.post("/api/folders", json={"space_id": str(family), "name": "kot"})
    folder_id = r.json()["id"]
    ctx = _ctx(db_session, test_user, home)

    result = await create_routine(
        ctx,
        {"title": "Krople", "every_minutes": 1440, "first_at": "21:00", "space": "w rodzinnym", "folder_id": folder_id, "notify": "self", "ends_on": "2099-01-01"},
    )

    assert result["schedule"] == "каждый день"
    assert result["space_name"] == "Rodzinny"
    assert result["course"] == "с … по 2099-01-01"
    assert result["notify"] == "только автору"
    item = await db_session.get(Item, uuid.UUID(result["id"]))
    assert item.space_id == family and str(item.folder_id) == folder_id
    assert item.properties["schedule"]["mode"] == "interval"


@pytest.mark.parametrize(
    "args, fragment",
    [
        ({"title": "x"}, "расписание"),
        ({"title": "x", "times": ["25:00"]}, "ЧЧ:ММ"),
        ({"title": "x", "times": ["08:00"], "every_minutes": 60}, "не оба"),
        ({"title": "x", "every_minutes": 60, "min_gap_minutes": 10}, "только для расписания по часам"),
        ({"title": "x", "times": ["08:00"], "starts_on": "2026-11-10", "ends_on": "2026-11-01"}, "раньше начала"),
        ({"title": "", "times": ["08:00"]}, "title"),
    ],
)
async def test_create_validation_is_a_tool_error(auth_client, db_session, test_user, args, fragment):
    space_id = await _space(auth_client)
    with pytest.raises(ToolError) as exc:
        await create_routine(_ctx(db_session, test_user, space_id), args)
    assert fragment.lower() in str(exc.value).lower()


async def test_list_mark_done_and_skip(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    other = await _member(db_session, auth_client, space_id)
    ctx = _ctx(db_session, test_user, space_id)
    created = await create_routine(ctx, {"title": "Tabletka dla Burka", "subject": "Burek", "times": ["08:00", "20:00"]})

    listed = await list_routines(ctx, {})
    assert [r["id"] for r in listed["routines"]] == [created["id"]]
    assert listed["routines"][0]["space_name"] == "Rodzina"
    assert "last_done" not in listed["routines"][0]

    half_hour_ago = (datetime.now(timezone.utc) - timedelta(minutes=30)).astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    done = await mark_dose(ctx, {"routine_id": created["id"], "at": half_hour_ago})
    assert done["dose"]["status"] == STATUS_DONE
    assert done["next_at"]
    item = await db_session.get(Item, uuid.UUID(created["id"]))
    doses = item.properties["doses"]
    assert doses[0]["status"] == STATUS_DONE and doses[0]["done_by"] == str(test_user.id)
    assert doses[-1]["status"] == STATUS_PENDING
    # Пинги первого приёма закрыты у всех, второго — заведены всем.
    pings = await _pings(db_session, item.id)
    assert all(n.resolved_at is not None for n in pings if n.payload["dose_id"] == doses[0]["id"])
    assert {n.user_id for n in pings if n.payload["dose_id"] == doses[-1]["id"]} == {test_user.id, other.id}

    skipped = await mark_dose(ctx, {"routine_id": created["id"], "action": "skip"})
    assert skipped["dose"]["status"] == STATUS_SKIPPED
    listed = await list_routines(ctx, {})
    assert listed["routines"][0]["stats"] == {"done": 1, "late": 0, "missed": 0, "skipped": 1}
    assert listed["routines"][0]["last_done"]["by"] == test_user.name


async def test_mark_dose_errors(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    ctx = _ctx(db_session, test_user, space_id)
    with pytest.raises(ToolError, match="list_routines"):
        await mark_dose(ctx, {"routine_id": "Tabletka"})
    with pytest.raises(ToolError, match="list_routines"):
        await mark_dose(ctx, {"routine_id": str(uuid.uuid4())})
    created = await create_routine(ctx, {"title": "Krople", "times": ["08:00"]})
    with pytest.raises(ToolError, match="done или skip"):
        await mark_dose(ctx, {"routine_id": created["id"], "action": "later"})
    with pytest.raises(ToolError, match="будущем"):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        await mark_dose(ctx, {"routine_id": created["id"], "at": future})


async def test_update_pause_schedule_and_course(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    ctx = _ctx(db_session, test_user, space_id)
    created = await create_routine(ctx, {"title": "Krople", "times": ["08:00"], "dose": "1 kropla"})

    paused = await update_routine(ctx, {"routine_id": created["id"], "paused": True})
    assert paused["status"] == "на паузе" and paused["next_at"] is None
    assert all(n.resolved_at is not None for n in await _pings(db_session, uuid.UUID(created["id"])))
    with pytest.raises(ToolError, match="нет открытого приёма"):
        await mark_dose(ctx, {"routine_id": created["id"]})

    resumed = await update_routine(ctx, {"routine_id": created["id"], "paused": False, "times": ["09:00", "21:00"], "dose": "2 krople"})
    assert resumed["status"] == "активна" and resumed["schedule"] == "в 09:00 и 21:00" and resumed["dose"] == "2 krople"
    assert resumed["next_at"] is not None

    item = await db_session.get(Item, uuid.UUID(created["id"]))
    assert item.properties["schedule"]["mode"] == "times"
    # ends_on в прошлом — курс закончен, из обычного списка уходит.
    finished = await update_routine(ctx, {"routine_id": created["id"], "ends_on": "2020-01-01"})
    assert finished["status"] == "курс закончен"
    assert (await list_routines(ctx, {}))["routines"] == []
    assert len((await list_routines(ctx, {"include_finished": True}))["routines"]) == 1

    with pytest.raises(ToolError, match="Нечего менять"):
        await update_routine(ctx, {"routine_id": created["id"]})


async def test_other_users_routines_are_invisible(auth_client, db_session, test_user):
    space_id = await _space(auth_client)
    ctx = _ctx(db_session, test_user, space_id)
    created = await create_routine(ctx, {"title": "Krople", "times": ["08:00"]})

    stranger = User(username="obcy", password_hash=hash_password("x"), name="Obcy")
    db_session.add(stranger)
    await db_session.commit()
    r = await auth_client.post("/api/spaces", json={"name": "Cudzy"})
    foreign = uuid.UUID(r.json()["id"])
    db_session.add(SpaceMember(space_id=foreign, user_id=stranger.id))
    await db_session.commit()
    their_ctx = ToolContext(db=db_session, user_id=stranger.id, space_id=foreign)

    assert (await list_routines(their_ctx, {}))["routines"] == []
    with pytest.raises(ToolError, match="не найдена"):
        await mark_dose(their_ctx, {"routine_id": created["id"]})
    with pytest.raises(ToolError, match="не найдена"):
        await update_routine(their_ctx, {"routine_id": created["id"], "paused": True})


async def test_registered_and_toggleable_as_one_skill(auth_client, db_session, test_user):
    names = {d.name for d in get_tool_definitions()}
    assert {"create_routine", "list_routines", "mark_dose", "update_routine"} <= names
    # Один тумблер «Рутины» выключает все четыре.
    assert not ({"create_routine", "list_routines", "mark_dose", "update_routine"} & {d.name for d in get_tool_definitions({"routines"})})
    space_id = await _space(auth_client)
    result = await dispatch("list_routines", _ctx(db_session, test_user, space_id), {}, disabled={"routines"})
    assert "отключён" in result["error"]
    # get_note на рутине подсказывает нужные инструменты, а не молчит.
    created = await create_routine(_ctx(db_session, test_user, space_id), {"title": "Krople", "times": ["08:00"]})
    result = await dispatch("get_note", _ctx(db_session, test_user, space_id), {"item_id": created["id"]})
    assert "list_routines" in result["error"]


async def test_mcp_exposes_routines_and_instructions(client, db_session, test_user):
    from tests.test_mcp import _issue_token, _make_space

    await _make_space(db_session, test_user, "Личное")
    await _issue_token(db_session, test_user)
    headers = {"MCP-Protocol-Version": "2025-06-18", "Authorization": "Bearer nn_testtoken"}
    r = await client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, headers=headers)
    assert "create_routine" in r.json()["result"]["instructions"]
    r = await client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"create_routine", "list_routines", "mark_dose", "update_routine"} <= names
    r = await client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "create_routine", "arguments": {"title": "Tabletka dla Burka", "times": ["08:00", "20:00"]}}},
        headers=headers,
    )
    assert r.json()["result"]["isError"] is False, r.text
    item = (await db_session.execute(select(Item).where(Item.title == "Tabletka dla Burka"))).scalar_one()
    assert item.material_type == "routine"
