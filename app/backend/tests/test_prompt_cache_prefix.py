"""Кэшируемый префикс системного промпта не должен рваться.

Кэш промпта у провайдера совпадает по ПРЕФИКСУ и удешевляет попавшие в
него входные токены до 10% тарифа. Проверено на живом API Mistral: при
неизменном префиксе cached_tokens = 8688 из 8716.

Ловушка, которая была в коде до 2026-09-05: строка «Текущие дата и время:
...» стояла ПЕРВОЙ в системном промпте и менялась каждую минуту. Префикс
расходился на первых же токенах, и все ~11 тысяч символов статичных
правил не кэшировались вообще. Тест сторожит ровно это: всё изменчивое
обязано быть в конце.
"""

from app.routers.dialogs import _build_system_prompt


def _prompt(**kw):
    base = dict(
        memory_facts=[], custom_instructions="", enabled_tools=set(),
        disabled_tools=set(), is_fresh_start=False,
        client_timezone="Europe/Warsaw", high_stakes=False,
    )
    base.update(kw)
    return _build_system_prompt(
        base["memory_facts"], base["custom_instructions"], base["enabled_tools"],
        base["disabled_tools"], base["is_fresh_start"], base["client_timezone"],
        base["high_stakes"],
    )


def test_timestamp_is_at_the_end_not_the_start():
    p = _prompt()
    assert "Текущие дата и время" in p
    # Не в первой трети — иначе кэшируемого префикса почти не остаётся.
    assert p.index("Текущие дата и время") > len(p) * 0.66


def test_static_prefix_is_identical_across_users_and_time():
    # Два «разных запроса» отличаются только тем, что меняется от вызова к
    # вызову. Общий префикс обязан покрывать основную часть промпта.
    a = _prompt()
    b = _prompt(memory_facts=["Пользователь живёт в Познани"])

    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    # Больше половины короткого из двух промптов — общий префикс.
    assert common > min(len(a), len(b)) * 0.5, (
        f"общий префикс всего {common} символов из {min(len(a), len(b))} — "
        "что-то изменчивое уползло в начало промпта и рвёт кэш"
    )


def test_conditional_fragments_do_not_break_the_prefix():
    # Условные куски (онбординг, «дорогая» тема) добавляются ПОСЛЕ
    # статичной базы, поэтому её префикс они не трогают.
    plain = _prompt()
    with_extra = _prompt(is_fresh_start=True, high_stakes=True)
    assert with_extra.startswith(plain[:2000])
