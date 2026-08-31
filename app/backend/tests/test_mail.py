async def test_status_no_address_by_default(auth_client):
    r = await auth_client.get("/api/mail/status")
    assert r.status_code == 200 and r.json() == {"address": None, "own_addresses": []}


async def test_generate_creates_inbox_and_space(auth_client, db_session, test_user):
    from sqlalchemy import select
    from app.models import EmailInbox, Space

    r = await auth_client.post("/api/mail/generate")
    assert r.status_code == 200
    address = r.json()["address"]
    assert address is not None
    local_part = address.split("@", 1)[0]
    assert local_part.count("-") == 2  # три слова через дефис, набираемо по памяти

    inbox = await db_session.get(EmailInbox, test_user.id)
    assert inbox is not None
    assert address == f"{inbox.local_part}@{address.split('@', 1)[1]}"

    space = (await db_session.execute(select(Space).where(Space.id == inbox.space_id))).scalar_one()
    assert space.name == "Почта"
    assert space.owner_id == test_user.id


async def test_generate_is_idempotent(auth_client):
    r1 = await auth_client.post("/api/mail/generate")
    r2 = await auth_client.post("/api/mail/generate")
    assert r1.json()["address"] == r2.json()["address"]


async def test_regenerate_changes_address(auth_client):
    first = (await auth_client.post("/api/mail/generate")).json()["address"]
    second = (await auth_client.post("/api/mail/regenerate")).json()["address"]
    assert first != second


async def test_regenerate_without_inbox_is_noop(auth_client):
    r = await auth_client.post("/api/mail/regenerate")
    assert r.status_code == 200 and r.json() == {"address": None}


async def test_disable_removes_inbox_but_keeps_notes(auth_client, db_session, test_user):
    from app.models import EmailInbox
    from app.routers.items import create_item_row

    await auth_client.post("/api/mail/generate")
    inbox = await db_session.get(EmailInbox, test_user.id)
    space_id = inbox.space_id

    item = await create_item_row(
        db_session, space_id=space_id, author_id=test_user.id, material_type="note", title="t", content="c"
    )

    r = await auth_client.delete("/api/mail/inbox")
    assert r.status_code == 200 and r.json() == {"address": None}
    assert await db_session.get(EmailInbox, test_user.id) is None

    r = await auth_client.get(f"/api/items/{item.id}")
    assert r.status_code == 200 and r.json()["title"] == "t"


# --- own-addresses: реальная жалоба "пересылаю себе письмо — папка по мне" ---

async def test_add_own_address_without_inbox_returns_404(auth_client):
    r = await auth_client.post("/api/mail/own-addresses", json={"email": "me@gmail.com"})
    assert r.status_code == 404


async def test_add_own_address_rejects_invalid_email(auth_client):
    await auth_client.post("/api/mail/generate")
    r = await auth_client.post("/api/mail/own-addresses", json={"email": "not-an-email"})
    assert r.status_code == 400


async def test_add_own_address_normalizes_and_lists_in_status(auth_client):
    await auth_client.post("/api/mail/generate")
    r = await auth_client.post("/api/mail/own-addresses", json={"email": "Me@Gmail.com"})
    assert r.status_code == 200
    assert r.json()["own_addresses"] == ["me@gmail.com"]

    r = await auth_client.get("/api/mail/status")
    assert r.json()["own_addresses"] == ["me@gmail.com"]


async def test_add_own_address_does_not_duplicate(auth_client):
    await auth_client.post("/api/mail/generate")
    await auth_client.post("/api/mail/own-addresses", json={"email": "me@gmail.com"})
    r = await auth_client.post("/api/mail/own-addresses", json={"email": "me@gmail.com"})
    assert r.json()["own_addresses"] == ["me@gmail.com"]


async def test_remove_own_address(auth_client):
    await auth_client.post("/api/mail/generate")
    await auth_client.post("/api/mail/own-addresses", json={"email": "me@gmail.com"})
    r = await auth_client.delete("/api/mail/own-addresses/me@gmail.com")
    assert r.status_code == 200
    assert r.json()["own_addresses"] == []


async def test_remove_own_address_without_inbox_returns_404(auth_client):
    r = await auth_client.delete("/api/mail/own-addresses/me@gmail.com")
    assert r.status_code == 404
