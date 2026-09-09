"""Распознанный текст с обратным слэшем не должен ронять обработчик.

Реальный отказ (2026-09-09, боевой сервер). Пользователь загрузил в
заметку три PDF: два распознались, третий — страховой полис AXA — навсегда
завис в состоянии «распознаётся». Выглядело как «распознавание идёт очень
долго», хотя на деле не шло вовсе: обработчик рухнул и больше не
возвращался.

    File "/app/app/pdf_processing.py", line 104, in _replace_document_card
        new_content, n = pattern.subn(new_card_html, item.content)
    re.error: bad escape \\Z at position 228

Причина: re.subn разбирает СТРОКУ ЗАМЕНЫ как шаблон, где обратный слэш
имеет особый смысл. В распознанном тексте он встретился как обычный
символ. Лечится заменой-функцией: она возвращает текст как есть.

Тот же класс, что баг с text::bytea в векторном поиске двумя днями
раньше: чужой текст подставляется туда, где обратный слэш что-то значит.
"""

import re

import pytest

# Последовательности, на которых re.subn падает или молча портит текст,
# если замену передать строкой. \Z — ровно то, что было в полисе.
DANGEROUS = [
    r"Раздел \Z полиса",
    r"путь C:\Users\dane",
    r"формула \d+ и \1 обратная ссылка",
    "хвост со слэшем \\",
]


def test_string_replacement_is_the_broken_way():
    """Фиксируем ПРИЧИНУ на том самом входе, что уронил обработчик.

    Тест намеренно описывает сломанное поведение стандартной библиотеки —
    иначе через год будет непонятно, зачем в коде lambda вместо строки, и
    её «упростят» обратно.

    Проверяем именно \\Z: не всякий обратный слэш ломает подстановку
    (одиночный в конце, например, проходит целым — проверено), поэтому
    заявлять «любой слэш опасен» было бы неправдой. Опасны escape-
    последовательности, и в полисе попалась ровно такая.
    """
    pattern = re.compile(r"PLACEHOLDER")
    card = '<div data-text="Раздел \\Z полиса"></div>'
    with pytest.raises(re.error, match="bad escape"):
        pattern.subn(card, "до PLACEHOLDER после")


@pytest.mark.parametrize("recognized", DANGEROUS)
def test_function_replacement_keeps_text_intact(recognized):
    """А так, как теперь в pdf_processing.py и vision.py, — цел и не падает."""
    pattern = re.compile(r"PLACEHOLDER")
    card = f'<div data-text="{recognized}"></div>'
    result, n = pattern.subn(lambda _m: card, "до PLACEHOLDER после")
    assert n == 1
    assert result == f"до {card} после"


def test_pdf_and_vision_use_function_replacement():
    """Сторожим оба места сразу: подстановка распознанного текста строкой —
    это тот самый отказ, а не стилистическая мелочь."""
    import inspect

    from app import pdf_processing, vision

    for module in (pdf_processing, vision):
        src = inspect.getsource(module)
        for line in src.splitlines():
            if ".subn(" in line and "lambda" not in line:
                pytest.fail(
                    f"{module.__name__}: подстановка строкой в subn вернулась — "
                    f"обратный слэш в распознанном тексте снова уронит обработчик:\n{line.strip()}"
                )
