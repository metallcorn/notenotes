from __future__ import annotations

from app.document_reflow import split_into_chunks
from app.llm.base import Message

# Реальная жалоба: run_dialog_turn (routers/dialogs.py) шлёт в LLM ВСЮ
# накопленную историю диалога на каждый ход, без окна и без потолка —
# для диалога, разросшегося за пару недель до 140+ сообщений, каждый ход
# стал занимать минуты (замерено по живым логам: ранние ходы 5-30с,
# поздние — 2-3+ минуты, ровно по мере роста истории). Это модуль сжатия
# истории в одну сводку — ручное действие пользователя (ТЗ §10a: не
# фоновый процесс), с обязательным откатом (ТЗ §7/§21.9: "суммаризация
# деструктивна и без отката невосстановима"). Форма модуля — как у
# document_reflow.py: константы -> чистые хелперы -> LLM-вызывающая
# функция, независимо тестируется без БД/LLM.

_MAX_CHUNK_CHARS = 8000  # тот же порядок, что document_reflow._MAX_CHARS
_DEFAULT_KEEP_LAST = 20
_MIN_OLD_MESSAGES = 10  # меньше — сжимать не стоит, экономия не окупает LLM-вызов


def find_cut_index(records: list[dict], keep_last: int) -> int:
    """Индекс начала "хвоста", который остаётся дословно. Не режет ровно по
    len(records) - keep_last, а идёт НАЗАД от этой точки до ближайшего
    role == "user" — единственная точка, гарантированно не разрывающая
    assistant.tool_calls[i].id и его tool-результат (те всегда лежат между
    двумя user-репликами, никогда не начинаются с них). Экономия и так на
    порядок (сжимаем большую часть истории), пара лишних дословных
    сообщений в хвосте не критична."""
    if keep_last <= 0 or not records:
        return 0
    i = max(len(records) - keep_last, 0)
    while i > 0 and records[i]["role"] != "user":
        i -= 1
    return i


def _describe_tool_call(tc: dict) -> str:
    args = tc.get("arguments") or {}
    hint = str(args.get("query") or args.get("title") or args.get("text") or "").strip()
    return f"{tc['name']}({hint[:60]})" if hint else str(tc["name"])


def render_old_messages_for_summary(records: list[dict]) -> str:
    """Компактное текстовое представление старой части истории для LLM —
    НЕ сырой _flatten_transcript и не JSON tool_calls/tool-результатов
    (это съело бы бюджет чанка на payload'ы, а не на смысл разговора).
    Записи роли "tool" (сырые результаты вызовов) не льются вообще — их
    суть уже отражена в последующем ответе ассистента. Более ранние
    сводки (is_summary — сжали уже сжатое) передаются как есть, их
    content уже сжат. Строки соединяются двойным переносом — split_into_chunks
    (document_reflow.py) режет именно по "\\n\\n", каждая реплика должна быть
    отдельным "абзацем" для него, иначе чанкинг упадёт на грубую нарезку по
    символам вместо границ реплик."""
    lines: list[str] = []
    for r in records:
        role, content = r.get("role"), (r.get("content") or "").strip()
        if role == "user":
            lines.append(f"Пользователь: {content}")
        elif role == "assistant":
            if r.get("is_summary"):
                lines.append(f"[Ранее уже сжатая часть разговора]: {content}")
                continue
            calls = r.get("tool_calls") or []
            if calls:
                calls_text = ", ".join(_describe_tool_call(tc) for tc in calls)
                suffix = f": {content}" if content else ""
                lines.append(f"Ассистент [вызвал: {calls_text}, получил результат]{suffix}")
            elif content:
                lines.append(f"Ассистент: {content}")
        # role == "tool" — сырые результаты, см. докстринг выше.
    return "\n\n".join(lines)


_SUMMARY_SYSTEM_PROMPT = (
    "Тебе дана более ранняя часть диалога пользователя с ассистентом-помощником "
    "(заметки, списки, напоминания, поиск) в сжатом текстовом виде — реплики "
    "пользователя дословно, действия ассистента кратко, без сырых аргументов "
    "и результатов инструментов.\n\n"
    "Перескажи одним связным резюме на русском: какие темы обсуждались, какие "
    "решения/факты были приняты или сообщены (даты, договорённости, созданные "
    "или изменённые заметки/списки, важные предпочтения пользователя), чем "
    "закончился каждый сюжет. Не придумывай ничего, чего не было, и не теряй "
    "конкретику (имена, даты, числа, названия) — по этому резюме разговор "
    "будет продолжаться дальше, как будто исходные реплики не стирались.\n\n"
    "Ответь только текстом резюме, без вступлений и заголовков."
)
_REDUCE_SYSTEM_PROMPT = (
    "Ниже — несколько частичных резюме последовательных фрагментов ОДНОГО "
    "разговора, в хронологическом порядке. Слей их в одно связное резюме "
    "целиком, без повторов и швов между фрагментами, ничего не теряя по "
    "существу. Ответь только текстом итогового резюме."
)


async def _summarize_chunk(client, text: str) -> str:
    response = await client.chat(
        [Message(role="system", content=_SUMMARY_SYSTEM_PROMPT), Message(role="user", content=text)], []
    )
    return response.message.content.strip()


async def _reduce_summaries(client, partials: list[str]) -> str:
    joined = "\n\n---\n\n".join(f"Фрагмент {i + 1}:\n{s}" for i, s in enumerate(partials))
    response = await client.chat(
        [Message(role="system", content=_REDUCE_SYSTEM_PROMPT), Message(role="user", content=joined)], []
    )
    return response.message.content.strip()


async def summarize_records(client, old_records: list[dict]) -> str:
    """Единственная функция здесь, что реально дёргает LLM — принимает
    готовый client (dependency injection), чтобы эндпоинт и тесты могли
    подменить его моком, не завязываясь на реального провайдера — тот же
    приём, что _reflow_chunk в document_reflow.py."""
    text = render_old_messages_for_summary(old_records)
    chunks = split_into_chunks(text, _MAX_CHUNK_CHARS)
    partials = [await _summarize_chunk(client, c) for c in chunks]
    return partials[0] if len(partials) == 1 else await _reduce_summaries(client, partials)
