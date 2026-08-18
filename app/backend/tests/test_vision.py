from app.vision import _split_ticket_marker


def test_ticket_marker_plain():
    is_ticket, rest = _split_ticket_marker("БИЛЕТ: да\n\nЭлектронный билет на рейс LOT 3945.")
    assert is_ticket is True
    assert rest.startswith("Электронный билет")


def test_ticket_marker_no():
    is_ticket, rest = _split_ticket_marker("БИЛЕТ: нет\n\nФотография кота на подоконнике.")
    assert is_ticket is False
    assert rest.startswith("Фотография кота")


def test_ticket_marker_markdown_bold():
    # Реальный найденный случай: модель обернула маркер в markdown вместо
    # голого текста, как просили в промпте — раньше строгий регэксп это не ловил.
    is_ticket, _ = _split_ticket_marker("**БИЛЕТ: да**\n\nПосадочный талон авиакомпании.")
    assert is_ticket is True


def test_ticket_marker_heading_style():
    is_ticket, _ = _split_ticket_marker("### БИЛЕТ: да\n\nЖД-билет.")
    assert is_ticket is True


def test_ticket_fallback_when_marker_missing_but_description_says_ticket():
    # Реальный найденный случай: модель вообще пропустила маркерную строку,
    # но в самом начале описания честно назвала изображение билетом.
    is_ticket, rest = _split_ticket_marker(
        "Электронный билет авиакомпании LOT Polish Airlines на рейс из Варшавы в Познань."
    )
    assert is_ticket is True
    assert rest.startswith("Электронный билет")


def test_ticket_fallback_boarding_pass_wording():
    is_ticket, _ = _split_ticket_marker("Посадочный талон на автобус, место 14.")
    assert is_ticket is True


def test_ticket_fallback_does_not_trigger_on_unrelated_mention():
    # Осторожный фолбэк: билет должен упоминаться В НАЧАЛЕ описания, не
    # где угодно — иначе случайное упоминание слова "билет" в середине
    # обычной фотографии ложно классифицировалось бы как билет.
    is_ticket, rest = _split_ticket_marker(
        "Фотография стола с ноутбуком и чашкой кофе. Рядом лежит забытый билет в кино."
    )
    assert is_ticket is False
    assert rest.startswith("Фотография стола")
