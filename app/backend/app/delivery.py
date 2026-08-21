from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

# Движок отслеживания доставки. Детерминированные шаблоны на перевозчика —
# НЕ даём модели выбирать API по памяти (там она галлюцинирует сторонние
# сервисы и несуществующие поля). Задача модели максимум — распознать, что
# это посылка, и при неоднозначности спросить перевозчика; сам запрос и
# разбор ответа жёстко зашиты здесь.
#
# Все эндпоинты проверены вживую 21.08.2026. Это непубличные-по-контракту,
# но настоящие продакшн-API самих перевозчиков (не скрейп HTML), поэтому
# у каждого — фолбэк на официальную ссылку, если ответ не пришёл.

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(12.0)

# Порядок важен для авто-определения по голому номеру: чей формат совпал
# ровно один — того и берём; совпало 0 или >1 — просим уточнить.
SUPPORTED: list[dict[str, str]] = [
    {"id": "inpost", "label": "InPost (Paczkomaty / kurier)"},
    {"id": "poczta", "label": "Poczta Polska"},
    {"id": "orlen", "label": "Orlen Paczka"},
    {"id": "dpd", "label": "DPD"},
]
_LABEL = {c["id"]: c["label"] for c in SUPPORTED}


# --- Распознавание -----------------------------------------------------------

_URL_HOST = {
    "inpost": re.compile(r"(inpost\.pl|paczkomaty|easypack24)", re.I),
    "poczta": re.compile(r"(poczta-polska\.pl|emonitoring)", re.I),
    "orlen": re.compile(r"orlenpaczka\.pl", re.I),
    "dpd": re.compile(r"dpd\.com\.pl", re.I),
}
# Из какого query-параметра тянуть номер для каждого хоста.
_URL_PARAM = {"inpost": "parcel", "poczta": "numer", "orlen": "id", "dpd": "p1"}

# Форматы голых номеров. dpd намеренно отсутствует — их номера слишком
# неспецифичны, чтобы угадывать по одному числу; DPD только по ссылке/явно.
_NUM_FORMAT = {
    "inpost": re.compile(r"^\d{24}$"),
    "poczta": re.compile(r"^(?:PX\d{18,22}|00259\d{15}|[A-Z]{2}\d{9}[A-Z]{2})$"),
    "orlen": re.compile(r"^(?:[23]\d{12}|\d{7}|\d{10})$"),
}


def _extract_from_url(raw: str) -> tuple[str | None, str | None]:
    """Ссылка → (carrier, number). Домен определяет перевозчика надёжно,
    номер берём из известного для него параметра, а если не вышло — из
    первой длинной цифровой группы в URL."""
    for cid, pat in _URL_HOST.items():
        if pat.search(raw):
            m = re.search(rf"[?&]{_URL_PARAM[cid]}=([A-Za-z0-9]+)", raw)
            if m:
                return cid, m.group(1)
            m = re.search(r"(\d{7,})", raw)
            return cid, (m.group(1) if m else None)
    return None, None


def identify(raw: str, carrier: str | None = None) -> tuple[str | None, str | None, bool]:
    """Возвращает (carrier, number, ambiguous). ambiguous=True — не смогли
    решить однозначно, вызывающий код должен спросить пользователя."""
    raw = (raw or "").strip()
    if carrier:
        carrier = carrier.strip().lower()
        if carrier not in _LABEL:
            return None, None, True
        num = raw
        if "://" in raw or "/" in raw:
            _, num = _extract_from_url(raw)
        return carrier, (num or raw), False

    if "://" in raw or raw.lower().startswith("www."):
        cid, num = _extract_from_url(raw)
        return cid, num, cid is None

    number = re.sub(r"\s+", "", raw)
    matched = [cid for cid, pat in _NUM_FORMAT.items() if pat.match(number)]
    if len(matched) == 1:
        return matched[0], number, False
    # 0 совпадений или пересечение форматов → пусть пользователь выберет.
    return None, number, True


# --- Нормализованный результат ----------------------------------------------

def _result(carrier: str, number: str, *, live: bool, status_text: str = "",
            checkpoints: list[dict] | None = None, tracking_url: str = "",
            note: str = "") -> dict[str, Any]:
    cps = checkpoints or []
    return {
        "carrier": carrier,
        "carrier_label": _LABEL.get(carrier, carrier),
        "tracking_number": number,
        "live": live,
        "status_text": status_text,
        "last_event_time": cps[0]["time"] if cps else "",
        "checkpoints": cps,
        "tracking_url": tracking_url,
        "note": note,
    }


# --- InPost (ShipX) ----------------------------------------------------------

_INPOST_STATUS = {
    "confirmed": "Zarejestrowano",
    "dispatched_by_sender": "Nadano",
    "collected_from_sender": "Odebrano od nadawcy",
    "taken_by_courier": "W drodze",
    "adopted_at_source_branch": "W sortowni",
    "sent_from_source_branch": "Wysłano z sortowni",
    "out_for_delivery": "W doręczeniu",
    "stack_in_box_machine": "Włożono do paczkomatu",
    "ready_to_pickup": "Gotowa do odbioru",
    "delivered": "Doręczono",
}


async def _inpost(number: str) -> dict[str, Any]:
    url = f"https://inpost.pl/sledzenie-przesylek?number={number}"
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as c:
        r = await c.get(f"https://api-shipx-pl.easypack24.net/v1/tracking/{number}")
    if r.status_code != 200:
        return _result("inpost", number, live=False, tracking_url=url,
                       note="ShipX не отдал статус — открой ссылку вручную")
    data = r.json()
    # ShipX отдаёт tracking_details уже от новых к старым (см. историю
    # правки) — реальный найденный баг: код заворачивал их в reversed(),
    # получая порядок от старых к новым, а фронт берёт checkpoints[:5] в
    # расчёте на "новые сверху" (тот же порядок, что у Poczta/Orlen) — итог:
    # в карточке показывались 5 САМЫХ СТАРЫХ событий, обрезая реальную
    # доставку, если событий было больше пяти.
    cps = [
        {"time": d.get("datetime", ""),
         "status": d.get("status", ""),
         "description": _INPOST_STATUS.get(d.get("status", ""), d.get("status", ""))}
        for d in (data.get("tracking_details", []) or [])
    ]
    custom_attrs = data.get("custom_attributes") or {}
    machine = custom_attrs.get("target_machine_detail") or {}
    top = data.get("status", "")
    note = ""
    if machine:
        # Реальный найденный баг (уже второй раз на тех же данных): в ответе
        # ShipX есть не только адрес/часы, но и location_description
        # ("в каком магазине" стоит пачкомат) и size на верхнем уровне
        # custom_attributes ("какого размера ячейка/посылка") — ничего из
        # этого не вытаскивалось, хотя раньше пользователь видел эти поля
        # через сырой ответ (url_check напрямую по этому же API).
        addr = machine.get("address") or {}
        addr_line = ", ".join(p for p in [addr.get("line1", ""), addr.get("line2", "")] if p)
        location_desc = machine.get("location_description", "")
        hours = machine.get("opening_hours", "")
        size = custom_attrs.get("size", "")
        note = f"Paczkomat {machine.get('name', '')}".strip()
        if location_desc:
            note += f" ({location_desc})"
        if addr_line:
            note += f", {addr_line}"
        if size:
            note += f" · размер {size}"
        if hours:
            note += f" · режим работы: {hours}"
    return _result(
        "inpost", number, live=True,
        status_text=_INPOST_STATUS.get(top, top),
        checkpoints=cps, tracking_url=url,
        note=note,
    )


# --- Orlen Paczka (JSONP) ----------------------------------------------------

async def _orlen(number: str) -> dict[str, Any]:
    url = f"https://www.orlenpaczka.pl/sledz-paczke/?id={number}"
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as c:
        r = await c.get(
            f"https://nadaj.orlenpaczka.pl/parcel/api-status?id={number}",
            headers={"Referer": "https://www.orlenpaczka.pl/sledz-paczke/",
                     "X-Requested-With": "XMLHttpRequest"},
        )
    if r.status_code != 200:
        return _result("orlen", number, live=False, tracking_url=url,
                       note="Orlen не отдал статус — открой ссылку вручную")
    # Ответ обёрнут в JSONP: callback({...});
    m = re.search(r"\{.*\}", r.text, re.S)
    if not m:
        return _result("orlen", number, live=False, tracking_url=url,
                       note="Неожиданный формат ответа Orlen")
    data = json.loads(m.group(0))
    cps = [
        {"time": h.get("date", ""),
         "status": h.get("status", "") or h.get("code", ""),
         "description": h.get("label", "")}
        for h in (data.get("history") or [])
    ]
    return _result("orlen", number, live=True,
                   status_text=cps[0]["description"] if cps else data.get("status", ""),
                   checkpoints=cps, tracking_url=url)


# --- Poczta Polska (2 шага: страница → ключ → checkmailex) --------------------

_HOURS_DAYS = (("businessDays", "Пн–Пт"), ("saturday", "Сб"), ("sunday", "Вс"))


def _format_hours(desc: dict[str, Any] | None) -> str:
    """openingHours из description отделения (тоже реально в ответе API,
    но раньше вообще никуда не попадал — ни модели, ни в raw, см.
    _format_office) в человеческую строку вида "Пн–Пт 08:00–22:00, Сб 08:00–22:00"."""
    hours = (desc or {}).get("openingHours") or {}
    parts = []
    for key, label in _HOURS_DAYS:
        for slot in hours.get(key) or []:
            frm, to = slot.get("from", ""), slot.get("to", "")
            if frm and to:
                parts.append(f"{label} {frm[:5]}–{to[:5]}")
    return ", ".join(parts)


def _format_office(office: dict[str, Any] | None) -> str:
    """Отделение/пункт из postOffice-объекта Poczta в человеческую строку.
    Реальная жалоба: адрес доставки уже был в ответе API (recipientPostOffice/
    postOffice каждого события), но не показывался — приходилось идти по
    ссылке вручную, чтобы узнать, куда пришла посылка. Дальше выяснилось,
    что то же самое было и с режимом работы (openingHours) — оба раза
    данные реально были в ответе перевозчика, просто терялись при разборе."""
    if not office:
        return ""
    name = office.get("name", "")
    desc = office.get("description") or {}
    street = " ".join(p for p in [desc.get("street", ""), desc.get("houseNumber", "")] if p)
    city_line = " ".join(p for p in [desc.get("zipCode", ""), desc.get("city", "")] if p)
    addr = ", ".join(p for p in [street, city_line] if p)
    base = f"{name}, {addr}" if addr else name
    hours = _format_hours(desc)
    return f"{base} · режим работы: {hours}" if hours else base


async def _poczta(number: str) -> dict[str, Any]:
    url = f"https://emonitoring.poczta-polska.pl/?numer={number}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA},
                                     follow_redirects=True) as c:
            # Шаг 1: страница ставит куки (в т.ч. Incapsula) и содержит свежий
            # одноразовый ключ в data-apikey — без него checkmailex даёт 401.
            page = await c.get("https://emonitoring.poczta-polska.pl/")
            km = re.search(r'data-apikey="([^"]+)"', page.text)
            if not km:
                return _result("poczta", number, live=False, tracking_url=url,
                               note="Не удалось получить ключ Poczta (возможно, антибот) — открой ссылку")
            # Шаг 2: POST с ключом. Тело — точь-в-точь как виджет
            # (widget.tracking.min.js): language/number/addPostOfficeInfo.
            r = await c.post(
                "https://uss.poczta-polska.pl/uss/v2.0/tracking/checkmailex",
                headers={"API_KEY": km.group(1),
                         "Content-Type": "application/json; charset=utf-8",
                         "Referer": "https://emonitoring.poczta-polska.pl/"},
                content=json.dumps({"language": "PL", "number": number,
                                    "addPostOfficeInfo": True}),
            )
    except httpx.HTTPError:
        return _result("poczta", number, live=False, tracking_url=url,
                       note="Poczta не ответила — открой ссылку вручную")
    if r.status_code != 200:
        return _result("poczta", number, live=False, tracking_url=url,
                       note="Poczta отклонила запрос — открой ссылку вручную")
    data = r.json()
    # Реальная схема (проверено на живом номере 21.08.2026, см. историю
    # правки): события лежат в data["mailInfo"]["events"], НЕ в
    # data["mailStatusesEx"]/data["events"] — та схема была угадана по
    # виджету и никогда не сверялась с реальным ответом. Из-за этого
    # events всегда получался пустым и код тихо скатывался на хардкод
    # "W trakcie" независимо от настоящего статуса (даже для уже
    # доставленных посылок) — реальный баг, найденный пользователем.
    events = (data.get("mailInfo") or {}).get("events") or []
    if not events:
        return _result("poczta", number, live=True, status_text="Brak danych o przesyłce",
                       tracking_url=url)
    # События идут в хронологическом порядке (старые первыми).
    cps = [
        {"time": e.get("time", "") or e.get("date", ""),
         "status": str(e.get("code", "") or e.get("status", "")),
         "description": e.get("name", "") or e.get("description", "")}
        for e in events
    ]
    # Отделение/пункт последнего события — для "Doręczona" это фактически
    # куда пришла посылка, для "W doręczeniu" — какое отделение везёт.
    office = _format_office(events[-1].get("postOffice")) or _format_office(
        (data.get("mailInfo") or {}).get("recipientPostOffice")
    )
    return _result("poczta", number, live=True,
                   status_text=cps[-1]["description"],
                   checkpoints=list(reversed(cps)), tracking_url=url,
                   note=office)


# --- DPD (только ссылка: WAF блокирует серверный фетч) ------------------------

async def _dpd(number: str) -> dict[str, Any]:
    return _result(
        "dpd", number, live=False,
        tracking_url=f"https://tracktrace.dpd.com.pl/parcelDetails?typ=1&p1={number}",
        note="DPD не отдаёт статус автоматическим запросам (антибот) — статус по ссылке",
    )


_FETCH = {"inpost": _inpost, "orlen": _orlen, "poczta": _poczta, "dpd": _dpd}


# --- Точка входа -------------------------------------------------------------

def _looks_found(result: dict[str, Any]) -> bool:
    """Перевозчик реально нашёл эту посылку (а не просто ответил без ошибки)."""
    return bool(result.get("live")) and bool(result.get("checkpoints")) \
        and result.get("status_text") != "Brak danych o przesyłce"


async def track_any(number: str) -> dict[str, Any]:
    """Перевозчик не указан и номер не подошёл однозначно ни под один
    формат — вместо того чтобы сразу переспрашивать, пробуем все
    перевозчики с живой проверкой параллельно (без dpd — у него нет живой
    проверки, только ссылка, он не может подтвердить совпадение) и
    возвращаем того единственного, кто реально нашёл посылку."""
    number = re.sub(r"\s+", "", number)
    candidates = [cid for cid in _FETCH if cid != "dpd"]
    results = await asyncio.gather(*(_FETCH[cid](number) for cid in candidates))
    hits = [r for r in results if _looks_found(r)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return {
            "need_carrier": True,
            "number": number,
            "supported": SUPPORTED,
            "message": "Не нашёл посылку ни у одного перевозчика с живой проверкой "
                       "(InPost/Poczta/Orlen). Уточни перевозчика или пришли ссылку "
                       "отслеживания — либо это DPD (для него живой проверки нет).",
        }
    return {
        "need_carrier": True,
        "number": number,
        "supported": [c for c in SUPPORTED if c["id"] in {h["carrier"] for h in hits}],
        "message": "Нашлось совпадение сразу у нескольких перевозчиков — уточни, какой это трек.",
    }


async def track(raw: str, carrier: str | None = None) -> dict[str, Any]:
    """Главная функция. Либо нормализованный статус, либо
    {"need_carrier": True, "supported": [...]} — когда перевозчик неясен и
    его надо спросить у пользователя."""
    cid, number, ambiguous = identify(raw, carrier)
    if not ambiguous and cid and number:
        return await _FETCH[cid](number)
    if not carrier and number:
        # Перевозчик не указан явно (в отличие от случая, когда указан, но
        # неизвестен) — пробуем все, прежде чем переспрашивать.
        return await track_any(number)
    return {
        "need_carrier": True,
        "number": number or raw,
        "supported": SUPPORTED,
        "message": "Не смог определить перевозчика по номеру. Уточни, чей это трек.",
    }
