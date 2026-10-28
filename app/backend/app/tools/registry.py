from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.llm.base import ToolDefinition

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """Ожидаемая ошибка тула (неверные аргументы, объект не найден и т.п.) —
    возвращается модели как результат вызова, а не роняет весь агентный цикл."""


@dataclass
class ToolContext:
    """Что доступно каждому обработчику тула. space_id — спейс, к которому
    привязан диалог: ассистент действует только в его границах, не мигрирует
    по всем спейсам пользователя без явного участия человека."""

    db: AsyncSession
    user_id: uuid.UUID
    space_id: uuid.UUID
    # Живой пояс из браузера (заголовок X-Client-Timezone), не домашний
    # User.timezone — для прямых, здесь-и-сейчас действий вроде "напомни в
    # 9 утра" важно, где пользователь физически сидит прямо сейчас, а не
    # где он обычно живёт (app/user_timezone.py). None — если запрос не
    # веб (Telegram: см. telegram_bot.py, где передаётся домашний пояс за
    # неимением живого сигнала) или заголовок не пришёл.
    client_timezone: str | None = None


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]

# Человеко-понятные названия для настроек («Умения ассистента») — отдельно
# от ToolDefinition.description, которое пишется для модели, не для UI.
# toggleable=False — базовые CRUD-тулы заметок/списков/памяти: без них
# ассистент не может решать основные задачи, отключение было бы не настройкой,
# а поломкой, поэтому в UI они видны, но без переключателя. suggest_replies
# сюда намеренно не входит — это не способность, а разметка чипов для UI.
SKILL_CATALOG: dict[str, dict[str, Any]] = {
    "search_base": {"label": "Поиск по заметкам", "description": "Ищет по названиям и содержимому заметок и списков", "toggleable": False},
    "list_all_items": {"label": "Просмотр всех заметок", "description": "Смотрит заголовки всех заметок, если обычный поиск не нашёл", "toggleable": False},
    "create_note": {"label": "Создание заметок", "description": "Создаёт новые заметки", "toggleable": False},
    "get_note": {"label": "Чтение заметок", "description": "Читает полное содержимое заметки", "toggleable": False},
    "update_note": {"label": "Редактирование заметок", "description": "Меняет заголовок и содержимое заметки", "toggleable": False},
    "append_to_note": {"label": "Дописать в заметку", "description": "Добавляет текст в конец заметки, не трогая остальное", "toggleable": False},
    "delete_note": {"label": "Удаление заметок", "description": "Перемещает заметку в корзину", "toggleable": False},
    "add_tag": {"label": "Теги", "description": "Добавляет тег к заметке", "toggleable": False},
    "list_folders": {"label": "Список папок", "description": "Смотрит, какие папки существуют", "toggleable": False},
    "create_folder": {"label": "Создание папок", "description": "Создаёт новую папку", "toggleable": False},
    "list_tags": {"label": "Список тегов", "description": "Смотрит, какие теги существуют", "toggleable": False},
    "list_items_by_tag": {"label": "Заметки по тегу", "description": "Смотрит, что помечено конкретным тегом", "toggleable": False},
    "list_items_in_folder": {"label": "Содержимое папки", "description": "Смотрит, что лежит в конкретной папке", "toggleable": False},
    "create_list": {"label": "Создание списков", "description": "Создаёт чек-листы", "toggleable": False},
    "get_list": {"label": "Чтение списков", "description": "Читает реальные пункты списка", "toggleable": False},
    "add_list_entry": {"label": "Добавление пунктов списка", "description": "Добавляет новый пункт в список", "toggleable": False},
    "toggle_list_entry": {"label": "Отметка пунктов списка", "description": "Отмечает пункт выполненным/невыполненным", "toggleable": False},
    "update_list_entry": {"label": "Правка пунктов списка", "description": "Меняет текст пункта", "toggleable": False},
    "delete_list_entry": {"label": "Удаление пунктов списка", "description": "Убирает пункт из списка", "toggleable": False},
    "tables": {
        "label": "Таблицы",
        "description": "Создаёт и редактирует таблицы со столбцами и строками (create_table/get_table/add_table_row и т.п.)",
        "toggleable": True,
    },
    "remember_fact": {"label": "Память", "description": "Запоминает факты о тебе между диалогами", "toggleable": False},
    "list_memories": {"label": "Просмотр памяти", "description": "Смотрит, что уже запомнено", "toggleable": False},
    "forget_fact": {"label": "Забыть факт", "description": "Удаляет запомненный факт", "toggleable": False},
    "web_search": {"label": "Веб-поиск", "description": "Ищет в открытом интернете через Tavily (до 5 запросов за ход)", "toggleable": True},
    "create_calendar_event": {"label": "Календарь", "description": "Готовит файл события для добавления в твой календарь", "toggleable": True},
    "create_maps_link": {"label": "Карты и навигация", "description": "Готовит ссылку на место в Google Maps", "toggleable": True},
    "create_reminder": {"label": "Напоминания", "description": "Создаёт напоминание в центре уведомлений на выбранное время", "toggleable": True},
    "list_reminders": {"label": "Просмотр напоминаний", "description": "Смотрит список активных напоминаний", "toggleable": False},
    # toggleable=False по той же причине, что у list_reminders: без этого
    # ассистент не может ответить на «что у меня на неделе», а это не
    # дополнительное умение, а базовый вопрос.
    "list_files": {"label": "Просмотр файлов", "description": "Видит вложенные файлы и извлечённый из них текст", "toggleable": False},
    "get_file": {"label": "Чтение файлов", "description": "Читает содержимое файла — текст или саму картинку", "toggleable": False},
    "upload_file": {"label": "Загрузка файлов", "description": "Кладёт файл в базу и вставляет в заметку", "toggleable": True},
    "list_agenda": {"label": "Что впереди", "description": "Показывает напоминания и события, распознанные в заметках", "toggleable": False},
    "self_check": {"label": "Самопроверка", "description": "Отвечает на «что у нас не так» — где ассистент за неделю спотыкался", "toggleable": True},
    "resolve_reminder": {"label": "Отметка напоминаний", "description": "Отмечает напоминание выполненным", "toggleable": False},
    "snooze_reminder": {"label": "Перенос напоминаний", "description": "Откладывает напоминание — оно сработает заново позже", "toggleable": False},
    "structure": {
        "label": "Папки и теги: правка",
        "description": "Переименовывает, переносит и удаляет пустые папки; снимает, переименовывает, сливает и удаляет теги",
        "toggleable": True,
    },
    "history": {
        "label": "История, корзина, архив",
        "description": "Смотрит версии заметки и откатывает, возвращает из корзины, убирает в архив",
        "toggleable": True,
    },
    "routines": {
        "label": "Рутины",
        "description": "Заводит приёмы лекарств с подтверждением, отмечает «дал», ставит на паузу (create_routine/list_routines/mark_dose/update_routine)",
        "toggleable": True,
    },
    "run_python": {"label": "Python-вычисления", "description": "Точные вычисления в изолированной песочнице", "toggleable": True},
    "read_website": {"label": "Чтение сайтов по ссылке", "description": "Скачивает и читает содержимое страницы по присланной ссылке", "toggleable": True},
    "track_delivery": {"label": "Отслеживание доставки", "description": "Статус посылки по трек-номеру или ссылке (InPost, Poczta, Orlen Paczka, DPD, Allegro Delivery)", "toggleable": True},
    "get_compacted_history": {
        "label": "Чтение сжатой истории диалога",
        "description": "Если сводка после сжатия истории (см. кнопку в чате) неточна для ответа — читает дословный оригинал",
        "toggleable": True,
    },
    "test_url_request": {"label": "Проверка ссылки", "description": "Делает тестовый запрос по ссылке, чтобы предложить поля для виджета", "toggleable": True},
    "insert_url_check_block": {"label": "Виджет «Проверить по ссылке»", "description": "Добавляет в заметку карточку с данными по ссылке и кнопкой «Обновить»", "toggleable": True},
    "show_note_images": {
        "label": "Картинки в чате",
        "description": "Показывает найденную в заметках картинку прямо в ответе, если она по теме",
        "toggleable": True,
    },
}

# show_note_images не вызываемый тул (нет ToolDefinition/handler — это
# переключаемое поведение поверх get_note/search_base, см.
# SHOW_NOTE_IMAGES_SKILL в routers/dialogs.py), поэтому его нет в
# _build_registry() и list_skills() ниже не нашёл бы его обычным способом.
PROMPT_ONLY_SKILLS = {"show_note_images"}

# "tables" в SKILL_CATALOG — не имя реального тула (в отличие от
# создания/чтения заметок и списков, работа с таблицами намеренно не
# "core": реальный запрос — видеть и уметь выключить работу с таблицами
# как ОДНУ способность в настройках, а не 6 отдельных переключателей на
# каждый tables.* тул по отдельности, что было бы неюзабельно и
# бессмысленно включать вразнобой). Здесь — единственное место, где имя
# из SKILL_CATALOG разворачивается в реальные имена тулов для фильтрации.
TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "tables": ("create_table", "get_table", "add_table_row", "update_table_row", "delete_table_row", "add_table_column"),
    # Один тумблер «Отслеживание доставки» управляет обоими тулами скилла:
    # track_delivery (статус в чат) и insert_delivery_block (виджет в заметку).
    "track_delivery": ("track_delivery", "insert_delivery_block"),
    # Один тумблер «Рутины» на все четыре инструмента — как у таблиц.
    "routines": ("create_routine", "list_routines", "mark_dose", "update_routine"),
    "structure": ("update_folder", "delete_folder", "remove_tag", "rename_tag", "merge_tag", "delete_tag"),
    "history": ("list_versions", "revert_version", "list_trash", "restore_note", "archive_note"),
}


def _expand_disabled(disabled: set[str]) -> set[str]:
    expanded = set(disabled)
    for group_name, members in TOOL_GROUPS.items():
        if group_name in disabled:
            expanded |= set(members)
    return expanded


def _build_registry() -> dict[str, tuple[ToolDefinition, ToolHandler]]:
    from app import self_check
    from app.tools import agenda, calendar_event, files as files_tool, dialog_history, history, lists, maps, memory, notes, python_sandbox, read_website, reminders, routines as routines_tool, search_base, structure, tables, track_delivery, ui, url_check, web_search

    registry: dict[str, tuple[ToolDefinition, ToolHandler]] = {
        search_base.DEFINITION.name: (search_base.DEFINITION, search_base.handle),
        dialog_history.GET_COMPACTED_HISTORY.name: (
            dialog_history.GET_COMPACTED_HISTORY,
            dialog_history.get_compacted_history,
        ),
        ui.SUGGEST_REPLIES.name: (ui.SUGGEST_REPLIES, ui.suggest_replies),
        calendar_event.CREATE_CALENDAR_EVENT.name: (
            calendar_event.CREATE_CALENDAR_EVENT,
            calendar_event.create_calendar_event,
        ),
        maps.CREATE_MAPS_LINK.name: (maps.CREATE_MAPS_LINK, maps.create_maps_link),
        python_sandbox.RUN_PYTHON.name: (python_sandbox.RUN_PYTHON, python_sandbox.run_python),
        read_website.DEFINITION.name: (read_website.DEFINITION, read_website.handle),
        track_delivery.DEFINITION.name: (track_delivery.DEFINITION, track_delivery.handle),
        track_delivery.INSERT_DELIVERY_BLOCK.name: (track_delivery.INSERT_DELIVERY_BLOCK, track_delivery.insert_delivery_block),
        url_check.TEST_URL_REQUEST.name: (url_check.TEST_URL_REQUEST, url_check.test_url_request),
        url_check.INSERT_URL_CHECK_BLOCK.name: (url_check.INSERT_URL_CHECK_BLOCK, url_check.insert_url_check_block),
        reminders.CREATE_REMINDER.name: (reminders.CREATE_REMINDER, reminders.create_reminder),
        reminders.LIST_REMINDERS.name: (reminders.LIST_REMINDERS, reminders.list_reminders),
        agenda.DEFINITION.name: (agenda.DEFINITION, agenda.handle),
        self_check.DEFINITION.name: (self_check.DEFINITION, self_check.handle),
        files_tool.LIST_FILES.name: (files_tool.LIST_FILES, files_tool.list_files),
        files_tool.GET_FILE.name: (files_tool.GET_FILE, files_tool.get_file),
        files_tool.UPLOAD_FILE.name: (files_tool.UPLOAD_FILE, files_tool.upload_file),
        reminders.RESOLVE_REMINDER.name: (reminders.RESOLVE_REMINDER, reminders.resolve_reminder),
        reminders.SNOOZE_REMINDER.name: (reminders.SNOOZE_REMINDER, reminders.snooze_reminder),
        routines_tool.CREATE_ROUTINE.name: (routines_tool.CREATE_ROUTINE, routines_tool.create_routine),
        routines_tool.LIST_ROUTINES.name: (routines_tool.LIST_ROUTINES, routines_tool.list_routines),
        routines_tool.MARK_DOSE.name: (routines_tool.MARK_DOSE, routines_tool.mark_dose),
        routines_tool.UPDATE_ROUTINE.name: (routines_tool.UPDATE_ROUTINE, routines_tool.update_routine),
        notes.CREATE_NOTE.name: (notes.CREATE_NOTE, notes.create_note),
        notes.CREATE_FOLDER.name: (notes.CREATE_FOLDER, notes.create_folder),
        notes.GET_NOTE.name: (notes.GET_NOTE, notes.get_note),
        notes.UPDATE_NOTE.name: (notes.UPDATE_NOTE, notes.update_note),
        notes.APPEND_TO_NOTE.name: (notes.APPEND_TO_NOTE, notes.append_to_note),
        notes.DELETE_NOTE.name: (notes.DELETE_NOTE, notes.delete_note),
        notes.ADD_TAG.name: (notes.ADD_TAG, notes.add_tag),
        notes.LIST_FOLDERS.name: (notes.LIST_FOLDERS, notes.list_folders),
        notes.LIST_TAGS.name: (notes.LIST_TAGS, notes.list_tags),
        notes.LIST_ITEMS_BY_TAG.name: (notes.LIST_ITEMS_BY_TAG, notes.list_items_by_tag),
        notes.LIST_ITEMS_IN_FOLDER.name: (notes.LIST_ITEMS_IN_FOLDER, notes.list_items_in_folder),
        notes.LIST_ALL_ITEMS.name: (notes.LIST_ALL_ITEMS, notes.list_all_items),
        lists.CREATE_LIST.name: (lists.CREATE_LIST, lists.create_list),
        lists.GET_LIST.name: (lists.GET_LIST, lists.get_list),
        lists.ADD_LIST_ENTRY.name: (lists.ADD_LIST_ENTRY, lists.add_list_entry),
        lists.TOGGLE_LIST_ENTRY.name: (lists.TOGGLE_LIST_ENTRY, lists.toggle_list_entry),
        lists.UPDATE_LIST_ENTRY.name: (lists.UPDATE_LIST_ENTRY, lists.update_list_entry),
        lists.DELETE_LIST_ENTRY.name: (lists.DELETE_LIST_ENTRY, lists.delete_list_entry),
        structure.UPDATE_FOLDER.name: (structure.UPDATE_FOLDER, structure.update_folder),
        structure.DELETE_FOLDER.name: (structure.DELETE_FOLDER, structure.delete_folder),
        structure.REMOVE_TAG.name: (structure.REMOVE_TAG, structure.remove_tag),
        structure.RENAME_TAG.name: (structure.RENAME_TAG, structure.rename_tag),
        structure.MERGE_TAG.name: (structure.MERGE_TAG, structure.merge_tag),
        structure.DELETE_TAG.name: (structure.DELETE_TAG, structure.delete_tag),
        history.LIST_VERSIONS.name: (history.LIST_VERSIONS, history.list_versions),
        history.REVERT_VERSION.name: (history.REVERT_VERSION, history.revert_version),
        history.LIST_TRASH.name: (history.LIST_TRASH, history.list_trash),
        history.RESTORE_NOTE.name: (history.RESTORE_NOTE, history.restore_note),
        history.ARCHIVE_NOTE.name: (history.ARCHIVE_NOTE, history.archive_note),
        tables.CREATE_TABLE.name: (tables.CREATE_TABLE, tables.create_table),
        tables.GET_TABLE.name: (tables.GET_TABLE, tables.get_table),
        tables.ADD_TABLE_ROW.name: (tables.ADD_TABLE_ROW, tables.add_table_row),
        tables.UPDATE_TABLE_ROW.name: (tables.UPDATE_TABLE_ROW, tables.update_table_row),
        tables.DELETE_TABLE_ROW.name: (tables.DELETE_TABLE_ROW, tables.delete_table_row),
        tables.ADD_TABLE_COLUMN.name: (tables.ADD_TABLE_COLUMN, tables.add_table_column),
        memory.REMEMBER_FACT.name: (memory.REMEMBER_FACT, memory.remember_fact),
        memory.LIST_MEMORIES.name: (memory.LIST_MEMORIES, memory.list_memories),
        memory.FORGET_FACT.name: (memory.FORGET_FACT, memory.forget_fact),
    }

    # web_search недоступен модели вовсе, если Tavily не настроен — лучше
    # чтобы тула не было в списке, чем чтобы модель звала его и всегда
    # получала ошибку.
    if get_settings().tavily_api_key:
        registry[web_search.DEFINITION.name] = (web_search.DEFINITION, web_search.handle)

    return registry


def get_tool_definitions(disabled: set[str] | None = None) -> list[ToolDefinition]:
    disabled = _expand_disabled(disabled or set())
    return [definition for definition in (d for d, _ in _build_registry().values()) if definition.name not in disabled]


def list_skills(disabled: set[str]) -> list[dict[str, Any]]:
    available = _build_registry()
    return [
        {
            "name": name,
            "label": meta["label"],
            "description": meta["description"],
            "toggleable": meta["toggleable"],
            "enabled": name not in disabled,
        }
        for name, meta in SKILL_CATALOG.items()
        if name in available or name in PROMPT_ONLY_SKILLS or name in TOOL_GROUPS
    ]


async def dispatch(name: str, ctx: ToolContext, args: dict[str, Any], disabled: set[str] | None = None) -> dict[str, Any]:
    # Проверка независима от того, что мы передали модели в tools —
    # на практике модель иногда возвращает tool_call на имя, которого не
    # было в объявленных ей тулах (наблюдали живьём с run_python), поэтому
    # dispatch не может полагаться только на то, что "модель не должна была
    # это вызвать". Отключённый тул отказывает здесь тоже, а не только
    # отсутствует в описании для модели.
    if disabled and name in _expand_disabled(disabled):
        return {"error": f"Инструмент {name} отключён в настройках пользователя"}
    entry = _build_registry().get(name)
    if entry is None:
        return {"error": f"Неизвестный инструмент: {name}"}
    definition, handler = entry
    try:
        result = await handler(ctx, args)
    except ToolError as e:
        return {"error": str(e)}
    except Exception:
        logger.exception("Ошибка выполнения тула %s", name)
        return {"error": "Внутренняя ошибка при выполнении инструмента"}
    # Аргументы, которых у инструмента нет, — вслух, а не молча. Живой
    # случай 19.10: update_note(item_id, folder_id) — параметра folder_id
    # у update_note не было, его проглотили, ответ выглядел успешным, и
    # ассистент написал «Готово, перенесла», ничего не перенеся. Ошибкой
    # не делаем: лишний безобидный ключ в поиске не должен ломать ответ.
    # Но «не применено» модель должна увидеть рядом с результатом.
    known = set((definition.parameters or {}).get("properties", {})) | _ARG_ALIASES.get(name, set())
    unknown = sorted(k for k in args if k not in known)
    if unknown and isinstance(result, dict):
        result = {
            **result,
            "warning": (
                f"Параметров {', '.join(unknown)} у {name} нет — они НЕ применены. "
                "Не сообщай пользователю, что это сделано."
            ),
        }
    return result


# Синонимы, которые обработчики принимают сверх схемы — сознательно (см.
# create_folder: модель по аналогии с соседями шлёт title вместо name).
_ARG_ALIASES: dict[str, set[str]] = {
    "append_to_note": {"content"},
    "create_folder": {"title"},
    "add_table_column": {"title"},
}
