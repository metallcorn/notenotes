"""Пересланное из Telegram → Markdown заметки: разметка entities с пробелами
по краям, переносы строк, дата оригинала и ответ бота «куда легло».
Данные вымышленные."""

import uuid
from datetime import datetime, timezone

from app.models import Item
from app.telegram_bot import (
    _derive_title,
    _entities_to_markdown,
    _forward_written_at,
    _handle_forward_batch,
    _hard_breaks,
    _message_markdown,
    _saved_reply,
)


def test_bold_with_surrounding_spaces_keeps_marks_tight():
    # Telegram включил в жирный спан пробел перед переносом: «**ul. X 1 **»
    # в Markdown — не разметка, звёздочки оставались в заметке буквально.
    text = "Adres:\nul. Przykładowa 1 \nGabinet"
    entities = [{"type": "bold", "offset": 7, "length": 18}]
    assert _entities_to_markdown(text, entities) == "Adres:\n**ul. Przykładowa 1** \nGabinet"


def test_bold_span_of_only_spaces_is_left_alone():
    assert _entities_to_markdown("a   b", [{"type": "bold", "offset": 1, "length": 3}]) == "a   b"


def test_hard_breaks_join_lines_inside_paragraph_only():
    md = "Adres\nul. Przykładowa 1\n\nKod: 1234\n- pierwszy\n- drugi\n# Tytuł\nTekst"
    assert _hard_breaks(md) == "Adres\\\nul. Przykładowa 1\n\nKod: 1234\n- pierwszy\n- drugi\n# Tytuł\nTekst"


def test_hard_breaks_skip_code_fences_and_existing_breaks():
    md = "Przed\\\nlinia\n```\nraz\ndwa\n```\npo"
    assert _hard_breaks(md) == "Przed\\\nlinia\n```\nraz\ndwa\n```\npo"


def test_message_markdown_combines_entities_and_breaks():
    text = "Tytuł przelewu\nKONSULTACJA\nIBAN: 00 1111"
    assert _message_markdown(text, None) == "Tytuł przelewu\\\nKONSULTACJA\\\nIBAN: 00 1111"
    assert _message_markdown("", None) == ""


def test_derive_title_drops_trailing_hard_break():
    assert _derive_title("Wysyłam adres\\\n**ul. Przykładowa 1**") == "Wysyłam adres"


def test_forward_written_at_prefers_origin_and_takes_earliest():
    messages = [
        {"forward_origin": {"type": "user", "date": 1_800_000_600}},
        {"forward_date": 1_800_000_000},
        {"text": "bez pересылки"},
    ]
    assert _forward_written_at(messages) == datetime.fromtimestamp(1_800_000_000, tz=timezone.utc)
    assert _forward_written_at([{"text": "x"}]) is None
    assert _forward_written_at([{"forward_date": "вчера"}]) is None


async def test_forward_batch_stores_origin_date_and_replies_with_place(auth_client, db_session, test_user):
    space_id = uuid.UUID((await auth_client.post("/api/spaces", json={"name": "Telegram"})).json()["id"])
    written = int(datetime(2026, 3, 9, 19, 15, tzinfo=timezone.utc).timestamp())
    messages = [
        {
            "text": "Wysyłam adres\nul. Przykładowa 1 \nGabinet Lorem",
            "entities": [{"type": "bold", "offset": 14, "length": 18}],
            "forward_origin": {"type": "user", "date": written, "sender_user": {"first_name": "Jan"}},
        },
        {"text": "Dobry wieczór! Jutro konsultacja.", "forward_origin": {"type": "user", "date": written + 60}},
    ]
    item = await _handle_forward_batch(db_session, messages, space_id, test_user.id, "Jan")
    assert isinstance(item, Item)
    assert item.title == "Wysyłam adres"
    assert item.properties["source"] == {
        "kind": "telegram_forward",
        "sender": "Jan",
        "written_at": "2026-03-09T19:15:00+00:00",
    }
    lines = item.content.split("\n")
    assert lines[0].startswith("_Переслано из Telegram · Jan · 09.03.2026, 20:15_")
    assert "**ul. Przykładowa 1** \\" in item.content
    assert "Wysyłam adres\\\n" in item.content
    assert "\n\nDobry wieczór! Jutro konsultacja." in item.content

    text, markup = await _saved_reply(db_session, item)
    assert text == "Сохранено ✅ «Wysyłam adres»\nTelegram › Jan"
    button = markup["inline_keyboard"][0][0]
    assert button["text"] == "Открыть" and button["web_app"]["url"].endswith(f"/?item={item.id}")


async def test_direct_album_without_forward_has_no_source(auth_client, db_session, test_user):
    space_id = uuid.UUID((await auth_client.post("/api/spaces", json={"name": "Dom"})).json()["id"])
    item = await _handle_forward_batch(db_session, [{"text": "Notatka\nz dwóch linii"}], space_id, test_user.id, None)
    assert item is not None and "source" not in item.properties
    assert item.content == "Notatka\\\nz dwóch linii"
    assert await _handle_forward_batch(db_session, [{"sticker": {}}], space_id, test_user.id, None) is None
