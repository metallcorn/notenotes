"""Прогон ролплей-сценариев и сбор отчёта.

Главная метрика — РАЗБРОС балла между переформулировками одного и того же
запроса, а не средний балл: замер 2026-09-03 показал, что один сценарий,
переписанный другими словами, даёт 2/5 и 5/5. Поэтому каждый сценарий
гоняется несколько раз с разными первыми репликами, а в отчёте
показывается min/max/среднее.

СКОЛЬКО ПРОГОНОВ НУЖНО. Трёх НЕ хватает — это установлено, а не мнение.
Один и тот же вариант, прогнанный дважды подряд, давал по сценарию «ужин»
4,4,3 и 1,3,1. Все сравнения на трёх прогонах (4.15 против 3.81 против
4.33 в разные дни) были игрой в шум. Для вывода «стало лучше/хуже» нужно
десять; три годятся только чтобы поймать грубую поломку.

ТОЧКА ОТСЧЁТА — 2026-09-09, 10 прогонов на сценарий, 90 диалогов, ~1 час.
Отчёты лежат в .eval-reports/, а он в .gitignore, поэтому цифры здесь:

    note_link             5.0   5,5,5,5,5,5,5,5,5,5
    list_flow             4.9   5,5,5,5,5,5,5,5,4,5
    web_fact_conflicting  4.7   5,5,5,4,5,5,4,5,5,4
    web_fact_absent       4.6   5,5,5,5,5,5,5,5,1,5
    high_stakes_medical   4.2   5,3,3,5,5,3,3,5,5,5
    foreigner_documents   3.7   4,4,4,4,4,2,4,3,4,4
    newbie_onboarding     3.5   5,2,4,3,1,2,4,5,5,4
    dinner_planning       3.1   4,4,3,2,2,3,1,5,3,4
    travel_visa           2.8   3,3,3,2,3,2,1,4,3,4

    итого 4.06; без галлюцинаций 74 из 90; провалов (1-2 балла) 11 из 90.

Что из этого видно и НЕ было видно на трёх прогонах:
  - web_fact_absent казался закрытым (всегда 5,5,5), а на самом деле
    примерно раз в десять раз выдумывает ссылку;
  - high_stakes_medical давал то 5,5,5, то 1,3,5 — по трём прогонам
    нельзя было сказать, работает ли защита от выдуманных доз. По десяти
    видно, что работает: худшее 3, единиц и двоек нет вовсе;
  - travel_visa (2.8) — самое слабое место, и это системно, а не
    невезение: все десять прогонов называют безвизовый срок, которого
    модель не знает.

Изоляция (каждое требование выучено на реальной ошибке того же дня):
  - свой одноразовый User на КАЖДЫЙ прогон. remember_fact пишет в память
    пользователя, она не привязана к спейсу и не удаляется вместе с ним —
    при переиспользовании аккаунта выдуманные факты из одного прогона
    «протекали» в следующий и выглядели как галлюцинация модели;
  - свой Space, всё удаляется после прогона вместе с памятью и юзером;
  - web_search ВСЕГДА застаблен, реальных обращений к Tavily ноль
    (у пользователя 1000 запросов в месяц).

Варианты «осмысления перед действием» (--variant) подменяются ТОЛЬКО
внутри этого процесса: боевое поведение ассистента не трогается, прод
продолжает работать как настроен.

Запуск — через scripts/assistant-eval.sh (там изоляция контейнера и БД).
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import statistics
import time
from datetime import datetime

import httpx

from app.core.config import get_settings
from app.db import async_session
from app.llm.base import Message
from app.llm.mistral import MistralClient
from app.models import AssistantMemory, Space, SpaceMember, User
from app.routers.items import create_item_row
from app.security import hash_password
from eval.scenarios import EMPTY_SEARCH, RECORDED_BRAKE_DISCS, SCENARIOS, TESTER_SYSTEM, judge_prompt

MAX_TURNS = 12

# Троттлинг вокруг КАЖДОГО вызова LLM: прогон устраивает десятки диалогов
# подряд, чего живой пользователь не делает. В прод-клиенте этого нет и не
# нужно — только здесь.
CALL_DELAY_SECONDS = 1.5
MAX_RETRIES = 6
BACKOFF_BASE_SECONDS = 4

_last_call_at = 0.0
_stats = {"calls": 0, "retries": 0, "search_stubs": 0}


class ThrottledClient:
    """Обёртка над LLMClient: пауза между вызовами и бэкофф на 429."""

    def __init__(self, inner):
        self._inner = inner

    async def chat(self, messages, tools, cache_key=None):
        # cache_key появился вместе с кэшем промпта (2026-09-05) — обёртка
        # обязана принимать всю сигнатуру LLMClient и пробрасывать её
        # дальше, иначе замер падает на первом же вызове. Поймано живьём:
        # харнесс не запускали четверо суток после той правки.
        global _last_call_at
        for attempt in range(MAX_RETRIES):
            elapsed = time.monotonic() - _last_call_at
            if elapsed < CALL_DELAY_SECONDS:
                await asyncio.sleep(CALL_DELAY_SECONDS - elapsed)
            _last_call_at = time.monotonic()
            try:
                result = await self._inner.chat(messages, tools, cache_key=cache_key)
                _stats["calls"] += 1
                return result
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 429 or attempt == MAX_RETRIES - 1:
                    raise
                _stats["retries"] += 1
                wait = BACKOFF_BASE_SECONDS * (2**attempt)
                print(f"      [429, жду {wait}s]", flush=True)
                await asyncio.sleep(wait)
        raise RuntimeError("недостижимо")


# --- варианты «осмысления перед действием» (см. план, этап 1) -------------

# B: просим планировать в том же вызове, без второй модели и лишних
# запросов — дешёвая версия того, что рассуждающие модели делают сами.
PLAN_FIRST_FRAGMENT = (
    "ПЕРЕД любым действием сформулируй про себя задачу в явном виде: что "
    "именно просит пользователь, какие данные для этого нужны, есть ли они "
    "уже или их надо получить тулом. Разные формулировки одной просьбы "
    "должны приводить к одному и тому же плану. Только после этого "
    "действуй. Сам план в ответ не пиши — пользователю нужен результат, а "
    "не рассуждения."
)

VARIANTS = {
    "baseline": "как в проде: mistral-small, промпт без изменений",
    "plan_prompt": "B: абзац «сначала сформулируй задачу», 0 доп. вызовов",
    "magistral": "A: рассуждающая модель magistral-small-latest",
    # Температура ДО 2026-09-05 не задавалась вовсе — работали на дефолте
    # Mistral (0.3 у всех моделей, проверено через GET /v1/models). Это
    # подозреваемый источник шума самого замера: один и тот же вариант,
    # прогнанный дважды, дал по сценарию «ужин» 4,4,3 и 1,3,1. Часть этого
    # разброса — просто сэмплирование, а не поведение ассистента.
    "temp_zero": "T=0: детерминированное сэмплирование вместо дефолтных 0.3",
    "temp_low": "T=0.1: почти детерминированно, но без полной жёсткости",
}


async def _make_user(db, memory: list[str]) -> User:
    suffix = secrets.token_hex(4)
    user = User(
        username=f"eval_{suffix}",
        password_hash=hash_password(secrets.token_urlsafe(16)),
        name=f"Eval {suffix}",
    )
    db.add(user)
    await db.flush()
    for fact in memory:
        db.add(AssistantMemory(user_id=user.id, content=fact))
    await db.flush()
    return user


async def _cleanup(db, user: User, space_id) -> None:
    from sqlalchemy import delete as sa_delete

    space = await db.get(Space, space_id)
    if space is not None:
        await db.delete(space)
    await db.execute(sa_delete(AssistantMemory).where(AssistantMemory.user_id == user.id))
    fresh = await db.get(User, user.id)
    if fresh is not None:
        await db.delete(fresh)
    await db.commit()


async def run_one(db, scenario: dict, opening: str, tester) -> str:
    """Один диалог. Возвращает transcript со служебными записями."""
    user = await _make_user(db, scenario.get("memory", []))
    space = Space(name="Eval sandbox", owner_id=user.id)
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=user.id))
    await db.commit()

    for note in scenario.get("seed_notes", []):
        await create_item_row(
            db, space_id=space.id, author_id=user.id, material_type="note",
            title=note["title"], content=note["content"],
        )
    dialog = await create_item_row(
        db, space_id=space.id, author_id=user.id, material_type="dialog",
        title=f"Eval: {scenario['name']}", properties={"messages": []},
    )
    await db.commit()

    from app.routers.dialogs import run_dialog_turn

    lines: list[str] = []
    ended = "лимит ходов"
    for turn in range(MAX_TURNS):
        if turn == 0:
            msg = opening  # фиксированная первая реплика — это и есть вариация
        else:
            prompt = (
                f"{scenario['persona']}\n\nЦель: {scenario['goal']}\n\n"
                "---Транскрипт---\n" + "\n".join(lines)
                + "\n\n---\nНапиши СЛЕДУЮЩУЮ реплику пользователя (только текст "
                "сообщения). Пора закончить — ответь ровно [END: причина]."
            )
            resp = await tester.chat(
                [Message(role="system", content=TESTER_SYSTEM), Message(role="user", content=prompt)], []
            )
            msg = resp.message.content.strip()
            if msg.startswith("[END"):
                ended = msg
                break

        lines.append(f"ПОЛЬЗОВАТЕЛЬ: {msg}")
        history_len = len(dialog.properties.get("messages", []))
        records = await run_dialog_turn(db, user, dialog, msg)
        for r in records[history_len:]:
            if r.get("role") == "assistant":
                for tc in r.get("tool_calls", []):
                    lines.append(f"АССИСТЕНТ [tool_call]: {tc.get('name')}({tc.get('arguments')})")
                if r.get("content"):
                    lines.append(f"АССИСТЕНТ: {r['content']}")
                # Кнопки НЕ лежат в tool_calls: dialogs.py намеренно вынимает
                # suggest_replies из real_tool_calls (это разметка UI, а не
                # тул с побочным эффектом) и кладёт варианты в отдельное поле.
                # Без этой строки судья кнопок не видел вовсе и во всех 9
                # прогонах сценария новичка писал «suggest_replies не вызван» —
                # оценки были испорчены багом харнесса, а не поведением
                # ассистента.
                if r.get("suggested_replies"):
                    lines.append(f"АССИСТЕНТ [кнопки]: {r['suggested_replies']}")
            elif r.get("role") == "tool":
                lines.append(f"TOOL_RESULT: {(r.get('content') or '')[:500]}")

    await db.delete(dialog)
    await _cleanup(db, user, space.id)
    return "\n".join(lines) + f"\n\n[Завершён: {ended}]"


def _parse_score(verdict: str) -> int | None:
    for line in verdict.splitlines():
        if line.strip().upper().startswith("ОЦЕНКА"):
            for token in line.replace("/", " ").split():
                if token.isdigit() and 1 <= int(token) <= 5:
                    return int(token)
    return None


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ролплей-оценка ассистента")
    parser.add_argument("--variant", default="baseline", choices=sorted(VARIANTS))
    parser.add_argument("--runs", type=int, default=3, help="прогонов на сценарий (разными формулировками)")
    parser.add_argument("--scenario", default=None, help="только один сценарий по имени")
    parser.add_argument("--out", default="/tmp/assistant-eval.md")
    args = parser.parse_args()

    settings = get_settings()
    import app.routers.dialogs as dm

    # --- стаб web_search: ни одного обращения к Tavily ---
    real_dispatch = dm.dispatch
    search_mode = {"mode": "none"}

    async def stub_dispatch(name, ctx, arguments, disabled=None):
        if name == "web_search":
            _stats["search_stubs"] += 1
            if search_mode["mode"] == "recorded":
                return RECORDED_BRAKE_DISCS
            return EMPTY_SEARCH
        return await real_dispatch(name, ctx, arguments, disabled=disabled)

    dm.dispatch = stub_dispatch

    assistant_model = "magistral-small-latest" if args.variant == "magistral" else settings.llm_model
    # None — не передавать параметр вовсе (дефолт провайдера), это и есть
    # baseline. 0.0 и 0.1 передаются явно.
    assistant_temp = {"temp_zero": 0.0, "temp_low": 0.1}.get(args.variant)
    assistant = ThrottledClient(
        MistralClient(api_key=settings.llm_api_key, model=assistant_model, temperature=assistant_temp)
    )
    # Тестер и судья — ВСЕГДА T=0, независимо от варианта. Это настройка
    # измерительного прибора, а не продукта: судья при дефолтных 0.3 мог
    # поставить один и тот же транскрипт то на 4, то на 2, и этот шум
    # смешивался с настоящей разницей между вариантами. Именно из-за него
    # 2026-09-03 не удалось сравнить три варианта: один и тот же вариант,
    # прогнанный дважды, дал по сценарию «ужин» 4,4,3 и 1,3,1.
    #
    # Тестер тоже: его собственная случайность добавляла расхождение
    # диалогов сверх того, что вносил ассистент. Полной воспроизводимости
    # это не даёт (реплики тестера всё равно зависят от ответов ассистента),
    # но убирает один из трёх источников шума целиком.
    tester = ThrottledClient(
        MistralClient(api_key=settings.llm_api_key, model="mistral-medium-latest", temperature=0.0)
    )
    judge = ThrottledClient(
        MistralClient(api_key=settings.llm_api_key, model="mistral-medium-latest", temperature=0.0)
    )

    original_get = dm.get_llm_client
    original_base = dm.SYSTEM_PROMPT_BASE
    dm.get_llm_client = lambda provider=None, _c=assistant: _c
    if args.variant == "plan_prompt":
        dm.SYSTEM_PROMPT_BASE = original_base + "\n\n" + PLAN_FIRST_FRAGMENT

    scenarios = [s for s in SCENARIOS if args.scenario in (None, s["name"])]
    if not scenarios:
        raise SystemExit(f"нет сценария с именем {args.scenario}")

    print(f"вариант: {args.variant} — {VARIANTS[args.variant]}")
    temp_label = "дефолт провайдера (0.3)" if assistant_temp is None else str(assistant_temp)
    print(
        f"модель ассистента: {assistant_model}, температура: {temp_label}, "
        f"прогонов на сценарий: {args.runs}\n",
        flush=True,
    )

    started = time.monotonic()
    results: dict[str, list[int]] = {}
    parts: list[str] = []
    try:
        async with async_session() as db:
            for sc in scenarios:
                print(f"=== {sc['name']} ===", flush=True)
                search_mode["mode"] = sc.get("search_mode", "none")
                scores: list[int] = []
                for i in range(args.runs):
                    opening = sc["openings"][i % len(sc["openings"])]
                    print(f"  прогон {i + 1}/{args.runs}: {opening[:50]}...", flush=True)
                    transcript = await run_one(db, sc, opening, tester)
                    verdict = (
                        await judge.chat(
                            [Message(role="user", content=judge_prompt(sc) + "\n\n---TRANSCRIPT---\n" + transcript)],
                            [],
                        )
                    ).message.content.strip()
                    score = _parse_score(verdict)
                    if score is not None:
                        scores.append(score)
                    print(f"     оценка: {score}", flush=True)
                    parts.append(
                        f"## {sc['name']} — прогон {i + 1} (оценка {score})\n\n"
                        f"**Первая реплика:** {opening}\n\n"
                        f"<details><summary>Transcript</summary>\n\n```\n{transcript}\n```\n</details>\n\n"
                        f"**Вердикт:**\n\n{verdict}\n"
                    )
                results[sc["name"]] = scores
                if scores:
                    print(f"  → min {min(scores)}, max {max(scores)}, разброс {max(scores) - min(scores)}\n", flush=True)
    finally:
        dm.get_llm_client = original_get
        dm.SYSTEM_PROMPT_BASE = original_base
        dm.dispatch = real_dispatch

    minutes = (time.monotonic() - started) / 60
    out = [
        f"# Ролплей-оценка ассистента — вариант «{args.variant}»\n",
        f"{VARIANTS[args.variant]}\n",
        f"Модель ассистента: `{assistant_model}` · температура: {temp_label} · "
        f"прогонов на сценарий: {args.runs} · "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} · {minutes:.0f} мин\n",
        f"Вызовов LLM: {_stats['calls']} · повторов по 429: {_stats['retries']} · "
        f"обращений к Tavily: **0** (перехвачено стабом: {_stats['search_stubs']})\n",
        "## Сводка\n",
        "Главная метрика — РАЗБРОС между переформулировками: он показывает, "
        "насколько поведение зависит от того, какими словами задан один и тот же "
        "вопрос.\n",
        "| Сценарий | Оценки | Среднее | Разброс |",
        "|---|---|---|---|",
    ]
    all_spreads: list[int] = []
    for name, scores in results.items():
        if not scores:
            out.append(f"| {name} | — | — | — |")
            continue
        spread = max(scores) - min(scores)
        all_spreads.append(spread)
        out.append(
            f"| {name} | {', '.join(str(s) for s in scores)} | "
            f"{statistics.mean(scores):.1f} | **{spread}** |"
        )
    flat = [s for scores in results.values() for s in scores]
    if flat:
        out.append("")
        out.append(
            f"**Итого:** средний балл {statistics.mean(flat):.2f}, "
            f"средний разброс внутри сценария {statistics.mean(all_spreads):.2f}, "
            f"максимальный разброс {max(all_spreads)}."
        )
    out.append("")
    out.append("\n\n---\n\n".join(parts))

    with open(args.out, "w") as f:
        f.write("\n".join(out))
    print(f"\nГотово: {args.out}")
    if flat:
        print(f"средний балл {statistics.mean(flat):.2f}, средний разброс {statistics.mean(all_spreads):.2f}")


if __name__ == "__main__":
    asyncio.run(main())
