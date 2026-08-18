async def test_event_ics_requires_auth(client):
    r = await client.get("/api/calendar/event.ics", params={"title": "T", "start": "2026-01-01T10:00:00", "end": "2026-01-01T11:00:00"})
    assert r.status_code == 401


async def test_event_ics_generated(auth_client):
    r = await auth_client.get(
        "/api/calendar/event.ics",
        params={
            "title": "Встреча; важная, срочно",
            "start": "2026-01-01T10:00:00",
            "end": "2026-01-01T11:00:00",
            "location": "Офис",
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    body = r.text
    assert "BEGIN:VCALENDAR" in body
    assert "SUMMARY:Встреча\\; важная\\, срочно" in body
    assert "DTSTART:20260101T100000" in body


async def test_event_ics_all_day(auth_client):
    r = await auth_client.get(
        "/api/calendar/event.ics",
        params={"title": "T", "start": "2026-01-01", "end": "2026-01-02", "all_day": "true"},
    )
    assert r.status_code == 200
    assert "DTSTART;VALUE=DATE:20260101" in r.text
