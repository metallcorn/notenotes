"""Сроки документов: предупредить заранее, а не констатировать задним числом.

Что уже было. expiry_check.find_expired_claims помечает УЖЕ ПРОСРОЧЕННУЮ
дату, если ассистент назвал её действующей (реальный случай с мельдунком,
09.09). Это разбор постфактум: человек узнаёт, что опоздал.

Чего не было. Сроки лежат в базе задолго до истечения и видны нам
заранее — проверено на боевой базе 02.10, и это не теория:

    05.02.2031  Paszport AB7654321, ważny do        (+1587 дней)
    25.08.2027  Następny przegląd do dnia            (+327)
    14.07.2027  Umowa najmu, przedłużyć do dnia      (+285)
    11.03.2027  Техосмотр Citroën, срок истекает     (+160)
    10.12.2026  Następny przegląd do dnia             (+69)

Паспорт, аренда, техосмотр, очередное ТО — всё то, где «узнать за неделю»
значит «не успеть». Данные были, предупреждения не было.

КАК. Раз в сутки проходим по заметкам и извлечённому тексту файлов тем же
разбором, что и expiry_check (одни и те же формулировки на русском,
польском и английском), и на каждый БУДУЩИЙ срок заводим обычное
напоминание за 60 дней. Обычное — значит оно само попадёт и в утреннюю
сводку, и в list_agenda, и в колокольчик, и в Telegram: отдельного канала
доставки заводить не нужно, он уже есть.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО:
  * прошедших дат — ими занимается expiry_check в самом ответе;
  * сейфа — он зашифрован, сервер его не читает;
  * автоматического продления или подачи чего-либо: напоминание говорит,
    человек решает.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.expiry_check import _CLAIM_RE, _VALIDITY_PHRASES, _to_date
from app.models import Item, Notification, Space, Upload

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "document_expiry"

# За сколько предупреждать. Шестьдесят дней — чтобы хватило и подать на
# новый документ, и записаться: на карту побыту в Польше очередь в урząд
# занимают сильно заранее. Для техосмотра это с запасом, и пусть: лишний
# месяц раздумий дешевле пропущенного срока.
LEAD = timedelta(days=60)

# Насколько далеко вперёд смотрим. Паспорт до 2031 года — настоящий срок,
# но напоминание на 2031-й сегодня не нужно никому; оно заведётся само,
# когда подойдёт время (воркер ходит каждые сутки).
MAX_HORIZON = timedelta(days=400)

_CHECK_INTERVAL_SECONDS = 6 * 3600


# Разметка и служебный мусор, которые в пояснении только мешают.
#
# Живой пример из боевой базы (напоминание про сервисную книжку):
#   "-----------|&#10;| 10.12.2024 | | Warunki normalne □ | do 73 000 km"
# Это срез markdown-таблицы: горизонтальная линейка, неразэкранированный
# перевод строки и палки столбцов. Человеку непонятно, модели — тоже.
_NOISE_RE = re.compile(r"&#\d+;|&[a-z]{2,6};|[|─—]{2,}|[-]{3,}")


# Длинные цепочки цифр в пояснении — это идентификаторы документов, и им
# в уведомлении не место.
#
# Найдено 10.10 в живом напоминании про паспорт: «Jan K… PESEL
# 90010112345 Paszport 75 1234567 ważny do 10.08.2027». Это уходит в
# Telegram и в push, то есть ВЫТАЛКИВАЕТСЯ без спроса, а ещё попадает в
# промпт модели через list_agenda (details). ТЗ §16.1 про PII говорит
# ровно обратное: в индекс и в промпт — только тег/лейбл.
#
# Смысл пояснения — сказать, КАКОЙ это документ («Paszport … ważny do»),
# а не повторить номер: для «пора продлевать» номер не нужен. Шесть цифр
# подряд — порог, который не задевает даты (10.12.2026 — группы по две и
# четыре) и обычные числа («do 73 000 km»).
#
# Чего это НЕ делает: сам документ лежит в общем хранилище, и его полный
# текст по-прежнему доступен ассистенту через get_note. Здесь закрыт
# только канал, который срабатывает сам, без просьбы человека.
_LONG_DIGITS_RE = re.compile(r"\d{6,}")


def _mask_identifiers(text: str) -> str:
    return _LONG_DIGITS_RE.sub(lambda m: "•" * min(len(m.group()), 8), text)


def _snippet(text: str, match_end: int) -> str:
    """Кусок текста вокруг срока — чтобы человек понял, о чём речь.

    Названия заметок бывают бесполезны («CamScanner 29.05.2025 07.31.pdf»),
    а строка «Paszport AB7654321, ważny do 10.08.2027» объясняет всё.
    """
    start = max(0, match_end - 140)
    raw = html.unescape(text[start:match_end])
    cleaned = _NOISE_RE.sub(" ", raw).replace("|", " ")
    return _mask_identifiers(" ".join(cleaned.split())[-90:])


# Формулировка, которой заявлен срок, — отдельно от самой даты. Берём из
# того же списка, что и _CLAIM_RE, чтобы не разъехалось.
_PHRASE_RE = re.compile(r"(?:" + "|".join(_VALIDITY_PHRASES) + r")", re.IGNORECASE)


def _phrase_of(match: re.Match[str]) -> str:
    found = _PHRASE_RE.match(match.group(0))
    return " ".join(found.group(0).lower().split()) if found else ""


# Любая дата — чтобы найти, к какой записи журнала относится срок.
_ANY_DATE_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b")

# Насколько далеко назад искать дату записи. В таблице сервисной книжки
# строка целиком — «| 10.12.2024 | | Warunki normalne □ | do 73 000 km lub
# do dnia 10.12.2026 |», то есть около ста символов. Двести — с запасом на
# разметку OCR, но не настолько, чтобы залезть в предыдущую строку.
_ROW_LOOKBEHIND = 200


def _row_date(text: str, match: re.Match[str]) -> date | None:
    """Дата ЗАПИСИ, к которой относится найденный срок.

    В журнале обслуживания каждая строка — «обслужено тогда → следующий
    осмотр до тогда», и живой срок принадлежит строке с самым поздним
    обслуживанием. Берём ближайшую дату ПЕРЕД формулировкой.

    СТРОГО В ПРЕДЕЛАХ ОДНОЙ СТРОКИ. Первая версия искала просто назад на
    двести символов и на тексте, где сроки идут подряд разными строками,
    принимала за «дату записи» срок из ПРЕДЫДУЩЕЙ строки. Поймано
    собственным тестом. В таблице дата и срок всегда в одной строке, так
    что ограничение ничего не отнимает, а ложные пары убирает.
    """
    line_start = text.rfind("\n", 0, match.start()) + 1
    start = max(line_start, match.start() - _ROW_LOOKBEHIND)
    candidates = list(_ANY_DATE_RE.finditer(text, start, match.start()))
    if not candidates:
        return None
    day, month, year = candidates[-1].groups()
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _literal_date(match: re.Match[str]) -> str:
    """Дата ровно так, как она написана в документе.

    ЗАЧЕМ. По этой строке редактор прокручивает к нужному месту
    (lib/findInDoc.ts), и переформатировать её нельзя. Живой случай
    12.10: напоминание про техосмотр никуда не прокручивало, потому что
    в payload лежало «11.03.2027», а в заметке написано «11 марта 2027
    года». Код даты не придумывает — он берёт то, что совпало.
    """
    phrase = _PHRASE_RE.match(match.group(0))
    tail = match.group(0)[len(phrase.group(0)):] if phrase else match.group(0)
    return tail.strip(" *_«\"'\t")


def find_upcoming(text: str, today: date) -> list[tuple[date, str, str]]:
    """Будущие сроки: (дата, пояснение, дата-как-написана-в-тексте).

    Третий элемент — буквальное написание, по нему редактор прокручивает
    к месту; см. _literal_date.

    ПЕРЕКРЫТЫЕ СРОКИ. Жалоба владельца 11.10: пришло напоминание «Срок
    истекает 10.12.2026: Сервисная книжка», а срок давно не актуален.
    Документ оказался ЖУРНАЛОМ обслуживания — восемь записей вида
    «обслужено тогда → следующий осмотр до тогда»:

        16.01.2014 → 16.01.2017      10.12.2024 → 10.12.2026
        03.10.2023 → 03.10.2024      12.12.2024 → 12.12.2025
        25.10.2023 → 25.10.2024      02.07.2025 → 02.07.2026
        14.03.2024 → 14.03.2025      25.08.2026 → 25.08.2027

    Последнее ТО 25.08.2026, значит 10.12.2026 перекрыт четырьмя более
    поздними записями. Предупреждать о нём — вранье.

    ПРАВИЛО ВЫБРАЛИ ДАННЫЕ, А НЕ ИНТУИЦИЯ. Первое, что хочется, —
    «оставляем самый поздний срок под одной формулировкой». Прогнал по
    всей боевой базе: оно отбросило бы 10.08.2027 в скане CamScanner,
    оставив 05.02.2031. А это РАЗНЫЕ документы в одном скане (там и
    PESEL'и трёх человек), и спрятать срок на три с половиной года раньше
    было бы хуже исходной болезни. Правило не поехало в прод.

    Работает уточнённое: формулировка «журнальная», если под ней в том же
    документе есть и ПРОШЕДШИЕ даты, — тогда это история, и жива только
    последняя запись. Если все даты под формулировкой в будущем, это
    разные документы, и трогать их нельзя. Проверено на той же базе:
    сервисная книжка схлопывается верно («do dnia», шесть прошедших
    дат), скан остаётся целым («ważny do», прошедших нет).
    """
    text = text or ""
    history: dict[str, bool] = {}
    # По формулировке: срок -> (дата записи, пояснение).
    entries: dict[str, dict[date, tuple[date | None, str]]] = {}
    # Самая поздняя дата ЗАПИСИ под формулировкой, включая прошедшие сроки.
    newest_row: dict[str, date] = {}

    for match in _CLAIM_RE.finditer(text):
        parsed = _to_date(match)
        if parsed is None:
            continue
        phrase = _phrase_of(match)
        row = _row_date(text, match)
        if row is not None and row <= today:
            previous = newest_row.get(phrase)
            if previous is None or row > previous:
                newest_row[phrase] = row
        if parsed <= today:
            # Прошедшее само в напоминания не идёт (ими занимается
            # expiry_check в ответе), но служит признаком журнала.
            history[phrase] = True
            continue
        if parsed > today + MAX_HORIZON:
            continue
        entries.setdefault(phrase, {}).setdefault(
            parsed, (row, _snippet(text, match.end()), _literal_date(match))
        )

    found: dict[date, tuple[str, str]] = {}
    for phrase, dates in entries.items():
        if not history.get(phrase):
            # Истории нет — это не журнал, а разные документы. Все сроки
            # живые, схлопывать нельзя (см. докстринг выше).
            found.update({d: (snippet, literal) for d, (_, snippet, literal) in dates.items()})
            continue

        # Журнал: жив срок из записи с самым поздним обслуживанием.
        #
        # Почему именно так, а не «самый поздний срок». Живой случай 12.10:
        # фото 20260822_132310.jpg — ФРАГМЕНТ той же книжки, четыре строки:
        #   14.03.2024 → 14.03.2025     10.12.2024 → 10.12.2026
        #   12.12.2024 → 12.12.2025     02.07.2025 → 02.07.2026
        # Самый поздний СРОК здесь 10.12.2026, и о нём пришло напоминание.
        # Но он из записи от 10.12.2024, а машину обслуживали позже — 02.07.2025,
        # и тот срок (02.07.2026) уже прошёл. То есть живого срока в этом
        # фрагменте нет вовсе, а 10.12.2026 — бумажный хвост.
        latest_row = newest_row.get(phrase)
        if latest_row is None:
            # Журнал есть (под формулировкой лежат прошедшие сроки), а дат
            # записей не нашлось — текст не табличный. Тогда откатываемся
            # к более грубому, но ЗАМЕРЕННОМУ правилу: жив самый поздний
            # срок. Оно верно для последовательности одного и того же
            # обязательства, а разные документы сюда не попадают — у них
            # истории под формулировкой нет вовсе (ветка выше).
            latest = max(dates)
            live = {latest: (dates[latest][1], dates[latest][2])}
        else:
            live = {
                d: (snippet, literal) for d, (row, snippet, literal) in dates.items()
                if row is None or row >= latest_row
            }
        dropped = [str(d) for d in sorted(dates) if d not in live]
        if dropped:
            logger.info(
                "Сроки под «%s» — журнал (последняя запись %s): оставлено %s, перекрыто %s",
                phrase, latest_row, ", ".join(str(d) for d in sorted(live)) or "ничего",
                ", ".join(dropped),
            )
        found.update(live)
    return [(d, snippet, literal) for d, (snippet, literal) in sorted(found.items())]



# Куда прокручивать, если дата лежит НЕ в видимом тексте заметки.
#
# ЗАМЕР 17.10, после ревью: из четырёх живых напоминаний о сроках
# прокручивалось ОДНО. В трёх остальных дата находится внутри атрибута
# data-text блока вложения — там хранится распознанный текст файла, и в
# самом тексте заметки этой даты нет вовсе:
#
#   CamScanner 29.05.2025        дата только в data-text (PDF)
#   Сервисная книжка             дата только в data-text (фото 1000016776)
#   Przedłużenie umowy najmu     дата только в data-text, transcript файла ПУСТ
#
# Последний случай и определил решение. Напрашивалось «не искать в
# атрибутах вовсе, пусть сработает проход по файлам» — но у этого файла
# текст извлечён текстовым слоем прямо при загрузке и вшит в блок
# заметки, а на самой загрузке transcript пустой. Выкинув атрибуты, мы
# потеряли бы срок целиком.
#
# Поэтому: дата не видна в тексте — находим вложение, в чьём data-text
# она лежит, и прокручиваем к файлу. Ничего не теряется, и человек
# попадает туда, где документ.
#
# 18.10: data-text из заметок вынесен в загрузки (app/attachment_text.py),
# и transcript «Przedłużenie» заполнен. Новые сроки из файлов приходят
# проходом по загрузкам (from_upload ниже) и сразу ведут к вложению. Эта
# функция остаётся для блоков старого формата — 21 блок, чьих загрузок уже
# нет, и заметки, откаченные к версии до переезда.
_TAG_RE = re.compile(r"<[^>]+>")
_DIV_RE = re.compile(r"<div[^>]*>")
_DATA_TEXT_RE = re.compile(r'data-text="([^"]*)"')
_UPLOAD_REF_RE = re.compile(r'/api/uploads/([0-9a-fA-F-]{36})|data-upload-id="([0-9a-fA-F-]{36})"')


def scroll_anchor(content: str, literal: str) -> str:
    """Литерал, если он виден в тексте; иначе id вложения с этим текстом."""
    if literal in _TAG_RE.sub(" ", content or ""):
        return literal
    for tag in _DIV_RE.finditer(content or ""):
        body = tag.group(0)
        text_attr = _DATA_TEXT_RE.search(body)
        if text_attr is None or literal not in text_attr.group(1):
            continue
        ref = _UPLOAD_REF_RE.search(body)
        if ref is not None:
            return ref.group(1) or ref.group(2)
    # Не нашли вложение — отдаём литерал: прокрутка не сработает, но
    # заметка откроется, и это лучше, чем ничего.
    return literal

async def _scan_once() -> int:
    """Завести недостающие напоминания. Возвращает, сколько добавлено."""
    today = date.today()
    added = 0
    async with async_session() as db:
        # Заметки — вместе с автором и с исключением сейфа.
        notes = (
            await db.execute(
                select(Item.id, Item.author_id, Item.title, Item.content, Item.space_id)
                .join(Space, Space.id == Item.space_id)
                .where(
                    Item.deleted_at.is_(None),
                    Space.is_vault.is_(False),
                    # ДИАЛОГИ ИСКЛЮЧЕНЫ. Их content — это расшифровка
                    # разговора (_flatten_transcript), и если ассистент
                    # обсуждал срок из заметки, тот же срок находился
                    # второй раз — уже «в диалоге».
                    #
                    # Живой случай 10.10: на «какие мероприятия на этой
                    # неделе» пришло два одинаковых «Срок истекает
                    # 10.12.2026» — один от сервисной книжки, второй от
                    # диалога «Telegram», где про неё говорили. Разговор
                    # не документ: срок у него не истекает, и вести
                    # человека из напоминания в середину переписки
                    # вместо самой книжки — бессмысленно.
                    Item.material_type.in_(("note", "list", "ticket", "table", "routine")),
                )
            )
        ).all()
        sources: list[tuple[uuid.UUID, uuid.UUID, str, str, uuid.UUID, uuid.UUID | None]] = [
            (i, a, t or "Без названия", c or "", sp, None) for i, a, t, c, sp in notes
        ]

        # Файлы — их извлечённый текст. Привязываем к заметке, в которой
        # файл лежит: иначе некуда вести человека из напоминания.
        uploads = (
            await db.execute(
                select(Upload.id, Upload.filename, Upload.transcript)
                .join(Space, Space.id == Upload.space_id)
                .where(Space.is_vault.is_(False), Upload.transcript.isnot(None))
            )
        ).all()
        for upload_id, filename, transcript in uploads:
            # sources теперь шестиэлементный (добавился id загрузки) —
            # распаковка должна совпадать, иначе ValueError на первом же
            # файле. Поймано тестом.
            host = next(((i, a, t, sp) for i, a, t, c, sp, _u in sources if str(upload_id) in c), None)
            if host is None:
                continue
            # Пятым элементом спейс, шестым — id ЗАГРУЗКИ. Он нужен, чтобы
            # прокрутить человека к самому файлу: срок из распознанного
            # текста в заметке отсутствует, искать его там нечего.
            # Живой случай 12.10: «Техосмотр Citroën», 11.03.2027 есть в
            # transcript фотографии и нет в content заметки.
            sources.append((host[0], host[1], filename or host[2], transcript, host[3], upload_id))

        for item_id, author_id, title, text, space_id, from_upload in sources:
            for expires_on, snippet, literal in find_upcoming(text, today):
                key = f"{item_id}:{expires_on.isoformat()}"
                exists = (
                    await db.execute(
                        select(Notification.id).where(
                            Notification.type == NOTIFICATION_TYPE,
                            Notification.payload["key"].astext == key,
                        )
                    )
                ).first()
                if exists is not None:
                    continue

                # Напоминание в полдень: срок — это дело дня, а не минуты,
                # и будить человека в полночь незачем.
                trigger_at = datetime.combine(expires_on - LEAD, time(12, 0))
                db.add(
                    Notification(
                        user_id=author_id,
                        type=NOTIFICATION_TYPE,
                        title=f"Срок истекает {expires_on:%d.%m.%Y}: {title[:80]}",
                        body=snippet,
                        # space_id ОБЯЗАТЕЛЕН, хотя кажется лишним: без него
                        # напоминание в «Активности» не кликабельно вовсе —
                        # ActivityView.tsx делает карточку кликабельной только
                        # при наличии ОБОИХ, space_id и item_id. Жалоба
                        # владельца 12.10: «не могу на это кликнуть в отличии
                        # от всего другого и попасть на нужную заметку». Все
                        # пять заведённых к тому дню напоминаний о сроках были
                        # мёртвыми ссылками.
                        payload={
                            "key": key,
                            "item_id": str(item_id),
                            "space_id": str(space_id),
                            "expires_on": expires_on.isoformat(),
                            # Текст, по которому редактор прокрутит к
                            # нужному месту (lib/findInDoc.ts). Жалоба
                            # владельца 12.10: «не могу перейти к тому
                            # месту, где эта дата» — заметка открывалась
                            # целиком, а это 12 554 символа распознанной
                            # сервисной книжки.
                            #
                            # Дата в формате ДД.ММ.ГГГГ: именно так её
                            # пишут в польских и русских документах, и
                            # она переживает рендер, в отличие от
                            # markdown-разметки и HTML-сущностей
                            # исходника. Не нашлась — заметка просто
                            # откроется, без прокрутки.
                            # Дата — когда срок лежит в тексте самой
                            # заметки. Если он пришёл из распознанного
                            # текста файла, в заметке его нет вовсе, и
                            # прокручивать надо к вложению — тогда здесь
                            # id загрузки. Одно поле на две стратегии,
                            # различает их фронтенд (lib/findInDoc.ts).
                            "find": str(from_upload) if from_upload else scroll_anchor(text, literal),
                        },
                        trigger_at=trigger_at.replace(tzinfo=timezone.utc),
                    )
                )
                added += 1
        if added:
            await db.commit()
    return added


async def run_worker() -> None:
    while True:
        try:
            added = await _scan_once()
            if added:
                logger.info("Сроки документов: заведено напоминаний %d", added)
        except Exception:
            logger.exception("Ошибка при проверке сроков документов")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
