import hashlib
import hmac

from app.core.config import get_settings

_SIGNING_KEY = "test-mailgun-signing-key"


def _signed_form(**fields) -> dict:
    timestamp = "1700000000"
    token = "abc123token"
    signature = hmac.new(_SIGNING_KEY.encode(), f"{timestamp}{token}".encode(), hashlib.sha256).hexdigest()
    return {"timestamp": timestamp, "token": token, "signature": signature, **fields}


async def test_webhook_creates_note_for_known_address(client, db_session, test_user, monkeypatch):
    from app.models import EmailInbox, Space, SpaceMember

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)

    space = Space(name="Почта", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(EmailInbox(user_id=test_user.id, local_part="mytoken123", space_id=space.id))
    await db_session.commit()

    form = _signed_form(
        recipient="mytoken123@mail.notenotes.example",
        subject="Важное письмо",
        **{"stripped-text": "Содержимое письма"},
    )
    r = await client.post("/api/mail/webhook", data=form)
    assert r.status_code == 200 and r.json() == {"ok": True}

    from sqlalchemy import select
    from app.models import Item

    item = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalar_one()
    assert item.title == "Важное письмо"
    assert item.content == "Содержимое письма"


async def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)

    form = {
        "timestamp": "1700000000",
        "token": "abc123token",
        "signature": "not-the-real-signature",
        "recipient": "mytoken123@mail.notenotes.example",
    }
    r = await client.post("/api/mail/webhook", data=form)
    assert r.status_code == 401


async def test_webhook_unknown_local_part_returns_200_without_creating(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)

    from sqlalchemy import func, select

    from app.models import Item

    # Считаем ДО и ПОСЛЕ, а не «в базе ровно ноль записей». Смысл теста —
    # «письмо на неизвестный адрес не создаёт заметку», и он выражается
    # именно так. Прежняя формулировка требовала, чтобы вся база была
    # пуста, и потому изредка падала на полном прогоне от любой посторонней
    # записи — поймано дважды за шесть прогонов, при этом в одиночку и с
    # соседними файлами тест проходил.
    async def items_count() -> int:
        return (await db_session.execute(select(func.count()).select_from(Item))).scalar_one()

    before = await items_count()

    form = _signed_form(recipient="doesnotexist@mail.notenotes.example", subject="X")
    r = await client.post("/api/mail/webhook", data=form)
    assert r.status_code == 200 and r.json() == {"ok": True}

    assert await items_count() == before


async def test_webhook_groups_notes_by_sender_folder(client, db_session, test_user, monkeypatch):
    from app.models import EmailInbox, Folder, Item, Space, SpaceMember

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)

    space = Space(name="Почта", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(EmailInbox(user_id=test_user.id, local_part="mytoken123", space_id=space.id))
    await db_session.commit()

    for subject in ("Письмо 1", "Письмо 2"):
        form = _signed_form(
            recipient="mytoken123@mail.notenotes.example",
            subject=subject,
            **{"from": "Иван Иванов <ivan@example.com>"},
        )
        r = await client.post("/api/mail/webhook", data=form)
        assert r.status_code == 200

    from sqlalchemy import select

    folders = (await db_session.execute(select(Folder).where(Folder.space_id == space.id))).scalars().all()
    assert len(folders) == 1
    assert folders[0].name == "Иван Иванов"

    items = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalars().all()
    assert len(items) == 2
    assert all(item.folder_id == folders[0].id for item in items)


async def test_webhook_forwarded_by_self_groups_by_original_sender(client, db_session, test_user, monkeypatch):
    # Реальная жалоба: пересылаешь себе письмо на notenotes-адрес — папка
    # называется по собственному имени пользователя (From: — это он сам),
    # а не по реальному отправителю оригинала, хотя тот виден в тексте
    # (пересланный Gmail-блок с "From: ...").
    from app.models import EmailInbox, Folder, Item, Space, SpaceMember

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)
    monkeypatch.setattr(get_settings(), "mail_domain", "mail.notenotes.example")

    space = Space(name="Почта", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(
        EmailInbox(user_id=test_user.id, local_part="mytoken123", space_id=space.id, own_addresses=["me@gmail.com"])
    )
    await db_session.commit()

    body = (
        "---------- Forwarded message ---------\n"
        "From: Piotr Zieliński <piotr.zielinski@example.com>\n"
        "Date: Mon, 1 Sep 2026 at 10:00\n"
        "Subject: Что-то интересное\n"
        "To: mytoken123@mail.notenotes.example\n\n"
        "Текст письма.\n"
    )
    form = _signed_form(
        recipient="mytoken123@mail.notenotes.example",
        subject="Fwd: Что-то интересное",
        **{"from": "Me <me@gmail.com>", "stripped-text": body},
    )
    r = await client.post("/api/mail/webhook", data=form)
    assert r.status_code == 200

    from sqlalchemy import select

    folders = (await db_session.execute(select(Folder).where(Folder.space_id == space.id))).scalars().all()
    assert len(folders) == 1
    assert folders[0].name == "Piotr Zieliński"

    item = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalar_one()
    assert item.folder_id == folders[0].id


async def test_webhook_self_sent_cc_groups_by_recipient(client, db_session, test_user, monkeypatch):
    # Второй кейс той же жалобы: письмо, которое пользователь пишет САМ и
    # ставит notenotes-адрес в копию — не пересылка, но собеседник должен
    # определяться так же (получатель, не сам пользователь).
    from app.models import EmailInbox, Folder, Item, Space, SpaceMember

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)
    monkeypatch.setattr(get_settings(), "mail_domain", "mail.notenotes.example")

    space = Space(name="Почта", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(
        EmailInbox(user_id=test_user.id, local_part="mytoken123", space_id=space.id, own_addresses=["me@gmail.com"])
    )
    await db_session.commit()

    form = _signed_form(
        recipient="mytoken123@mail.notenotes.example",
        subject="Договорились на среду",
        **{
            "from": "Me <me@gmail.com>",
            "stripped-text": "Обычное письмо без пересылки, просто текст.",
            "To": "Alina <alina@example.com>",
            "Cc": "mytoken123@mail.notenotes.example",
        },
    )
    r = await client.post("/api/mail/webhook", data=form)
    assert r.status_code == 200

    from sqlalchemy import select

    folders = (await db_session.execute(select(Folder).where(Folder.space_id == space.id))).scalars().all()
    assert len(folders) == 1
    assert folders[0].name == "Alina"

    item = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalar_one()
    assert item.folder_id == folders[0].id


async def test_webhook_self_sent_with_no_signal_falls_back_to_default_folder(client, db_session, test_user, monkeypatch):
    # Свой адрес, но ни пересылки, ни постороннего получателя — не должно
    # падать, просто нечего определить.
    from app.models import EmailInbox, Folder, Space, SpaceMember

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)

    space = Space(name="Почта", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(
        EmailInbox(user_id=test_user.id, local_part="mytoken123", space_id=space.id, own_addresses=["me@gmail.com"])
    )
    await db_session.commit()

    form = _signed_form(
        recipient="mytoken123@mail.notenotes.example",
        subject="Заметка себе",
        **{"from": "Me <me@gmail.com>", "stripped-text": "Просто заметка себе, без пересылки и без других получателей."},
    )
    r = await client.post("/api/mail/webhook", data=form)
    assert r.status_code == 200

    from sqlalchemy import select

    folders = (await db_session.execute(select(Folder).where(Folder.space_id == space.id))).scalars().all()
    assert len(folders) == 1
    assert folders[0].name == "Без отправителя"


async def test_webhook_queues_pdf_attachment_for_ocr(client, db_session, test_user, monkeypatch):
    # Реальная жалоба: вложения письма падали голыми markdown-ссылками —
    # ничего не ставило PDF в очередь распознавания, как это делает
    # обычная загрузка (routers/uploads.py) и Telegram-бот.
    from app.models import EmailInbox, Item, Space, SpaceMember, Upload

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)

    space = Space(name="Почта", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(EmailInbox(user_id=test_user.id, local_part="mytoken123", space_id=space.id))
    await db_session.commit()

    form = _signed_form(recipient="mytoken123@mail.notenotes.example", subject="Счёт", **{"attachment-count": "1"})
    files = {"attachment-1": ("invoice.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
    r = await client.post("/api/mail/webhook", data=form, files=files)
    assert r.status_code == 200

    from sqlalchemy import select

    upload = (await db_session.execute(select(Upload).where(Upload.space_id == space.id))).scalar_one()
    assert upload.transcription_status == "pending"

    item = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalar_one()
    assert f'data-url="/api/uploads/{upload.id}"' in item.content


async def test_webhook_saves_attachment_and_links_it(client, db_session, test_user, monkeypatch):
    from app.models import EmailInbox, Space, SpaceMember

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)

    space = Space(name="Почта", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(EmailInbox(user_id=test_user.id, local_part="mytoken123", space_id=space.id))
    await db_session.commit()

    form = _signed_form(recipient="mytoken123@mail.notenotes.example", subject="С вложением", **{"attachment-count": "1"})
    files = {"attachment-1": ("photo.png", b"\x89PNG fake bytes", "image/png")}
    r = await client.post("/api/mail/webhook", data=form, files=files)
    assert r.status_code == 200

    from sqlalchemy import select
    from app.models import Item, Upload

    item = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalar_one()
    upload = (await db_session.execute(select(Upload).where(Upload.space_id == space.id))).scalar_one()
    assert upload.filename == "photo.png"
    assert f"/api/uploads/{upload.id}" in item.content


# --- повторная доставка одного письма ------------------------------------
#
# Найдено на живой базе 10.10 — две пары заметок с интервалом РОВНО
# 10 минут 10 секунд в обоих случаях («Fwd: Налоги 08-2026» 14:49:22 и
# 14:59:32; «Fwd: Налоги за 07-2026» 21:09:21 и 21:19:32). Это не человек
# переслал дважды, это расписание повторов Mailgun: обработчик делает
# тяжёлую работу прямо в запросе и не успевает ответить.


async def _inbox(db_session, test_user):
    from app.models import EmailInbox, Space, SpaceMember

    space = Space(name="Почта", owner_id=test_user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=test_user.id))
    db_session.add(EmailInbox(user_id=test_user.id, local_part="mytoken123", space_id=space.id))
    await db_session.commit()
    return space


async def test_повторная_доставка_не_создаёт_второй_заметки(client, db_session, test_user, monkeypatch):
    from sqlalchemy import select

    from app.models import Item

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)
    space = await _inbox(db_session, test_user)

    def form(text):
        return _signed_form(
            recipient="mytoken123@mail.notenotes.example",
            subject="Fwd: Налоги 08-2026",
            **{"stripped-text": text, "Message-Id": "<CAF=abc123@mail.gmail.com>"},
        )

    first = await client.post("/api/mail/webhook", data=form("Налоги за август"))
    # Содержимое второй доставки ОТЛИЧАЕТСЯ — именно это сбивало со следа:
    # текст письма один, а блоки вложений содержат новый id загрузки.
    second = await client.post("/api/mail/webhook", data=form("Налоги за август и ещё немного"))

    assert first.json() == {"ok": True}
    assert second.json() == {"ok": True, "duplicate": True}, "Mailgun должен считать доставку успешной"
    items = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalars().all()
    assert len(items) == 1


async def test_разные_письма_с_одной_темой_остаются_двумя(client, db_session, test_user, monkeypatch):
    """«Fwd: Przedłużenie umowy najmu» в живой базе встречается трижды за
    двенадцать дней — это РАЗНЫЕ письма с одной темой, и схлопывать их по
    теме было бы потерей."""
    from sqlalchemy import select

    from app.models import Item

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)
    space = await _inbox(db_session, test_user)

    for n in (1, 2, 3):
        await client.post("/api/mail/webhook", data=_signed_form(
            recipient="mytoken123@mail.notenotes.example",
            subject="Fwd: Przedłużenie umowy najmu",
            **{"stripped-text": f"письмо {n}", "Message-Id": f"<msg-{n}@mail.gmail.com>"},
        ))

    items = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalars().all()
    assert len(items) == 3


async def test_письмо_без_message_id_не_теряется(client, db_session, test_user, monkeypatch):
    """Заголовок обязателен по RFC, но мы не вправе выкидывать письмо,
    если его нет: потерять письмо хуже, чем завести дубль."""
    from sqlalchemy import select

    from app.models import Item

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)
    space = await _inbox(db_session, test_user)

    for _ in range(2):
        await client.post("/api/mail/webhook", data=_signed_form(
            recipient="mytoken123@mail.notenotes.example",
            subject="Без идентификатора",
            **{"stripped-text": "текст"},
        ))

    items = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalars().all()
    assert len(items) == 2


async def test_регистр_заголовка_не_важен(client, db_session, test_user, monkeypatch):
    from sqlalchemy import select

    from app.models import Item

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)
    space = await _inbox(db_session, test_user)

    await client.post("/api/mail/webhook", data=_signed_form(
        recipient="mytoken123@mail.notenotes.example", subject="Тема",
        **{"stripped-text": "раз", "Message-Id": "<same@x>"}))
    await client.post("/api/mail/webhook", data=_signed_form(
        recipient="mytoken123@mail.notenotes.example", subject="Тема",
        **{"stripped-text": "два", "message-id": "<same@x>"}))

    items = (await db_session.execute(select(Item).where(Item.space_id == space.id))).scalars().all()
    assert len(items) == 1


async def test_одно_письмо_двум_людям_доходит_обоим(client, db_session, test_user, monkeypatch):
    """Message-Id уникален глобально, поэтому проверка только в пределах
    спейса ящика: рассылку, пришедшую двум людям, каждый должен получить.
    """
    from sqlalchemy import select

    from app.models import EmailInbox, Item, Space, SpaceMember, User
    from app.security import hash_password

    monkeypatch.setattr(get_settings(), "mailgun_webhook_signing_key", _SIGNING_KEY)
    mine = await _inbox(db_session, test_user)

    other = User(username="other@example.com", name="Другой", password_hash=hash_password("x"))
    db_session.add(other)
    await db_session.flush()
    other_space = Space(name="Почта", owner_id=other.id)
    db_session.add(other_space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=other_space.id, user_id=other.id))
    db_session.add(EmailInbox(user_id=other.id, local_part="othertoken", space_id=other_space.id))
    await db_session.commit()

    for recipient in ("mytoken123@mail.notenotes.example", "othertoken@mail.notenotes.example"):
        await client.post("/api/mail/webhook", data=_signed_form(
            recipient=recipient, subject="Рассылка",
            **{"stripped-text": "всем", "Message-Id": "<newsletter@x>"}))

    assert len((await db_session.execute(select(Item).where(Item.space_id == mine.id))).scalars().all()) == 1
    assert len((await db_session.execute(select(Item).where(Item.space_id == other_space.id))).scalars().all()) == 1
