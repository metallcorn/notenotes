"""Скилл отслеживания доставки (app/delivery.py + tools/track_delivery.py +
routers/delivery_widgets.py). Сеть перевозчиков не трогаем: identify —
чистая функция, а track мокаем, чтобы гейт не ходил в ShipX/Orlen/Poczta."""
import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app import delivery
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


# --- _poczta(): разбор реального ответа перевозчика --------------------------
# Реальный найденный баг: код ждал события в data["mailStatusesEx"] или
# data["events"] на верхнем уровне ответа — эта схема была угадана по
# JS-виджету и никогда не сверялась с настоящим ответом API. На деле
# события лежат в data["mailInfo"]["events"], так что events всегда
# получался пустым, и статус тихо скатывался на хардкод "W trakcie" —
# даже для уже доставленной посылки. Ответ ниже — реальный (снят
# 21.08.2026 на трек-номере 00559007730468902887), не выдуманный.
_POCZTA_REAL_RESPONSE = {
    "mailInfo": {
        "number": "00559007730468902887",
        "finished": True,
        "events": [
            {"code": "P_REJ_KN1", "name": "Przygotowana", "time": "2026-08-13T14:02:15",
             "state": {"code": "PRZ", "name": "PRZYGOTOWANA"}, "finished": False, "canceled": False},
            {"code": "P_NAD", "name": "Nadana", "time": "2026-08-13T15:10:50",
             "state": {"code": "NA", "name": "NADANA"}, "finished": False, "canceled": False},
            {"code": "P_WDML", "name": "W doręczeniu", "time": "2026-08-17T07:29:37",
             "state": {"code": "DOR", "name": "W DORĘCZENIU"}, "finished": False, "canceled": False},
            {"code": "P_D", "name": "Doręczona", "time": "2026-08-17T08:26:42",
             "state": {"code": "DO", "name": "DORĘCZONA"}, "finished": True, "canceled": False,
             "postOffice": {"name": "Placówka Pocztowa Poznań 2",
                             "description": {"street": "ul. Przykładowa", "houseNumber": "17",
                                              "zipCode": "60-001", "city": "Poznań",
                                              "openingHours": {
                                                  "businessDays": [{"from": "08:00:00", "to": "22:00:59"}],
                                                  "saturday": [{"from": "08:00:00", "to": "22:00:59"}],
                                              }}}},
        ],
    },
    "number": "00559007730468902887",
    "mailStatus": 0,
}


def _mock_poczta_client(response_json):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text='<html><div data-apikey="fake-key"></div></html>')
        return httpx.Response(200, json=response_json)

    original_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    return factory


async def test_poczta_parses_real_response_shape_and_reports_delivered(monkeypatch):
    monkeypatch.setattr(delivery.httpx, "AsyncClient", _mock_poczta_client(_POCZTA_REAL_RESPONSE))

    result = await delivery._poczta("00559007730468902887")
    assert result["live"] is True
    assert result["status_text"] == "Doręczona"
    # checkpoints — новые сверху (reversed относительно хронологии events)
    assert result["checkpoints"][0]["description"] == "Doręczona"
    assert result["checkpoints"][-1]["description"] == "Przygotowana"
    # Реальная жалоба: куда пришла посылка и режим работы отделения были
    # видны только по ссылке (или вообще нигде — параметр raw= в _result()
    # молча отбрасывался, модель их не видела) — теперь сразу в note.
    assert result["note"] == (
        "Placówka Pocztowa Poznań 2, ul. Przykładowa 17, 60-001 Poznań "
        "· режим работы: Пн–Пт 08:00–22:00, Сб 08:00–22:00"
    )


async def test_poczta_reports_no_data_when_no_events(monkeypatch):
    monkeypatch.setattr(
        delivery.httpx, "AsyncClient",
        _mock_poczta_client({"mailInfo": {"number": "x", "finished": False, "events": []}, "mailStatus": -1}),
    )

    result = await delivery._poczta("00000000000000000000000")
    assert result["status_text"] == "Brak danych o przesyłce"


# --- _inpost(): порядок чекпоинтов и адрес пачкомата -------------------------
# Реальный найденный баг: ShipX отдаёт tracking_details от НОВЫХ к СТАРЫМ, а
# код заворачивал их в reversed(), получая от старых к новым. Фронт берёт
# checkpoints[:5] в расчёте на "новые сверху" — итог: карточка показывала 5
# самых старых событий вместо последних, и last_event_time (= checkpoints[0])
# указывал на первое событие вместо доставки. Плюс адрес/размер/место
# пачкомата (реально есть в ответе, custom_attributes.*) не вытаскивались —
# модель один раз на реальном номере просто выдумала другой адрес, а другие
# поля (location_description, size) пользователь раньше видел только через
# сырой ответ (url_check напрямую по этому же API), в новой карточке их не
# было вообще.
_INPOST_REAL_RESPONSE = {
    "status": "delivered",
    "tracking_details": [
        {"datetime": "2026-08-16T16:30:38.000+02:00", "status": "delivered"},
        {"datetime": "2026-08-16T06:47:04.000+02:00", "status": "out_for_delivery"},
        {"datetime": "2026-08-14T11:28:47.000+02:00", "status": "confirmed"},
    ],
    "custom_attributes": {
        "size": "B",
        "target_machine_detail": {
            "name": "POZ00XX",
            "opening_hours": "PN-SB 09-22",
            "location_description": "w sklepie Sklep",
            "address": {"line1": "Przykładowa 5", "line2": "60-000 Poznań"},
        },
    },
}


def _mock_inpost_client(response_json):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json)

    original_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    return factory


async def test_inpost_keeps_newest_first_order_and_reports_real_address(monkeypatch):
    monkeypatch.setattr(delivery.httpx, "AsyncClient", _mock_inpost_client(_INPOST_REAL_RESPONSE))

    result = await delivery._inpost("600000000000000000000002")
    assert result["status_text"] == "Doręczono"
    # новые сверху — checkpoints[0] это доставка, а не первое событие
    assert result["checkpoints"][0]["description"] == "Doręczono"
    assert result["checkpoints"][-1]["description"] == "Zarejestrowano"
    assert result["last_event_time"] == "2026-08-16T16:30:38.000+02:00"
    assert result["note"] == (
        "Paczkomat POZ00XX (w sklepie Sklep), Przykładowa 5, 60-000 Poznań "
        "· размер B · режим работы: PN-SB 09-22"
    )


def test_identify_dpd_by_url():
    cid, _, ambiguous = identify("https://tracktrace.dpd.com.pl/parcelDetails?typ=1&p1=00340434")
    assert cid == "dpd" and ambiguous is False


def test_identify_explicit_carrier_overrides_detection():
    assert identify("00340434", carrier="dpd") == ("dpd", "00340434", False)


# --- Allegro Delivery: реальный найденный случай (AD00TESTPACK00001) --------


def test_identify_allegro_by_bare_number():
    cid, number, ambiguous = identify("AD00TESTPACK00001")
    assert cid == "allegro" and number == "AD00TESTPACK00001" and ambiguous is False


def test_identify_allegro_by_url():
    cid, number, ambiguous = identify(
        "https://allegro.pl/allegrodelivery/sledzenie-paczki?numer=AD00TESTPACK00001"
    )
    assert cid == "allegro" and number == "AD00TESTPACK00001" and ambiguous is False


def test_identify_plain_allegro_link_is_not_mistaken_for_delivery():
    # allegro.pl сам по себе ничто не говорит о посылке — обычная ссылка на
    # товар не должна распознаваться как трек allegro delivery.
    cid, _, ambiguous = identify("https://allegro.pl/oferta/jakis-towar-123456")
    assert cid is None and ambiguous is True


@pytest.mark.asyncio
async def test_allegro_returns_link_only_no_live_check():
    result = await delivery._allegro("AD00TESTPACK00001")
    assert result["carrier"] == "allegro"
    assert result["live"] is False
    assert result["tracking_url"] == (
        "https://allegro.pl/allegrodelivery/sledzenie-paczki?numer=AD00TESTPACK00001"
    )


def test_track_any_excludes_allegro_same_as_dpd():
    # allegro, как и dpd, не участвует в параллельном переборе track_any —
    # у него нет живой проверки, он не может подтвердить совпадение номера.
    assert delivery._NO_LIVE_CHECK == {"dpd", "allegro"}
    candidates = [cid for cid in delivery._FETCH if cid not in delivery._NO_LIVE_CHECK]
    assert "allegro" not in candidates
    assert "dpd" not in candidates


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
