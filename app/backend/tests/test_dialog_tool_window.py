"""Свёртка старых результатов инструментов в запросе к модели.

Повод — замер на боевой базе 07.10 (см. docstring dialog_tool_window.py):
93% контекста диалога «Тренировки» составляли результаты инструментов, и
один ход на «16кг 10 раз» стоил 731 тысячу входных токенов при окне
модели в 128K. Жалоба владельца: «оч странно он отвечает».
"""

from __future__ import annotations

from app.dialog_tool_window import FOLD_OVER_CHARS, fold_stale_tool_results

BIG = "x" * (FOLD_OVER_CHARS + 1)
SMALL = "y" * 100


def _user(text="вопрос"):
    return {"role": "user", "content": text}


def _tool(content, name="get_table", call_id="c1"):
    return {"role": "tool", "content": content, "name": name, "tool_call_id": call_id}


def _assistant(content="ответ", calls=None):
    return {"role": "assistant", "content": content, "tool_calls": calls or []}


class TestЧтоСворачивается:
    def test_старый_дамп_сворачивается(self):
        records = [_user(), _tool(BIG), _assistant()] + [_user(), _assistant()] * 6

        folded = fold_stale_tool_results(records)

        assert "_свёрнуто" in folded[1]["content"]
        assert "get_table" in folded[1]["content"], "модель должна понимать, чего результат"
        assert len(folded[1]["content"]) < 300

    def test_маленький_результат_не_сворачивается_никогда(self):
        """В нём лежат id. Результат add_table_row — это ~250 символов и
        row_id внутри; свернуть его значит заставить модель снова звать
        get_table, то есть вернуть ту же проблему с другой стороны."""
        records = [_user(), _tool(SMALL, name="add_table_row"), _assistant()] + [_user(), _assistant()] * 20

        folded = fold_stale_tool_results(records)

        assert folded[1]["content"] == SMALL

    def test_свежее_остаётся_дословно(self):
        records = [_user(), _assistant()] * 10 + [_user(), _tool(BIG), _assistant()]

        folded = fold_stale_tool_results(records)

        assert folded[-2]["content"] == BIG

    def test_окно_считается_ходами_пользователя(self):
        # Ход = реплика пользователя и всё за ней. Четыре последних хода
        # дословно, пятый с конца — уже свёрнут.
        records = []
        for i in range(6):
            records += [_user(f"ход {i}"), _tool(BIG, call_id=f"c{i}"), _assistant()]

        folded = fold_stale_tool_results(records)

        contents = [r["content"] for r in folded if r["role"] == "tool"]
        assert contents[:2] == [folded[1]["content"], folded[4]["content"]]
        assert all("_свёрнуто" in c for c in contents[:2])
        assert all(c == BIG for c in contents[2:]), "последние четыре хода — дословно"

    def test_реплики_пользователя_и_ассистента_не_трогаем(self):
        """Они и так дешёвые: в замере 2 922 + 19 437 символов против
        273 103 у инструментов. Терять их смысла нет."""
        records = [_user("длинный вопрос " * 100), _assistant("длинный ответ " * 100)] + [_user(), _assistant()] * 10

        folded = fold_stale_tool_results(records)

        assert folded[0] == records[0]
        assert folded[1] == records[1]


class TestЧтоНельзяСломать:
    def test_сообщение_остаётся_на_месте(self):
        """У каждого assistant.tool_calls[i].id должен быть парный
        tool-результат, иначе Mistral отвечает 400 — та же причина, по
        которой find_cut_index режет историю только по границе user."""
        records = [_user(), _assistant(calls=[{"id": "c1", "name": "get_table", "arguments": {}}]), _tool(BIG)]
        records += [_user(), _assistant()] * 6

        folded = fold_stale_tool_results(records)

        assert len(folded) == len(records)
        assert [r["role"] for r in folded] == [r["role"] for r in records]
        assert folded[2]["tool_call_id"] == "c1"
        assert folded[2]["name"] == "get_table"

    def test_исходный_список_не_меняется(self):
        """records уходит в БД и на экран — сворачиваем только копию."""
        records = [_user(), _tool(BIG), _assistant()] + [_user(), _assistant()] * 6
        original = _tool(BIG)["content"]

        fold_stale_tool_results(records)

        assert records[1]["content"] == original

    def test_пустая_история(self):
        assert fold_stale_tool_results([]) == []

    def test_история_короче_окна(self):
        records = [_user(), _tool(BIG), _assistant()]

        assert fold_stale_tool_results(records)[1]["content"] == BIG

    def test_результат_без_имени_инструмента(self):
        records = [_user(), {"role": "tool", "content": BIG}] + [_user(), _assistant()] * 6

        folded = fold_stale_tool_results(records)

        assert "_свёрнуто" in folded[1]["content"]


class TestЖивойЗамер:
    def test_на_форме_настоящего_диалога(self):
        """Воспроизводим пропорции диалога «Тренировки»: короткие реплики
        пользователя, подтверждения на 300 символов и дампы таблицы на
        девять тысяч. Проверяем сам порядок экономии, а не точное число."""
        records: list[dict] = []
        for i in range(20):
            records += [
                _user("16кг 10 раз"),
                _assistant("", calls=[{"id": f"g{i}", "name": "get_table", "arguments": {}}]),
                _tool("z" * 9000, name="get_table", call_id=f"g{i}"),
                _assistant("", calls=[{"id": f"u{i}", "name": "update_table_row", "arguments": {}}]),
                _tool("w" * 320, name="update_table_row", call_id=f"u{i}"),
                _assistant("Добавлено!"),
            ]

        before = sum(len(r.get("content") or "") for r in records)
        after = sum(len(r.get("content") or "") for r in fold_stale_tool_results(records))

        assert before > 180_000
        assert after < before / 4
        # Подтверждения с id целы все до единого.
        assert sum(1 for r in fold_stale_tool_results(records) if r.get("content") == "w" * 320) == 20


class TestПотолокНаОдинРезультат:
    """Живой случай 10.10: диалог «Telegram» умер насовсем. Три get_file с
    base64 файлов (1.5 + 3.8 + 1.9 МБ) в ОДНОМ ходу — Mistral ответил 400.
    Запись починили 26.09, но история проигрывается заново каждый ход, и
    через две недели тот же чат снова отдал ту же ошибку на безобидное
    «а что такое Кейтерка?». Лечится только на чтении."""

    def test_непомерный_свежий_результат_обрезается(self):
        huge = "{" + "д" * 4_000_000
        records = [_user("найди мои права"), _tool(huge, name="get_file"), _assistant()]

        folded = fold_stale_tool_results(records)

        assert len(folded[1]["content"]) < 31_000

    def test_обрезок_честно_помечен(self):
        """Иначе модель примет обрубок за полный результат и ответит по
        половине данных, не сказав об этом."""
        records = [_user(), _tool("я" * 100_000, name="get_file"), _assistant()]

        content = fold_stale_tool_results(records)[1]["content"]

        assert "ОБРЕЗАНО" in content
        assert "100000" in content, "сколько было — тоже надо сказать"

    def test_три_мегабайтных_вместе_укладываются_в_контекст(self):
        """Ровно форма мёртвого диалога: один ход, три get_file."""
        records = [
            _user("найди мои права"),
            _assistant("", calls=[{"id": f"f{i}", "name": "get_file", "arguments": {}} for i in range(3)]),
            _tool("a" * 1_535_922, name="get_file", call_id="f0"),
            _tool("b" * 3_795_300, name="get_file", call_id="f1"),
            _tool("c" * 1_928_784, name="get_file", call_id="f2"),
        ]

        total = sum(len(r.get("content") or "") for r in fold_stale_tool_results(records))

        assert total < 100_000, "7.26 МБ в промпт больше не уедет"

    def test_потолок_не_трогает_обычные_результаты(self):
        """Самый крупный законный результат в живой базе — list_all_items
        на 57 850; он обрежется, и это правильная цена. А get_table на
        9 300 и web_search на 23 000 должны проходить целиком."""
        for size, name in ((9_300, "get_table"), (23_215, "web_search")):
            records = [_user(), _tool("x" * size, name=name), _assistant()]

            assert fold_stale_tool_results(records)[1]["content"] == "x" * size

    def test_старое_и_непомерное_становится_заглушкой_а_не_обрезком(self):
        """Заглушка дешевле обрезка: 120 символов против 30 000, а для
        устаревших данных и то и то бесполезно."""
        records = [_user(), _tool("x" * 1_000_000, name="get_file"), _assistant()]
        records += [_user(), _assistant()] * 6

        content = fold_stale_tool_results(records)[1]["content"]

        assert "_свёрнуто" in content
        assert len(content) < 300

    def test_структура_цела_и_при_обрезке(self):
        records = [
            _user(),
            _assistant("", calls=[{"id": "f0", "name": "get_file", "arguments": {}}]),
            _tool("x" * 1_000_000, name="get_file", call_id="f0"),
        ]

        folded = fold_stale_tool_results(records)

        assert folded[2]["tool_call_id"] == "f0"
        assert folded[2]["name"] == "get_file"
        assert len(folded) == 3
