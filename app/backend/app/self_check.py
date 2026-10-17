"""Самопроверка: находить промахи ассистента до того, как о них расскажут.

ПОЧЕМУ ЭТО ВООБЩЕ ПОНАДОБИЛОСЬ. Жалоба владельца 10.10: «кажется, наш
агент всё ещё не слишком полезен… он и так часто ошибается и тупит, и мы
это никак не можем решить».

Разбор трёх его жалоб за ту неделю показал, что «никак не можем» —
неправда: каждый раз причиной был дефект в коде, и каждый раз он
чинился с измеримым эффектом (свёртка контекста −72%, мёртвый диалог
ожил, схлопывание дублей). Модель тут почти не виновата: тот же вопрос
про «Кейтерку», на который mistral-small ответил чушью в засранном
диалоге, в чистом диалоге он отвечает правильно. А «взять модель
поумнее» уже мерили в августе на 28 реальных вопросах — large не точнее
и менее надёжна (см. llm/factory.py).

Настоящая нерешённая проблема была другая: ВСЕ ТРИ ПРОМАХА НАШЁЛ
ЧЕЛОВЕК. Цикл «ошибка → дамп таблицы → повтор» прокрутился четырнадцать
раз в одном диалоге и никого не разбудил. Мёртвый диалог простоял две
недели. Мы не плохо чиним — мы ничего не видим, пока не придут и не
скажут.

При этом все признаки УЖЕ ЛЕЖАТ В ДАННЫХ. Этот модуль их читает.

ЧТО ИЩЕМ (и почему именно это — каждая проверка поймала бы реальный
случай из прошлого, а не воображаемый):

  * раздутый диалог — «Тренировки» перед починкой отправляли 295 462
    символа на каждый вызов;
  * один и тот же отказ инструмента подряд — те самые 14 «Строка не
    найдена»;
  * сохранённый отказ «не получилось получить ответ» — диалог
    «Telegram», 26.09 и снова 10.10;
  * непомерный результат инструмента — 3.8 МБ base64 из get_file;
  * проигнорированная подсказка «это есть в твоей базе» — вопрос про
    «Кейтерку», на который ответили лекцией про кейтеринг.

КАК ДОСТАВЛЯЕТСЯ. Три канала, намеренно разные:

  1. журнал (logger.warning) — всё, это наш канал в код;
  2. инструмент self_check — чтобы можно было спросить в любой момент,
     в том числе снаружи через MCP;
  3. одна строка в утренней сводке, когда что-то найдено.

Отдельного уведомления НЕТ, и это осознанно: правило из audit_log
(«предупреждать человека только о том, что редко, не сделано им самим и
требует действий») здесь работает против тревог. Ежедневное «всё хорошо»
учит смахивать не глядя, а потом смахнут и то, в котором что-то было.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db import async_session
from app.dialog_tool_window import MAX_RESULT_CHARS, fold_stale_tool_results
from app.models import Item
from app.tools.web_search import OWN_BASE_KEY

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 6 * 3600

# Потолок на то, что уходит в модель. ЗАМЕРЕНО 10.10 на всех 101 живых
# диалогах: самый крупный после свёртки — 92 156 символов, и он отвечает
# нормально. «Тренировки» перед починкой — 295 462, и вот там ответы
# разваливались (115 тысяч токенов в одном вызове при окне 128K).
# 150 000 — между этими двумя: сегодня не срабатывает ни на одном
# диалоге, но предупредит задолго до того, как станет плохо.
MAX_PROMPT_CHARS = 150_000

# Сколько раз один и тот же отказ инструмента — уже не случайность.
# ЗАМЕРЕНО на той же выборке: по два повтора («Папка не найдена»,
# «Заметка не найдена») — обычное дело, модель уточняет и идёт дальше.
# Патология начинается дальше: x5 «Лимит веб-поиска исчерпан» и x14
# «Строка не найдена». Порог 4 ловит обе и не трогает нормальные.
REPEATED_ERROR_TIMES = 4

# Насколько назад смотрим на отказы. Та же причина, что у _WIPE_LOOKBACK
# в cleanup.py: старое уже разобрано, и напоминать о нём каждые шесть
# часов — шум, за которым не заметишь новое.
LOOKBACK = timedelta(days=7)


@dataclass
class Finding:
    """Одно замечание. kind — машинный, чтобы схлопывать повторы."""

    kind: str
    dialog_id: str
    dialog_title: str
    text: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "вид": self.kind,
            "диалог": self.dialog_title or "Без названия",
            "диалог_id": self.dialog_id,
            "что": self.text,
            **({"подробности": self.details} if self.details else {}),
        }


def _recent(record: dict, since: datetime) -> bool:
    raw = record.get("created_at")
    if not raw:
        return False
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at >= since


def inspect_dialog(dialog_id: str, title: str, records: list[dict], *, now: datetime | None = None) -> list[Finding]:
    """Все замечания к одному диалогу. Чистая функция: ни БД, ни сети."""
    now = now or datetime.now(timezone.utc)
    since = now - LOOKBACK
    found: list[Finding] = []
    if not records:
        return found

    def add(kind: str, text: str, **details: Any) -> None:
        found.append(Finding(kind=kind, dialog_id=dialog_id, dialog_title=title, text=text, details=details))

    # 1. Сколько уйдёт в модель на следующем ходу — считаем ровно тем же
    # кодом, что и отправляет (fold_stale_tool_results), иначе замер
    # разошёлся бы с реальностью.
    prompt_chars = sum(len(r.get("content") or "") for r in fold_stale_tool_results(records))
    if prompt_chars > MAX_PROMPT_CHARS:
        add(
            "раздутый_диалог",
            f"На каждый ход уходит {prompt_chars} символов — ответы будут хуже. "
            "Стоит начать новый диалог или сжать историю (кнопка «Сжать» в диалоге).",
            символов=prompt_chars,
            порог=MAX_PROMPT_CHARS,
        )

    # 2. Один и тот же отказ инструмента много раз: модель не понимает,
    # чего от неё хотят, и крутится. Считаем по НАЧАЛУ текста — хвост у
    # таких ошибок обычно одинаковый, а различают их первые слова.
    # Только за последнюю неделю, как и остальные проверки. Без этого
    # сторож нагоняет вечно: первый же прогон 10.10 нашёл цикл из 14
    # ошибок, который УЖЕ ПОЧИНЕН (add_table_row теперь возвращает
    # row_id), — но следы остаются в диалоге навсегда, и напоминание о
    # них каждые шесть часов научило бы смахивать сводку не глядя.
    errors: Counter[str] = Counter()
    for r in records:
        if r.get("role") != "tool" or not _recent(r, since):
            continue
        content = r.get("content") or ""
        if '"error"' in content[:40]:
            errors[content[:90]] += 1
    for text, times in errors.items():
        if times >= REPEATED_ERROR_TIMES:
            add(
                "циклит_на_ошибке",
                f"Инструмент {times} раз вернул одну и ту же ошибку — похоже, модель не может её обойти.",
                повторов=times,
                ошибка=text,
            )

    # 3. Сохранённый отказ — ход, который человек увидел как «попробуй
    # позже». Дважды в одном диалоге это уже не сбой сети.
    refusals = [
        r for r in records
        if r.get("role") == "assistant"
        and "Не получилось" in (r.get("content") or "")
        and _recent(r, since)
    ]
    if refusals:
        add(
            "ход_не_состоялся",
            f"Ассистент {len(refusals)} раз(а) за неделю ответил «не получилось» — человек это видел.",
            случаев=len(refusals),
            последний=refusals[-1].get("created_at", ""),
        )

    # 4. Непомерный результат инструмента. После потолка на чтении он уже
    # не убивает ход, но означает, что какой-то тул отдаёт мегабайты, —
    # и это надо чинить у источника, а не терпеть.
    for r in records:
        if r.get("role") != "tool":
            continue
        size = len(r.get("content") or "")
        if size > MAX_RESULT_CHARS and _recent(r, since):
            add(
                "непомерный_результат",
                f"Инструмент {r.get('name') or '?'} вернул {size} символов — обрезается, данные теряются.",
                инструмент=r.get("name") or "",
                символов=size,
            )
            break  # одного примера на диалог достаточно

    # 5. Подсказку «это есть в твоей базе» модель получила и не пошла
    # смотреть. Ровно случай с «Кейтеркой»: веб-поиск сказал, что слово
    # есть в двух заметках, а ответ был из общих знаний.
    for i, r in enumerate(records):
        if r.get("role") != "tool" or OWN_BASE_KEY not in (r.get("content") or ""):
            continue
        if not _recent(r, since):
            continue
        looked = any(
            tc.get("name") in ("get_note", "search_base", "get_list", "get_table")
            for later in records[i + 1:]
            for tc in (later.get("tool_calls") or [])
        )
        if not looked:
            add(
                "подсказка_проигнорирована",
                "Веб-поиск сообщил, что спрошенное есть в записях пользователя, "
                "но модель их не открыла и ответила из общих знаний.",
            )
            break

    return found


# --- здоровье хоста: своп ------------------------------------------------
#
# ПОЧЕМУ ЭТО ЗДЕСЬ, А НЕ В ЖУРНАЛЕ. 17.10.2026 после ребута на новое ядро
# zram не поднялся (модуль лежит в linux-modules-extra, а тот был
# поставлен по номеру старого ядра — см. roles/baseline). Сервер остался
# со свопом ТОЛЬКО в файле внутри LUKS — ровно тот путь, который 19.08 и
# 11.09 вешал машину на шесть часов (kswapd → dm-crypt → loop → page
# cache → kswapd).
#
# Отказ zramswap.service был в журнале с первой секунды загрузки, и
# существующий notenotes-alert тоже пишет только в журнал. Журнал никто
# не читает, пока не случится беда. Самопроверка же уходит в утреннюю
# сводку — то есть пропажу zram человек увидит наутро, а не по зависанию.
#
# /proc/swaps не изолирован в контейнере: это своп хоста.

def inspect_host_swap(swaps_text: str) -> Finding | None:
    """Замечание, если дисковый своп есть, а zram перед ним — нет."""
    lines = [line.split() for line in (swaps_text or "").splitlines()[1:] if line.strip()]
    has_zram = any(parts and "zram" in parts[0] for parts in lines)
    has_disk = any(len(parts) > 1 and parts[1] == "file" for parts in lines)
    if has_disk and not has_zram:
        return Finding(
            kind="нет_zram",
            dialog_id="",
            dialog_title="сервер",
            text=(
                "zram не поднят: своп остался только в файле внутри LUKS — тот же путь, "
                "что вешал сервер 19.08 и 11.09. Проверь linux-modules-extra для текущего ядра."
            ),
        )
    return None


def _read_proc_swaps() -> str:
    try:
        with open("/proc/swaps", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        # Нет доступа — молчим: самопроверка не должна сама становиться
        # источником ложных тревог.
        return ""


async def collect_findings(db) -> list[Finding]:
    """Пройти по всем живым диалогам. Порядок — сначала самые большие."""
    dialogs = (
        await db.execute(select(Item).where(Item.material_type == "dialog", Item.deleted_at.is_(None)))
    ).scalars().all()
    findings: list[Finding] = []
    # Хост — первым: если сервер под угрозой зависания, это важнее любого
    # промаха ассистента.
    swap = inspect_host_swap(_read_proc_swaps())
    if swap is not None:
        findings.append(swap)
    for item in dialogs:
        records = item.properties.get("messages") or []
        findings.extend(inspect_dialog(str(item.id), item.title or "", records))
    return findings


async def _check_once() -> int:
    async with async_session() as db:
        findings = await collect_findings(db)
    for f in findings:
        logger.warning("Самопроверка [%s] «%s»: %s", f.kind, f.dialog_title[:40], f.text)
    return len(findings)


async def run_worker() -> None:
    while True:
        try:
            count = await _check_once()
            if not count:
                logger.info("Самопроверка: замечаний нет")
        except Exception:
            logger.exception("Ошибка самопроверки")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)


# --- инструмент -----------------------------------------------------------

from app.llm.base import ToolDefinition  # noqa: E402  (ниже, чтобы шапка модуля читалась первой)
from app.tools.registry import ToolContext  # noqa: E402

DEFINITION = ToolDefinition(
    name="self_check",
    description=(
        "Самопроверка приложения: где ассистент за последнюю неделю сработал плохо — "
        "раздутые диалоги, застревание на одной и той же ошибке инструмента, ходы, "
        "закончившиеся «не получилось», проигнорированные подсказки. Вызывай, когда "
        "спрашивают «что у нас не так», «почему ты тупишь», «всё ли работает» — и НЕ "
        "вызывай для обычных вопросов по содержимому базы. Отвечая, не оправдывайся и не "
        "пересказывай машинные поля: скажи, что нашлось, своими словами."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)


async def handle(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Замечания по ВСЕМ диалогам установки, не только своим.

    Так и задумано: это не персональная статистика, а состояние
    приложения — то, за чем владелец и приходит с вопросом «почему он
    тупит». Содержимого диалогов наружу не отдаём, только названия и
    машинные признаки.
    """
    findings = await collect_findings(ctx.db)
    return {
        "замечаний": len(findings),
        "список": [f.as_dict() for f in findings],
        **({"итог": "Замечаний нет — за последнюю неделю ассистент не спотыкался."} if not findings else {}),
    }
