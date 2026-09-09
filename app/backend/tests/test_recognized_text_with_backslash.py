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


# --- сломанная кодировка шрифта в PDF ------------------------------------

def test_broken_font_encoding_is_detected():
    """Реальный случай (2026-09-09): страховой полис отдавал
    «2GSRZLHG]LDOQR» вместо «Odpowiedzialność» — встроенный шрифт со
    смещением. Текстовый слой формально есть, поэтому запасной путь через
    vision не включался, и пользователь получал в заметке кашу."""
    from app.pdf_processing import looks_like_broken_encoding

    garbage = "2GSRZLHG]LDOQR F\\ZLOQD 3HUVRQDO OLDELOLW\\ 3R]RVWDZLRQH PLHQLH /HIRUPD " * 5
    assert looks_like_broken_encoding(garbage)


def test_normal_documents_are_not_mistaken_for_broken():
    """Цена ложного срабатывания — лишний прогон через vision, то есть
    деньги и минуты. Проверяем на том, что реально лежит в базе."""
    from app.pdf_processing import looks_like_broken_encoding

    polish = "Odpowiedzialność cywilna Personal liability Pozostawione mienie ubezpieczenie podróży " * 5
    russian = "Полис страхования путешествий AXA Assistance номер 1234509876 сумма 1500000 PLN " * 5
    table = "| Pole | Wartość |\n|---|---|\n| Data | 28.8.2026 |\n| Godzina | 22:00 |\n" * 6
    # Код в документе — главная ловушка: скобки и слэши там законны, и по
    # одному признаку «невозможных символов» он давал 21% ложных.
    code = "const x = arr[0]; if (a || b) { return `${x}`; }  path C:\\Users\\test " * 5

    for text in (polish, russian, table, code):
        assert not looks_like_broken_encoding(text), text[:60]


def test_short_text_is_never_judged():
    """Документ из пары артикулов даёт любые доли — судить по нему нельзя."""
    from app.pdf_processing import looks_like_broken_encoding

    assert not looks_like_broken_encoding("AXA-4585 PLN 1500 \\Z ]X[")


# --- обход всех мест, где чужой текст попадает в «значимый» контекст -----
# Проведён 2026-09-09 после третьего за три дня случая (\Z в подстановке,
# ::bytea в векторном поиске). Ниже — то, что обход нашёл; остальное
# проверено и оказалось чистым (см. сообщение коммита).

def test_like_wildcards_from_user_are_escaped():
    """Поиск по названию: «%» и «_» из запроса не должны работать как
    подстановочные символы SQL. Инъекции тут нет (запрос параметризован),
    это про правильность выдачи — «50%» находил бы вообще всё."""
    from app.routers.items import _escape_like

    assert _escape_like("50%") == r"50\%"
    assert _escape_like("файл_1") == r"файл\_1"
    # Обратный слэш ПЕРВЫМ, иначе он экранировал бы то, что сам же вписал.
    assert _escape_like("путь\\дом") == "путь\\\\дом"
    assert _escape_like("обычный текст") == "обычный текст"


def test_telegram_link_label_brackets_are_escaped():
    """Квадратные скобки в тексте ссылки из Telegram ломали markdown:
    «[смотри [тут]](url)» разъезжается, и в заметке остаётся мусор."""
    from app.telegram_bot import _entities_to_markdown

    text = "смотри [тут]"
    entities = [{"type": "text_link", "offset": 0, "length": len(text), "url": "https://example.com"}]
    result = _entities_to_markdown(text, entities)

    assert result == r"[смотри \[тут\]](https://example.com)"
