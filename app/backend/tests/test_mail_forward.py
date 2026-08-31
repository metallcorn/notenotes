from app.mail_forward import first_other_recipient, is_own_address, parse_forwarded_sender


# --- is_own_address ----------------------------------------------------

def test_is_own_address_matches_case_insensitively():
    assert is_own_address("Ivan@Gmail.com", ["ivan@gmail.com"]) is True


def test_is_own_address_parses_display_name_wrapper():
    assert is_own_address("Ivan Ivanov <ivan@gmail.com>", ["ivan@gmail.com"]) is True


def test_is_own_address_no_match():
    assert is_own_address("stranger@example.com", ["ivan@gmail.com"]) is False


def test_is_own_address_empty_list():
    assert is_own_address("ivan@gmail.com", []) is False


# --- parse_forwarded_sender ----------------------------------------------
# Реальный найденный случай: пользователь пересылает себе письмо от
# Piotr Zieliński — тело содержит блок пересылки Gmail с исходным From:.

def test_parse_forwarded_sender_gmail_en():
    body = (
        "---------- Forwarded message ---------\n"
        "From: Piotr Zieliński <piotr.zielinski@example.com>\n"
        "Date: Mon, 1 Sep 2026 at 10:00\n"
        "Subject: Something interesting\n"
        "To: <apple-river-tiger@mail.notenotes.example>\n\n"
        "Оригинальный текст письма.\n"
    )
    name, email = parse_forwarded_sender(body)
    assert name == "Piotr Zieliński"
    assert email == "piotr.zielinski@example.com"


def test_parse_forwarded_sender_gmail_ru():
    body = (
        "---------- Пересланное сообщение ---------\n"
        "От кого: Томаш Новак <tomasz.nowak@example.pl>\n"
        "Дата: 1 сентября 2026 г., 10:00\n"
        "Тема: Что-то важное\n"
        "Кому: apple-river-tiger@mail.notenotes.example\n\n"
        "Текст письма.\n"
    )
    name, email = parse_forwarded_sender(body)
    assert name == "Томаш Новак"
    assert email == "tomasz.nowak@example.pl"


def test_parse_forwarded_sender_apple_mail():
    body = (
        "Begin forwarded message:\n\n"
        "From: Anna Kowalska <anna.kowalska@example.com>\n"
        "Subject: Re: Meeting\n"
        "Date: 1 September 2026 at 10:00:00\n"
        "To: me@icloud.com\n\n"
        "Текст письма.\n"
    )
    name, email = parse_forwarded_sender(body)
    assert name == "Anna Kowalska"
    assert email == "anna.kowalska@example.com"


def test_parse_forwarded_sender_outlook_legacy_mailto_format():
    body = (
        "-----Original Message-----\n"
        "From: John Smith [mailto:john.smith@example.com]\n"
        "Sent: Monday, September 1, 2026 10:00 AM\n"
        "To: someone@example.com\n"
        "Subject: FW: Invoice\n\n"
        "Текст письма.\n"
    )
    name, email = parse_forwarded_sender(body)
    assert name == "John Smith"
    assert email == "john.smith@example.com"


def test_parse_forwarded_sender_no_marker_returns_none():
    body = "Обычное письмо без пересылки, просто текст с упоминанием From: где-то в середине."
    assert parse_forwarded_sender(body) == (None, None)


def test_parse_forwarded_sender_marker_without_from_line_returns_none():
    body = "---------- Forwarded message ---------\nВсё сломано, нет заголовков вообще.\n"
    assert parse_forwarded_sender(body) == (None, None)


# --- first_other_recipient -----------------------------------------------

def test_first_other_recipient_skips_own_and_mail_domain():
    to_header = "Ivan Ivanov <ivan@gmail.com>, apple-river-tiger@mail.notenotes.example"
    cc_header = "Alina <alina@example.com>"
    name, email = first_other_recipient(to_header, cc_header, ["ivan@gmail.com"], "mail.notenotes.example")
    assert name == "Alina"
    assert email == "alina@example.com"


def test_first_other_recipient_picks_first_non_own_in_to():
    to_header = "ivan@gmail.com, Colleague <colleague@example.com>, other@example.com"
    name, email = first_other_recipient(to_header, "", ["ivan@gmail.com"], "mail.notenotes.example")
    assert name == "Colleague"
    assert email == "colleague@example.com"


def test_first_other_recipient_none_when_only_own_and_domain():
    to_header = "ivan@gmail.com, apple-river-tiger@mail.notenotes.example"
    assert first_other_recipient(to_header, "", ["ivan@gmail.com"], "mail.notenotes.example") == (None, None)


def test_first_other_recipient_empty_headers():
    assert first_other_recipient("", "", ["ivan@gmail.com"], "mail.notenotes.example") == (None, None)
