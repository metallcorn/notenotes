"""Сообщения об ошибках инструментов должны говорить, ЧТО ДЕЛАТЬ, а не
только констатировать отказ.

Замер 2026-09-03 показал: это единственное место, где модель исправляется
во всех прогонах без исключения. В транскрипте видно живьём — create_list
без folder_id вернул отказ с объяснением, модель немедленно вызвала
list_folders и повторила создание правильно. Надёжнее любого правила в
промпте, потому что приходит в момент ошибки и называет выход.

Тест сторожит регрессию: новое сообщение без подсказки — это молчаливая
потеря самого надёжного механизма самокоррекции, который у нас есть.
"""

import ast
import pathlib
import re

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "tools"

# Сообщения, где подсказка не нужна: действие пользователя не поможет,
# либо текст уже содержит всё необходимое.
ALLOWED_WITHOUT_HINT: set[str] = set()


def _tool_error_messages() -> list[tuple[str, str]]:
    """(файл, текст сообщения) для каждого raise ToolError(...) с литералом."""
    found: list[tuple[str, str]] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            func = node.exc.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "ToolError" or not node.exc.args:
                continue
            arg = node.exc.args[0]
            # Собираем текст и из обычной строки, и из f-строки, и из
            # неявной склейки соседних литералов.
            parts: list[str] = []
            for piece in ast.walk(arg):
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    parts.append(piece.value)
            if parts:
                found.append((path.name, " ".join(parts)))
    return found


def test_every_tool_error_says_what_to_do():
    missing = [
        (f, m) for f, m in _tool_error_messages()
        if "—" not in m and m not in ALLOWED_WITHOUT_HINT
    ]
    assert not missing, (
        "Эти сообщения только констатируют отказ, но не говорят, что делать вместо. "
        "Добавь короткую подсказку после тире (образец — lists.py, 'Пункт не найден "
        f"— сначала вызови get_list…'):\n{missing}"
    )


def test_hints_name_real_tools():
    """Подсказка бесполезна и вредна, если называет несуществующий
    инструмент: модель послушно попробует его вызвать и получит новую
    ошибку вместо выхода."""
    from app.tools.registry import get_tool_definitions

    real = {d.name for d in get_tool_definitions()}
    # snake_case-слово из двух и более частей — так выглядят имена тулов.
    # Имена параметров (folder_id, trigger_at) отсеиваем по списку реальных
    # тулов: проверяем только те слова, что ПОХОЖИ на тул и при этом
    # встречаются в подсказке после тире.
    candidate_re = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
    referenced: set[str] = set()
    known_params = {"folder_id", "list_id", "table_id", "item_id", "dialog_id",
                    "memory_id", "notification_id", "trigger_at", "snapshot_id",
                    "parent_id", "tag_name", "material_type",
                    # 28.10: рутины, пункты списков, версии.
                    "routine_id", "version_id", "entry_id", "text_match", "new_name",
                    "every_minutes", "ends_on", "starts_on", "first_at", "min_gap_minutes"}
    for _, msg in _tool_error_messages():
        hint = msg.split("—", 1)[1] if "—" in msg else ""
        for word in candidate_re.findall(hint):
            if word not in known_params:
                referenced.add(word)

    unknown = referenced - real
    assert not unknown, (
        f"Подсказки называют то, чего нет среди инструментов: {sorted(unknown)}. "
        "Модель послушно попробует это вызвать и получит новую ошибку."
    )
    assert referenced, "Ни одна подсказка не называет инструмент — проверь тест"
