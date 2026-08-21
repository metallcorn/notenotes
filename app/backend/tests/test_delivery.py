"""Скилл отслеживания доставки (app/delivery.py + tools/track_delivery.py +
routers/delivery_widgets.py). Сеть перевозчиков не трогаем: identify —
чистая функция, а track мокаем, чтобы гейт не ходил в ShipX/Orlen/Poczta."""
import json
import uuid

import pytest
from sqlalchemy import select

from app.delivery import identify
from app.models import DeliveryWidget
from app.tools.registry import ToolContext
from app.tools.track_delivery import insert_delivery_block


# --- identify(): распознавание перевозчика ----------------------------------

def test_identify_inpost_by_bare_number():
    assert identify("600000000000000000000001") == ("inpost", "600000000000000000000001", False)


def test_identify_inpost_by_url():
    cid, number, ambiguous = identify("https://twoj.inpost.pl/pl/znajdz-przesylke?parcel=600000000000000000000001")
    assert (cid, number, ambiguous) == ("inpost", "600000000000000000000001", False)


def test_identify_orlen_by_url_and_by_short_number():
    assert identify("https://www.orlenpaczka.pl/sledz-paczke/?id=2000000000000") == ("orlen", "2000000000000", False)
    assert identify("1234567") == ("orlen", "1234567", False)


def test_identify_poczta_by_px_number():
    assert identify("PX00000000000000000000") == ("poczta", "PX00000000000000000000", False)


def test_identify_dpd_by_url():
    cid, _, ambiguous = identify("https://tracktrace.dpd.com.pl/parcelDetails?typ=1&p1=00340434")
    assert cid == "dpd" and ambiguous is False


def test_identify_explicit_carrier_overrides_detection():
    assert identify("00340434", carrier="dpd") == ("dpd", "00340434", False)


def test_identify_garbage_is_ambiguous():
    cid, _, ambiguous = identify("абракадабра")
    assert cid is None and ambiguous is True


# --- insert_delivery_block: постоянный виджет в заметке ----------------------

_FAKE_RESULT = {
    "carrier": "inpost",
    "carrier_label": "InPost (Paczkomaty / kurier)",
    "tracking_number": "600000000000000000000001",
    "live": True,
    "status_text": "Zarejestrowano",
    "last_event_time": "2026-08-21T09:42:13+02:00",
    "checkpoints": [{"time": "2026-08-21T09:42:13+02:00", "status": "confirmed", "description": "Zarejestrowano"}],
    "tracking_url": "https://inpost.pl/sledzenie-przesylek?number=600000000000000000000001",
    "note": "Paczkomat POZ00XX",
}


async def _make_note(auth_client):
    r = await auth_client.post("/api/spaces", json={"name": "Space"})
    space_id = r.json()["id"]
    r = await auth_client.post("/api/items", json={"space_id": space_id, "title": "T", "content": ""})
    return space_id, r.json()["id"]


async def test_insert_delivery_block_creates_widget_and_stores_only_id(
    auth_client, db_session, test_user, monkeypatch
):
    async def fake_track(number, carrier=None):
        return dict(_FAKE_RESULT, tracking_number=number)

    monkeypatch.setattr("app.tools.track_delivery.track", fake_track)

    space_id, item_id = await _make_note(auth_client)
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    out = await insert_delivery_block(
        ctx, {"item_id": item_id, "tracking_number": "600000000000000000000001", "carrier": "inpost"}
    )
    assert out["carrier"] == "inpost"

    widget = (
        await db_session.execute(select(DeliveryWidget).where(DeliveryWidget.item_id == uuid.UUID(item_id)))
    ).scalar_one()
    assert widget.carrier == "inpost"
    assert widget.tracking_number == "600000000000000000000001"
    assert json.loads(widget.last_result)["status_text"] == "Zarejestrowano"

    # в content — только непрозрачная ссылка на виджет, не сам статус
    r = await auth_client.get(f"/api/items/{item_id}")
    content = r.json()["content"]
    assert str(widget.id) in content
    assert "Zarejestrowano" not in content
    assert "Paczkomat" not in content


async def test_insert_delivery_block_need_carrier_creates_no_widget(auth_client, db_session, test_user):
    space_id, item_id = await _make_note(auth_client)
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    out = await insert_delivery_block(ctx, {"item_id": item_id, "tracking_number": "абракадабра"})
    assert out.get("need_carrier") is True

    rows = (
        await db_session.execute(select(DeliveryWidget).where(DeliveryWidget.item_id == uuid.UUID(item_id)))
    ).scalars().all()
    assert rows == []


# --- Роутер get/refresh + контроль доступа -----------------------------------

async def _make_widget(auth_client, db_session, test_user, monkeypatch):
    async def fake_track(number, carrier=None):
        return dict(_FAKE_RESULT, tracking_number=number)

    monkeypatch.setattr("app.tools.track_delivery.track", fake_track)
    space_id, item_id = await _make_note(auth_client)
    ctx = ToolContext(db=db_session, user_id=test_user.id, space_id=uuid.UUID(space_id))
    await insert_delivery_block(
        ctx, {"item_id": item_id, "tracking_number": "600000000000000000000001", "carrier": "inpost"}
    )
    r = await auth_client.get(f"/api/items/{item_id}")
    widget_id = r.json()["content"].split('data-delivery-id="')[1].split('"')[0]
    return item_id, widget_id


async def test_get_delivery_widget_returns_parsed_result(auth_client, db_session, test_user, monkeypatch):
    _, widget_id = await _make_widget(auth_client, db_session, test_user, monkeypatch)
    r = await auth_client.get(f"/api/delivery-widgets/{widget_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["carrier"] == "inpost"
    assert body["result"]["status_text"] == "Zarejestrowano"


async def test_refresh_delivery_widget_updates_status(auth_client, db_session, test_user, monkeypatch):
    _, widget_id = await _make_widget(auth_client, db_session, test_user, monkeypatch)

    async def fake_track_updated(number, carrier=None):
        return dict(_FAKE_RESULT, tracking_number=number, status_text="Doręczono")

    monkeypatch.setattr("app.routers.delivery_widgets.track_delivery", fake_track_updated)
    r = await auth_client.post(f"/api/delivery-widgets/{widget_id}/refresh")
    assert r.status_code == 200
    assert r.json()["result"]["status_text"] == "Doręczono"


async def test_foreign_user_cannot_access_delivery_widget(
    auth_client, _client_factory, db_session, test_user, monkeypatch
):
    _, widget_id = await _make_widget(auth_client, db_session, test_user, monkeypatch)

    from app.models import User
    from app.security import create_session_token, hash_password

    other = User(username="delivery_outsider", password_hash=hash_password("x"), name="Outsider")
    db_session.add(other)
    await db_session.flush()
    outsider = _client_factory()
    outsider.cookies.set("notenotes_session", create_session_token(other.id))

    r = await outsider.get(f"/api/delivery-widgets/{widget_id}")
    assert r.status_code == 404
