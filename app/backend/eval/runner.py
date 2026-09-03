"""Прогон ролплей-сценариев и сбор отчёта.

Главная метрика — РАЗБРОС балла между переформулировками одного и того же
запроса, а не средний балл: замер 2026-09-03 показал, что один сценарий,
переписанный другими словами, даёт 2/5 и 5/5. Поэтому каждый сценарий
гоняется несколько раз с разными первыми репликами, а в отчёте
показывается min/max/среднее.

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

    async def chat(self, messages, tools):
        global _last_call_at
        for attempt in range(MAX_RETRIES):
            elapsed = time.monotonic() - _last_call_at
            if elapsed < CALL_DELAY_SECONDS:
                await asyncio.sleep(CALL_DELAY_SECONDS - elapsed)
            _last_call_at = time.monotonic()
            try:
                result = await self._inner.chat(messages, tools)
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
    assistant = ThrottledClient(MistralClient(api_key=settings.llm_api_key, model=assistant_model))
    tester = ThrottledClient(MistralClient(api_key=settings.llm_api_key, model="mistral-medium-latest"))
    judge = ThrottledClient(MistralClient(api_key=settings.llm_api_key, model="mistral-medium-latest"))

    original_get = dm.get_llm_client
    original_base = dm.SYSTEM_PROMPT_BASE
    dm.get_llm_client = lambda provider=None, _c=assistant: _c
    if args.variant == "plan_prompt":
        dm.SYSTEM_PROMPT_BASE = original_base + "\n\n" + PLAN_FIRST_FRAGMENT

    scenarios = [s for s in SCENARIOS if args.scenario in (None, s["name"])]
    if not scenarios:
        raise SystemExit(f"нет сценария с именем {args.scenario}")

    print(f"вариант: {args.variant} — {VARIANTS[args.variant]}")
    print(f"модель ассистента: {assistant_model}, прогонов на сценарий: {args.runs}\n", flush=True)

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
        f"Модель ассистента: `{assistant_model}` · прогонов на сценарий: {args.runs} · "
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
