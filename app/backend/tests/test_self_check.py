"""Самопроверка: находить промахи ассистента до того, как о них расскажут.

Жалоба владельца 10.10: «он часто ошибается и тупит, и мы это никак не
можем решить». Разбор показал, что чиним мы как раз нормально — но ВСЕ
промахи находил он сам и приносил. Цикл из четырнадцати одинаковых
ошибок инструмента никого не разбудил; мёртвый диалог простоял две
недели.

Каждая проверка здесь поймала бы реальный случай из прошлого, и тесты
написаны на тех же числах, что замерены на живой базе.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.self_check import (
    LOOKBACK,
    MAX_PROMPT_CHARS,
    REPEATED_ERROR_TIMES,
    inspect_dialog,
)
from app.tools.web_search import OWN_BASE_KEY

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def _at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _msg(role, content="", *, name=None, calls=None, days_ago=0.0):
    m = {"role": role, "content": content, "created_at": _at(days_ago)}
    if name:
        m["name"] = name
    if calls is not None:
        m["tool_calls"] = calls
    return m


def _kinds(records):
    return {f.kind for f in inspect_dialog("d1", "Тренировки", records, now=NOW)}


class TestРаздутыйДиалог:
    def test_ловит_то_что_убивало_тренировки(self):
        """«Тренировки» перед починкой отправляли 295 462 символа на
        каждый вызов — 115 тысяч токенов при окне модели 128K."""
        records = [_msg("user", "16кг 10 раз")]
        records += [_msg("tool", "x" * 29_000, name="get_table") for _ in range(12)]

        assert "раздутый_диалог" in _kinds(records)

    def test_самый_крупный_живой_диалог_не_срабатывает(self):
        """Замер 10.10 по всем 101 диалогам: максимум после свёртки —
        92 156 символов, и он отвечает нормально. Порог не должен
        ругаться на здоровое."""
        records = [_msg("user", "вопрос"), _msg("assistant", "y" * 92_000)]

        assert "раздутый_диалог" not in _kinds(records)

    def test_порог_между_здоровым_и_больным(self):
        assert 92_156 < MAX_PROMPT_CHARS < 295_462

    def test_в_замечании_видно_число(self):
        records = [_msg("assistant", "y" * (MAX_PROMPT_CHARS + 10))]

        finding = next(f for f in inspect_dialog("d1", "T", records, now=NOW) if f.kind == "раздутый_диалог")

        assert finding.details["символов"] > MAX_PROMPT_CHARS


class TestЦиклНаОшибке:
    def test_четырнадцать_одинаковых_ошибок(self):
        """Тот самый случай: add_table_row не возвращал row_id, и на
        каждое «ещё подход» выходило update → ошибка → get_table."""
        err = '{"error": "Строка не найдена — сначала вызови get_table"}'
        records = [_msg("tool", err, name="update_table_row", days_ago=1) for _ in range(14)]

        assert "циклит_на_ошибке" in _kinds(records)

    def test_два_повтора_это_норма(self):
        """На живой базе по два «Папка не найдена» / «Заметка не найдена»
        — обычное дело: модель уточняет и идёт дальше."""
        records = [_msg("tool", '{"error": "Папка не найдена"}', name="get_note", days_ago=1) for _ in range(2)]

        assert "циклит_на_ошибке" not in _kinds(records)

    def test_порог_между_нормой_и_патологией(self):
        # Норма x2, патология x5 (лимит веб-поиска) и x14.
        assert 2 < REPEATED_ERROR_TIMES <= 5

    def test_разные_ошибки_не_складываются(self):
        records = [
            _msg("tool", '{"error": "Папка не найдена"}', name="a", days_ago=1),
            _msg("tool", '{"error": "Заметка не найдена"}', name="b", days_ago=1),
            _msg("tool", '{"error": "Пустой текст"}', name="c", days_ago=1),
            _msg("tool", '{"error": "Это не заметка"}', name="d", days_ago=1),
        ]

        assert "циклит_на_ошибке" not in _kinds(records)

    def test_давний_цикл_не_нагоняет_вечно(self):
        """Первый прогон 10.10 нашёл цикл из 14 ошибок, который УЖЕ
        починен, — но следы остаются в диалоге навсегда. Напоминание о
        них каждые шесть часов научило бы смахивать сводку не глядя."""
        err = '{"error": "Строка не найдена"}'
        records = [_msg("tool", err, name="update_table_row", days_ago=LOOKBACK.days + 2) for _ in range(14)]

        assert "циклит_на_ошибке" not in _kinds(records)

    def test_успешные_результаты_не_считаются_ошибками(self):
        records = [_msg("tool", '{"results": []}', name="search_base", days_ago=1) for _ in range(10)]

        assert "циклит_на_ошибке" not in _kinds(records)


class TestХодНеСостоялся:
    def test_сохранённый_отказ(self):
        """Диалог «Telegram»: 26.09 ответ «не получилось», и 10.10 снова —
        две недели между ними никто не заметил."""
        records = [_msg("assistant", "Не получилось получить ответ от LLM-провайдера — попробуй позже", days_ago=1)]

        assert "ход_не_состоялся" in _kinds(records)

    def test_старое_не_поднимаем_каждые_шесть_часов(self):
        """Та же причина, что у _WIPE_LOOKBACK в cleanup.py: старое уже
        разобрано, и шум из него мешает заметить новое."""
        records = [_msg("assistant", "Не получилось получить ответ", days_ago=LOOKBACK.days + 3)]

        assert "ход_не_состоялся" not in _kinds(records)

    def test_запись_без_времени_не_роняет(self):
        assert inspect_dialog("d1", "T", [{"role": "assistant", "content": "Не получилось"}], now=NOW) == []


class TestНепомерныйРезультат:
    def test_мегабайты_из_get_file(self):
        """3.8 МБ base64 в результате get_file убили диалог насовсем."""
        records = [_msg("tool", "a" * 3_795_300, name="get_file", days_ago=1)]

        assert "непомерный_результат" in _kinds(records)

    def test_обычный_дамп_таблицы_не_срабатывает(self):
        records = [_msg("tool", "a" * 9_300, name="get_table", days_ago=1)]

        assert "непомерный_результат" not in _kinds(records)

    def test_один_пример_на_диалог(self):
        records = [_msg("tool", "a" * 1_000_000, name="get_file", days_ago=1) for _ in range(3)]

        findings = [f for f in inspect_dialog("d1", "T", records, now=NOW) if f.kind == "непомерный_результат"]

        assert len(findings) == 1


class TestПроигнорированнаяПодсказка:
    def test_кейтерка(self):
        """Веб-поиск сказал, что слово есть в двух заметках, а ответ был
        лекцией про кейтеринг из общих знаний."""
        records = [
            _msg("user", "А что такое Кейтерка?", days_ago=0.1),
            _msg("tool", '{"results": [], "%s": {"записи": []}}' % OWN_BASE_KEY, name="web_search", days_ago=0.1),
            _msg("assistant", "Кейтеринг — это услуга по организации питания", days_ago=0.1),
        ]

        assert "подсказка_проигнорирована" in _kinds(records)

    def test_если_пошла_смотреть_то_не_замечание(self):
        records = [
            _msg("tool", '{"%s": {}}' % OWN_BASE_KEY, name="web_search", days_ago=0.1),
            _msg("assistant", "", calls=[{"id": "1", "name": "get_note", "arguments": {}}], days_ago=0.1),
            _msg("tool", '{"content": "Marsz Kejterka"}', name="get_note", days_ago=0.1),
            _msg("assistant", "Это собачья прогулка в Познани", days_ago=0.1),
        ]

        assert "подсказка_проигнорирована" not in _kinds(records)

    def test_веб_поиск_без_подсказки_не_замечание(self):
        records = [
            _msg("tool", '{"results": [{"title": "погода"}]}', name="web_search", days_ago=0.1),
            _msg("assistant", "В Познани +12", days_ago=0.1),
        ]

        assert "подсказка_проигнорирована" not in _kinds(records)


class TestУстойчивость:
    def test_пустой_диалог(self):
        assert inspect_dialog("d1", "T", [], now=NOW) == []

    def test_нормальный_диалог_молчит(self):
        """Главное свойство: на здоровом диалоге замечаний быть не должно,
        иначе сторожа перестанут читать."""
        records = [
            _msg("user", "Что у меня сегодня?", days_ago=0.2),
            _msg("assistant", "", calls=[{"id": "1", "name": "list_agenda", "arguments": {}}], days_ago=0.2),
            _msg("tool", '{"entries": []}', name="list_agenda", days_ago=0.2),
            _msg("assistant", "На сегодня ничего не запланировано", days_ago=0.2),
        ]

        assert inspect_dialog("d1", "T", records, now=NOW) == []

    def test_замечание_несёт_название_диалога(self):
        """Без него непонятно, куда идти смотреть."""
        records = [_msg("assistant", "Не получилось получить ответ", days_ago=1)]

        finding = inspect_dialog("abc", "Тренировки", records, now=NOW)[0]

        assert finding.dialog_title == "Тренировки"
        assert finding.dialog_id == "abc"

    def test_словарь_для_инструмента_читаемый(self):
        records = [_msg("assistant", "Не получилось получить ответ", days_ago=1)]

        as_dict = inspect_dialog("abc", "Тренировки", records, now=NOW)[0].as_dict()

        assert as_dict["диалог"] == "Тренировки"
        assert "что" in as_dict


class TestСвопХоста:
    """17.10.2026 после ребута на новое ядро zram не поднялся, и сервер
    остался со свопом только в файле внутри LUKS — тот путь, что вешал
    машину на шесть часов 19.08 и 11.09. Отказ был в журнале, но журнал
    никто не читает; самопроверка уходит в утреннюю сводку."""

    HEALTHY = (
        "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"
        "/srv/encrypted/swapfile                 file\t\t2097148\t\t12\t\t10\n"
        "/dev/zram0                              partition\t2002612\t\t0\t\t100\n"
    )
    NO_ZRAM = (
        "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"
        "/srv/encrypted/swapfile                 file\t\t2097148\t\t12\t\t10\n"
    )

    def test_ровно_тот_случай_17_10(self):
        from app.self_check import inspect_host_swap

        finding = inspect_host_swap(self.NO_ZRAM)

        assert finding is not None
        assert finding.kind == "нет_zram"
        assert "modules-extra" in finding.text, "надо сказать, что проверять"

    def test_здоровый_своп_молчит(self):
        from app.self_check import inspect_host_swap

        assert inspect_host_swap(self.HEALTHY) is None

    def test_до_unlock_свопа_нет_вовсе_и_это_не_тревога(self):
        """До разблокировки тома дискового свопа нет совсем — это штатное
        состояние, а не поломка zram."""
        from app.self_check import inspect_host_swap

        assert inspect_host_swap("Filename\tType\tSize\tUsed\tPriority\n") is None

    def test_пустой_или_недоступный_файл_не_роняет(self):
        from app.self_check import inspect_host_swap

        assert inspect_host_swap("") is None


class TestОфлайнКонфликты:
    """Шаг 1 офлайн-редактирования при конфликте сохраняет правку копией.
    На 17.10 за пятнадцать дней конфликтов не было ни одного, и шаг 2
    (слияние вместо копии) отложили. Это правило — сигнал, что пора."""

    async def _flush(self, db_session, test_user, *, saved=0, conflict=0, failed=0, days_ago=0):
        import uuid as _uuid
        from datetime import datetime, timedelta, timezone

        from app.models import DebugLog

        db_session.add(DebugLog(
            id=_uuid.uuid4(), user_id=test_user.id, event="offline_flush",
            data={"saved": saved, "conflict": conflict, "failed": failed},
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        ))
        await db_session.commit()

    async def test_без_конфликтов_молчит(self, db_session, test_user):
        """Офлайн правили, всё дошло — это не проблема, а норма."""
        from app.self_check import inspect_offline_conflicts

        await self._flush(db_session, test_user, saved=3)
        await self._flush(db_session, test_user, saved=1)

        assert await inspect_offline_conflicts(db_session) is None

    async def test_конфликт_всплывает(self, db_session, test_user):
        from app.self_check import inspect_offline_conflicts

        await self._flush(db_session, test_user, saved=2, conflict=1)
        await self._flush(db_session, test_user, conflict=2)

        finding = await inspect_offline_conflicts(db_session)

        assert finding is not None
        assert finding.details["конфликтов"] == 3
        assert finding.details["отправок"] == 2
        assert "не через Yjs" in finding.text, "надо сразу сказать, по какой схеме делать"

    async def test_старые_конфликты_не_нагоняют(self, db_session, test_user):
        """Та же неделя, что у остальных проверок: разобранное прошлое не
        должно висеть в сводке вечно."""
        from app.self_check import LOOKBACK, inspect_offline_conflicts

        await self._flush(db_session, test_user, conflict=5, days_ago=LOOKBACK.days + 2)

        assert await inspect_offline_conflicts(db_session) is None

    async def test_кривые_данные_не_роняют(self, db_session, test_user):
        import uuid as _uuid

        from app.models import DebugLog
        from app.self_check import inspect_offline_conflicts

        db_session.add(DebugLog(id=_uuid.uuid4(), user_id=test_user.id, event="offline_flush", data={}))
        await db_session.commit()

        assert await inspect_offline_conflicts(db_session) is None
