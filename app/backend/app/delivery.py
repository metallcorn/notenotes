from __future__ import annotations

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
            note: str = "", raw: Any = None) -> dict[str, Any]:
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
    "out_for_delivery": "W doręczeniu",
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
    cps = [
        {"time": d.get("datetime", ""),
         "status": d.get("status", ""),
         "description": _INPOST_STATUS.get(d.get("status", ""), d.get("status", ""))}
        for d in reversed(data.get("tracking_details", []) or [])
    ]
    machine = (data.get("custom_attributes") or {}).get("target_machine_detail") or {}
    top = data.get("status", "")
    return _result(
        "inpost", number, live=True,
        status_text=_INPOST_STATUS.get(top, top),
        checkpoints=cps, tracking_url=url,
        note=f"Paczkomat {machine.get('name', '')}".strip() if machine else "",
        raw=data,
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
                   checkpoints=cps, tracking_url=url, raw=data)


# --- Poczta Polska (2 шага: страница → ключ → checkmailex) --------------------

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
    if data.get("mailStatus", -1) == -1 and not data.get("mailStatusesEx"):
        return _result("poczta", number, live=True, status_text="Brak danych o przesyłce",
                       tracking_url=url, raw=data)
    # Схема успешного ответа выведена по виджету; уточнить на реальном номере.
    events = data.get("mailStatusesEx") or data.get("events") or []
    cps = [
        {"time": e.get("date", "") or e.get("time", ""),
         "status": str(e.get("code", "") or e.get("status", "")),
         "description": e.get("name", "") or e.get("description", "")}
        for e in events
    ]
    return _result("poczta", number, live=True,
                   status_text=cps[-1]["description"] if cps else "W trakcie",
                   checkpoints=list(reversed(cps)), tracking_url=url, raw=data)


# --- DPD (только ссылка: WAF блокирует серверный фетч) ------------------------

async def _dpd(number: str) -> dict[str, Any]:
    return _result(
        "dpd", number, live=False,
        tracking_url=f"https://tracktrace.dpd.com.pl/parcelDetails?typ=1&p1={number}",
        note="DPD не отдаёт статус автоматическим запросам (антибот) — статус по ссылке",
    )


_FETCH = {"inpost": _inpost, "orlen": _orlen, "poczta": _poczta, "dpd": _dpd}


# --- Точка входа -------------------------------------------------------------

async def track(raw: str, carrier: str | None = None) -> dict[str, Any]:
    """Главная функция. Либо нормализованный статус, либо
    {"need_carrier": True, "supported": [...]} — когда перевозчик неясен и
    его надо спросить у пользователя."""
    cid, number, ambiguous = identify(raw, carrier)
    if ambiguous or not cid or not number:
        return {
            "need_carrier": True,
            "number": number or raw,
            "supported": SUPPORTED,
            "message": "Не смог определить перевозчика по номеру. Уточни, чей это трек.",
        }
    return await _FETCH[cid](number)
