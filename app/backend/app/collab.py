"""Реле совместного редактирования заметок (Yjs) — комната = одна заметка.

Сервер не пытается понять СТРУКТУРУ документа (какой у клиента shared-type,
ProseMirror-схему и т.п.) — он держит y_py.YDoc как чёрный ящик и релеит
между подключёнными клиентами бинарные Yjs-апдейты (apply_update/
encode_state_as_update из y_py — та же CRDT-логика, что у JS-клиента,
другие биндинги того же алгоритма). Комната существует только в памяти,
только пока есть хотя бы один подключённый клиент — реальная сохранность
контента идёт отдельным, уже существующим путём (ItemVersion/PATCH
/api/items, см. NoteEditor.tsx), сюда никак не завязана.

Протокол — свой, не y-websocket (сознательно: у нас свой сервер и свой
seeding-хендшейк, проще написать маленький клиент под свой протокол, чем
подгонять npm-пакет y-websocket под чужой сервер). Один байт типа в начале
каждого WS-бинарного фрейма:
  MSG_UPDATE        — CRDT-апдейт (encode_state_as_update/apply_update).
  MSG_AWARENESS     — присутствие/курсоры (y-protocols/awareness на
                       клиенте) — непрозрачные для сервера байты, просто
                       релеятся.
  MSG_SEED_REQUEST  — сервер → первому клиенту совсем свежей комнаты:
                       "комната пуста, наполни её текущим content заметки".
  MSG_SEED_COMPLETE — клиент → сервер: "наполнять нечем, заметка пуста" —
                       чтобы не держать остальных подключившихся в ожидании.

Гонка при одновременном первом открытии исключена структурно: seed_claimed
выставляется атомарно под _rooms_lock, так что "сеятелем" может стать
только самый первый клиент за всю жизнь комнаты, ровно один раз.
"""
import asyncio
import uuid

import y_py as Y
from fastapi import WebSocket

MSG_UPDATE = 1
MSG_AWARENESS = 2
MSG_SEED_REQUEST = 3
MSG_SEED_COMPLETE = 4
MSG_PING = 5
MSG_PONG = 6

# Реальный найденный баг: у канала не было проверки "жив ли клиент" —
# receive_bytes() в collab_ws.py ждал вечно. Если сеть у клиента отмирала
# молча (ноутбук уснул, недружелюбный NAT/файрвол закрыл простаивающее
# соединение без FIN), ни сервер, ни браузер не замечали разрыва: клиент
# годами показывал "подключено", хотя реальные апдейты от других
# участников до него не доходили (send_bytes на мёртвый TCP-сокет обычно
# не бросает исключение сразу — молча копится в буфере ОС). Уже готовый
# код переподключения на фронте (collabStatus === "disconnected" в
# NoteEditor.tsx) от этого никогда не срабатывал — onclose у мёртвого,
# но не закрытого явно сокета браузер тоже не звал. Heartbeat здесь и
# ответ на MSG_PING в collabProvider.ts дают серверу способ самому
# обнаружить и закрыть молчащего клиента.
HEARTBEAT_INTERVAL_SECONDS = 20.0
MAX_MISSED_HEARTBEATS = 2

# Сеятель мог закрыть вкладку до того, как прислал что-то (или решил, что
# наполнять нечем, но так и не отправил MSG_SEED_COMPLETE) — не держим
# остальных подключившихся вечно.
_SEED_TIMEOUT_SECONDS = 10.0


class CollabRoom:
    def __init__(self) -> None:
        self.doc = Y.YDoc()
        self.clients: set[WebSocket] = set()
        self.seed_claimed = False
        self.seed_done = asyncio.Event()


_rooms: dict[uuid.UUID, CollabRoom] = {}
_rooms_lock = asyncio.Lock()

# Реальный найденный риск (не гипотетический — уже происходит в проде):
# альбом из нескольких фото в Telegram создаёт ОДНУ заметку, но каждое фото
# распознаётся своим отдельным vision-вызовом и по завершении САМОСТОЯТЕЛЬНО
# зовёт invalidate_room — если у заметки открыта живая комната, она рвётся
# несколько раз подряд за секунды. Каждый разрыв сам по себе безопасен
# (клиент переподключается со свежим content), но клиент реконнектится
# асинхронно (сначала GET, потом WS) — второй разрыв, прилетевший ПОКА
# первый реконнект ещё в процессе, ловит переходное состояние. Схлопываем
# несколько invalidate_room подряд за это окно в ОДИН реальный разрыв уже
# ПОСЛЕ того, как поток завершений выдохся — тому же принципу, что и
# debounce автосейва на фронте, только для обратного потока.
_INVALIDATE_DEBOUNCE_SECONDS = 2.0
_pending_invalidations: dict[uuid.UUID, asyncio.Task] = {}


async def join_room(item_id: uuid.UUID, websocket: WebSocket) -> tuple[CollabRoom, bool]:
    """Регистрирует клиента в комнате заметки, создавая её при первом
    подключении. Возвращает (комната, ты_сеятель)."""
    async with _rooms_lock:
        room = _rooms.get(item_id)
        if room is None:
            room = CollabRoom()
            _rooms[item_id] = room
        room.clients.add(websocket)
        is_seeder = not room.seed_claimed
        if is_seeder:
            room.seed_claimed = True
    return room, is_seeder


async def leave_room(item_id: uuid.UUID, room: CollabRoom, websocket: WebSocket) -> None:
    async with _rooms_lock:
        room.clients.discard(websocket)
        # Комната эфемерна: последний ушёл — состояние выбрасывается, не
        # сохраняется никуда (см. докстринг модуля).
        if not room.clients and _rooms.get(item_id) is room:
            del _rooms[item_id]


# Код закрытия, которым сервер разрывает соединение сам (не клиент) —
# клиент должен отличить это от обрыва связи и переподключиться заново,
# а не просто показать "нет связи" (см. collabProvider.ts).
INVALIDATED_CLOSE_CODE = 4409


async def invalidate_room(item_id: uuid.UUID) -> None:
    """Реальный найденный баг: фоновые воркеры (vision.py/pdf_processing.py/
    tickets.py) меняют item.content НАПРЯМУЮ в БД, в обход Yjs целиком —
    если в этот момент у заметки открыта живая комната, её Y.Doc ничего не
    узнаёт об этом изменении: результат распознавания не появляется на
    экране, а следующее же локальное сохранение (автосейв из устаревшего
    Yjs-состояния) молча ЗАТЁРЛО БЫ готовый результат обратно плейсхолдером.
    Единственный безопасный вариант без обучения бэкенда понимать
    ProseMirror-структуру документа (сознательный принцип этого модуля,
    см. докстринг) — разорвать комнату целиком: все подключённые клиенты
    переподключатся заново и пройдут посев с УЖЕ обновлённым content.

    Не рвёт немедленно — см. _pending_invalidations выше: несколько вызовов
    подряд для ОДНОЙ заметки (типичный случай — альбом из нескольких фото)
    схлопываются в один реальный разрыв после того, как поток утих."""
    existing = _pending_invalidations.get(item_id)
    if existing is not None and not existing.done():
        existing.cancel()
    _pending_invalidations[item_id] = asyncio.create_task(_invalidate_after_debounce(item_id))


async def _invalidate_after_debounce(item_id: uuid.UUID) -> None:
    try:
        await asyncio.sleep(_INVALIDATE_DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return
    _pending_invalidations.pop(item_id, None)
    async with _rooms_lock:
        room = _rooms.pop(item_id, None)
    if room is None:
        return
    for ws in list(room.clients):
        try:
            await ws.close(code=INVALIDATED_CLOSE_CODE)
        except Exception:
            pass


async def wait_for_seed(room: CollabRoom) -> None:
    if room.seed_done.is_set():
        return
    try:
        await asyncio.wait_for(room.seed_done.wait(), timeout=_SEED_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        room.seed_done.set()


async def handle_message(room: CollabRoom, sender: WebSocket, data: bytes) -> None:
    if not data:
        return
    msg_type, payload = data[0], data[1:]

    if msg_type == MSG_UPDATE:
        try:
            Y.apply_update(room.doc, payload)
        except Exception:
            # Битый/чужеродный апдейт от одного клиента не должен ронять
            # комнату остальным — просто игнорируем это сообщение.
            return
        if not room.seed_done.is_set():
            room.seed_done.set()
        await _broadcast(room, sender, bytes([MSG_UPDATE]) + payload)

    elif msg_type == MSG_AWARENESS:
        await _broadcast(room, sender, data)

    elif msg_type == MSG_SEED_COMPLETE:
        room.seed_done.set()

    elif msg_type == MSG_PONG:
        # Не требует действий — само получение ЛЮБОГО сообщения (в т.ч.
        # этого) уже сбрасывает таймаут ожидания в collab_ws.py.
        return


async def _broadcast(room: CollabRoom, sender: WebSocket, raw: bytes) -> None:
    dead = []
    for ws in room.clients:
        if ws is sender:
            continue
        try:
            await ws.send_bytes(raw)
        except Exception:
            dead.append(ws)
    for ws in dead:
        room.clients.discard(ws)
