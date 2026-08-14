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
    "remember_fact": {"label": "Память", "description": "Запоминает факты о тебе между диалогами", "toggleable": False},
    "list_memories": {"label": "Просмотр памяти", "description": "Смотрит, что уже запомнено", "toggleable": False},
    "forget_fact": {"label": "Забыть факт", "description": "Удаляет запомненный факт", "toggleable": False},
    "web_search": {"label": "Веб-поиск", "description": "Ищет в открытом интернете через Tavily (до 5 запросов за ход)", "toggleable": True},
    "create_calendar_event": {"label": "Календарь", "description": "Готовит файл события для добавления в твой календарь", "toggleable": True},
    "create_maps_link": {"label": "Карты и навигация", "description": "Готовит ссылку на место в Google Maps", "toggleable": True},
    "create_reminder": {"label": "Напоминания", "description": "Создаёт напоминание в центре уведомлений на выбранное время", "toggleable": True},
    "list_reminders": {"label": "Просмотр напоминаний", "description": "Смотрит список активных напоминаний", "toggleable": False},
    "resolve_reminder": {"label": "Отметка напоминаний", "description": "Отмечает напоминание выполненным", "toggleable": False},
    "run_python": {"label": "Python-вычисления", "description": "Точные вычисления в изолированной песочнице", "toggleable": True},
    "read_website": {"label": "Чтение сайтов по ссылке", "description": "Скачивает и читает содержимое страницы по присланной ссылке", "toggleable": True},
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


def _build_registry() -> dict[str, tuple[ToolDefinition, ToolHandler]]:
    from app.tools import calendar_event, lists, maps, memory, notes, python_sandbox, read_website, reminders, search_base, ui, web_search

    registry: dict[str, tuple[ToolDefinition, ToolHandler]] = {
        search_base.DEFINITION.name: (search_base.DEFINITION, search_base.handle),
        ui.SUGGEST_REPLIES.name: (ui.SUGGEST_REPLIES, ui.suggest_replies),
        calendar_event.CREATE_CALENDAR_EVENT.name: (
            calendar_event.CREATE_CALENDAR_EVENT,
            calendar_event.create_calendar_event,
        ),
        maps.CREATE_MAPS_LINK.name: (maps.CREATE_MAPS_LINK, maps.create_maps_link),
        python_sandbox.RUN_PYTHON.name: (python_sandbox.RUN_PYTHON, python_sandbox.run_python),
        read_website.DEFINITION.name: (read_website.DEFINITION, read_website.handle),
        reminders.CREATE_REMINDER.name: (reminders.CREATE_REMINDER, reminders.create_reminder),
        reminders.LIST_REMINDERS.name: (reminders.LIST_REMINDERS, reminders.list_reminders),
        reminders.RESOLVE_REMINDER.name: (reminders.RESOLVE_REMINDER, reminders.resolve_reminder),
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
    disabled = disabled or set()
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
        if name in available or name in PROMPT_ONLY_SKILLS
    ]


async def dispatch(name: str, ctx: ToolContext, args: dict[str, Any], disabled: set[str] | None = None) -> dict[str, Any]:
    # Проверка независима от того, что мы передали модели в tools —
    # на практике модель иногда возвращает tool_call на имя, которого не
    # было в объявленных ей тулах (наблюдали живьём с run_python), поэтому
    # dispatch не может полагаться только на то, что "модель не должна была
    # это вызвать". Отключённый тул отказывает здесь тоже, а не только
    # отсутствует в описании для модели.
    if disabled and name in disabled:
        return {"error": f"Инструмент {name} отключён в настройках пользователя"}
    entry = _build_registry().get(name)
    if entry is None:
        return {"error": f"Неизвестный инструмент: {name}"}
    _, handler = entry
    try:
        return await handler(ctx, args)
    except ToolError as e:
        return {"error": str(e)}
    except Exception:
        logger.exception("Ошибка выполнения тула %s", name)
        return {"error": "Внутренняя ошибка при выполнении инструмента"}
