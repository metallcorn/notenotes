import json
import time

import pytest

from app.core.config import get_settings
from app.telegram_miniapp import InitDataError, sign_init_data, verify_init_data

TOKEN = "123456:TEST-TOKEN-fake"


def _init_data(user_id: int = 123456789, auth_date: int | None = None, token: str = TOKEN) -> str:
    return sign_init_data(
        {
            "auth_date": str(auth_date or int(time.time())),
            "query_id": "AAEtest",
            "user": json.dumps({"id": user_id, "first_name": "Jan", "username": "jan_kowalski"}),
        },
        token,
    )


def test_verify_ok():
    fields = verify_init_data(_init_data(), TOKEN)
    assert fields["user"]["id"] == 123456789
    assert fields["user"]["username"] == "jan_kowalski"


def test_verify_rejects_wrong_token():
    with pytest.raises(InitDataError):
        verify_init_data(_init_data(token="999:OTHER"), TOKEN)


def test_verify_rejects_tampered_user():
    data = _init_data().replace("jan_kowalski", "someone_else")
    with pytest.raises(InitDataError):
        verify_init_data(data, TOKEN)


def test_verify_rejects_stale():
    with pytest.raises(InitDataError):
        verify_init_data(_init_data(auth_date=int(time.time()) - 3 * 24 * 3600), TOKEN)


def test_verify_requires_hash_and_token():
    with pytest.raises(InitDataError):
        verify_init_data("auth_date=1&user=%7B%7D", TOKEN)
    with pytest.raises(InitDataError):
        verify_init_data(_init_data(), "")


async def test_miniapp_login_sets_session(client, auth_client, db_session, test_user, monkeypatch):
    from app.models import Space, SpaceMember, TelegramLink

    monkeypatch.setattr(get_settings(), "telegram_bot_token", TOKEN)
    space = Space(name="Telegram", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(TelegramLink(user_id=test_user.id, chat_id=123456789, space_id=space.id))
    await db_session.commit()

    # Незалогиненный клиент: подписанный initData привязанного пользователя
    # даёт сессию, дальше /me отвечает как после обычного входа.
    r = await client.post("/api/auth/telegram-miniapp", json={"init_data": _init_data()})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == test_user.username
    r = await client.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["username"] == test_user.username


async def test_miniapp_login_unlinked_and_forged(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_bot_token", TOKEN)
    # Telegram-пользователь без привязки — 403 с понятным текстом.
    r = await client.post("/api/auth/telegram-miniapp", json={"init_data": _init_data(user_id=42)})
    assert r.status_code == 403
    assert "привяз" in r.json()["detail"].lower()
    # Подделка — 401.
    r = await client.post("/api/auth/telegram-miniapp", json={"init_data": _init_data(token="999:OTHER")})
    assert r.status_code == 401
