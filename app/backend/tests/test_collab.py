import asyncio
import uuid

from app import collab


class _FakeWebSocket:
    def __init__(self) -> None:
        self.closed_with: int | None = None

    async def close(self, code: int) -> None:
        self.closed_with = code


async def test_invalidate_room_coalesces_rapid_calls(monkeypatch):
    # Реальный найденный риск: альбом из нескольких фото в Telegram (или
    # несколько вложений письма) — каждое завершается своим отдельным
    # vision/pdf_processing вызовом, и КАЖДЫЙ по завершении самостоятельно
    # зовёт invalidate_room для ОДНОЙ и той же заметки. Без схлопывания
    # клиент ловил бы разрыв за разрывом, пока ещё не успел переподключиться
    # после предыдущего — несколько invalidate_room подряд должны рвать
    # комнату РОВНО ОДИН раз, после того как поток вызовов утих.
    monkeypatch.setattr(collab, "_INVALIDATE_DEBOUNCE_SECONDS", 0.05)
    item_id = uuid.uuid4()
    ws = _FakeWebSocket()
    room, is_seeder = await collab.join_room(item_id, ws)
    assert is_seeder

    for _ in range(4):
        await collab.invalidate_room(item_id)
        await asyncio.sleep(0.01)  # короче debounce — каждый вызов должен отменять предыдущий таймер

    assert ws.closed_with is None  # ещё не должно было сработать
    assert item_id in collab._rooms  # комната ещё жива

    await asyncio.sleep(0.1)  # дольше debounce — теперь должно сработать ровно один раз

    assert ws.closed_with == collab.INVALIDATED_CLOSE_CODE
    assert item_id not in collab._rooms


async def test_invalidate_room_noop_for_unknown_item(monkeypatch):
    monkeypatch.setattr(collab, "_INVALIDATE_DEBOUNCE_SECONDS", 0.01)
    await collab.invalidate_room(uuid.uuid4())
    await asyncio.sleep(0.05)  # не должно упасть, даже если комнаты никогда не было
