import uuid
from collections import defaultdict

from fastapi import WebSocket

# Live-синк заметок/папок/диалогов между устройствами и участниками спейса
# (жалоба: правки с телефона не появлялись на ноуте без ручной перезагрузки).
# Тот же паттерн in-memory реестра, что уже есть для списков
# (app/routers/lists.py) — один backend-процесс, поэтому этого достаточно;
# если появится несколько воркеров, это единственное место под Redis pub/sub.
#
# В отличие от списков, здесь НЕ шлём точные диффы (items/folders слишком
# разнородны — заметка, папка, тег и т.д.), а лёгкий сигнал "kind изменился
# в этом спейсе". Клиент сам решает, что перезапросить (react-query
# invalidateQueries) — то же решение, что уже принято для инвалидации кэша
# после хода ассистента.
_connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)


async def notify_space(space_id: uuid.UUID, kind: str) -> None:
    dead = []
    for ws in _connections.get(space_id, set()):
        try:
            await ws.send_json({"kind": kind})
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections[space_id].discard(ws)


def register(space_id: uuid.UUID, ws: WebSocket) -> None:
    _connections[space_id].add(ws)


def unregister(space_id: uuid.UUID, ws: WebSocket) -> None:
    _connections[space_id].discard(ws)
