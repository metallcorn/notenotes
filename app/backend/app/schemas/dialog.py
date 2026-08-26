import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DialogCreate(BaseModel):
    # Не обязателен: ассистент не привязан к одному спейсу с точки зрения
    # пользователя, без явного space_id бэкенд сам выбирает "домашний" спейс
    # (см. _default_space_id в routers/dialogs.py). Остаётся опцией на
    # будущее — например, если когда-нибудь понадобится явно "создать
    # диалог именно в спейсе X".
    space_id: uuid.UUID | None = None
    title: str = ""
    # Мини-чат "спроси ассистента прямо в заметке" (NoteAssistantModal.tsx) —
    # диалог привязан к конкретной заметке: ассистент видит её содержимое
    # без пересказа пользователем, тулы ограничены только чтением/поиском
    # (см. _SCOPED_TOOL_NAMES в routers/dialogs.py — не должен уметь менять
    # ДРУГИЕ заметки/списки), а сам диалог не показывается в общем списке
    # (list_dialogs) — это утилитарный скретч-чат, не полноценный разговор.
    scoped_item_id: uuid.UUID | None = None
    # Реальная жалоба: если пользователь выделил КУСОК заметки (не весь
    # текст), ассистент всё равно видел заметку целиком — непонятно, на чём
    # именно он должен сфокусироваться, "может я мало выделил или много".
    # Сохраняется рядом с scoped_item_id, используется только вместе с ним.
    selection: str = ""
    # Тот же приём, что scoped_item_id, но на уровне ПАПКИ — "обсудить с
    # ассистентом" все заметки одной темы разом (пример: папка "Авто"), без
    # затягивания контекста из остального пространства. Контекст строится
    # из содержимого заметок папки (превью, не полный текст — их несколько),
    # тулсет так же сужен до _SCOPED_TOOL_NAMES. Взаимоисключим со
    # scoped_item_id по построению (форма создаёт диалог одним способом).
    scoped_folder_id: uuid.UUID | None = None


class MessageCreate(BaseModel):
    content: str


class DialogCompactCreate(BaseModel):
    # None -> app.dialog_compaction._DEFAULT_KEEP_LAST. Не выставлен на
    # фронте пока никак — задел на будущее, если понадобится настроить.
    keep_last: int | None = None


class ToolCallOut(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class DialogMessageOut(BaseModel):
    id: str
    role: str
    content: str
    tool_calls: list[ToolCallOut] = []
    # Донесённые из более раннего хода tool_calls — только для отрисовки
    # карточек на фронте (см. run_dialog_turn в routers/dialogs.py), никогда
    # не смешивается с tool_calls: тот идёт в LLM API и требует реального
    # tool-результата сразу после себя, этот — нет.
    display_tool_calls: list[ToolCallOut] = []
    tool_call_id: str | None = None
    name: str | None = None
    suggested_replies: list[str] = []
    created_at: str
    # Синтетическая сводка более ранней части истории (app/dialog_compaction.py)
    # — обычная assistant-запись с этими двумя флагами, роль не меняется,
    # _to_llm_messages её не отличает от любой другой. snapshot_id указывает
    # на properties["compaction_snapshots"] — по нему фронт откатывает сжатие.
    is_summary: bool = False
    snapshot_id: str | None = None


class CompactionSnapshotOut(BaseModel):
    id: str
    created_at: str
    # Только счётчик — сами замещённые сообщения (replaced_messages) целиком
    # фронту не нужны, откат делает бэкенд; не раздувать каждый GET /dialogs/{id}.
    message_count: int


class DialogSummaryOut(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    # По умолчанию пусто — заполняется только в списке диалогов (список
    # теперь общий на все спейсы сразу, нужно подписывать откуда каждый).
    # _serialize() для одиночного диалога (DialogOut) это поле не трогает —
    # там уже понятно, в каком спейсе открыт диалог, по контексту экрана.
    space_name: str = ""
    title: str
    created_at: datetime
    updated_at: datetime
    # Только для списка скретч-диалогов заметки (list_scoped_dialogs) —
    # реальная жалоба: у всех диалогов одной заметки одинаковый заголовок
    # ("Ассистент: {название заметки}"), в списке их не отличить друг от
    # друга. None в остальных местах (обычный список диалогов не заполняет).
    preview: str | None = None


class DialogOut(DialogSummaryOut):
    messages: list[DialogMessageOut] = []
    compaction_snapshots: list[CompactionSnapshotOut] = []
