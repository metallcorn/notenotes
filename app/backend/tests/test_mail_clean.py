from app.mail_clean import clean_forwarded_text, clean_subject

GMAIL_DOUBLE_FORWARD = """---------- Forwarded message ---------
Od: Anna Kowalska <anna@example.com>
Date: pon., 5 paź 2026, 09:46
Subject: Fwd: Twoje bilety na koncert
To: jan <jan@example.com>




---------- Forwarded message ---------
From: Sklep biletowy <noreply@example.org>
Date: Mon, 5 Oct 2026 at 09:44
Subject: Twoje bilety na koncert
To: <anna@example.com>


Potwierdzenie zamówienia 12345.
<https://mandrillapp.com/track/click/30490463/www.example.org?p=eyJzIjoiQk01ZDk1aUQwdEJJNlVNVVlUQTdjclZHb1BvIiwidiI6MiwicCI6IntcInVcIjozMDQ5MDQ2MyxcInZcIjoyLFwidXJsXCI6XCJodHRwczpcXFwvXFxcL3d3dy5lYmlsZXQucGxcIixcImlkXCI6XCJiNDZhYmE4YzFjYzE0YjlmYjUzMDU3ZjBjNzkzZTAwNlwiLFwidXJsX2lkc1wiOltcImI2ZTM2NmVjOWJmZjVhZDE4ZWRiNmQ1YjQ4ODQxZjMyYzJjMTVlYzZcIl0sXCJtc2dfdHNcIjoxNzkxMTg2Mjg4fSJ9>
Cześć Anna,

bilety w załączniku. Szczegóły: https://www.example.org/zamowienie/12345
"""


def test_strips_forward_separators_and_header_blocks():
    cleaned = clean_forwarded_text(GMAIL_DOUBLE_FORWARD)
    assert "Forwarded message" not in cleaned
    assert "Od:" not in cleaned and "From:" not in cleaned and "Subject:" not in cleaned and "To:" not in cleaned
    assert cleaned.startswith("Potwierdzenie zamówienia 12345.")
    assert "Cześć Anna," in cleaned


def test_drops_tracker_links_but_keeps_real_ones():
    cleaned = clean_forwarded_text(GMAIL_DOUBLE_FORWARD)
    assert "mandrillapp.com" not in cleaned
    assert "https://www.example.org/zamowienie/12345" in cleaned


def test_collapses_blank_runs():
    cleaned = clean_forwarded_text("a\n\n\n\n\nb")
    assert cleaned == "a\n\nb"


def test_outlook_header_block_without_separator():
    text = "From: Jan Kowalski <jan@example.com>\nSent: Monday\nTo: anna@example.com\nSubject: Plan\n\nTreść wiadomości."
    assert clean_forwarded_text(text) == "Treść wiadomości."


def test_plain_text_untouched():
    text = "Просто заметка.\n\nВторой абзац с From: внутри предложения не трогаем."
    assert clean_forwarded_text(text) == text


def test_clean_subject():
    assert clean_subject("Fwd: Fwd: Re: Билеты") == "Билеты"
    assert clean_subject("FW: Odp: Umowa") == "Umowa"
    assert clean_subject("Обычная тема") == "Обычная тема"
    assert clean_subject("Fwd:") == "Fwd:"
