import json
import logging
import re
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.llm.base import Message, ToolCall
from app.llm.factory import get_llm_client
from app.models import AssistantMemory, Item, User
from app.routers.items import create_item_row
from app.schemas.dialog import DialogCreate, DialogOut, DialogSummaryOut, MessageCreate
from app.tools.registry import ToolContext, dispatch, get_tool_definitions

router = APIRouter(prefix="/api/dialogs", tags=["dialogs"])
logger = logging.getLogger(__name__)

# Предохранитель от зацикливания агента: LLM может звать инструменты сколько
# угодно раз внутри одного хода, но не бесконечно — на такой глубине что-то
# явно пошло не так, лучше вернуть частичный результат, чем платить за LLM
# без остановки.
MAX_TOOL_ITERATIONS = 8

SYSTEM_PROMPT_BASE = (
    "Ты — ассистент базы знаний Notenotes. Ты работаешь внутри диалога с "
    "пользователем и можешь искать и изменять его заметки и списки через "
    "доступные инструменты. Отвечай на языке пользователя (по умолчанию — "
    "русский).\n\n"
    "Для точных вычислений (суммы, проценты, разница дат, сортировка чисел, "
    "агрегация данных из заметки/списка) — используй run_python, а не считай "
    "в уме: языковые модели систематически ошибаются в арифметике, а тул "
    "считает точно. Не показывай пользователю код, если не просил — только "
    "результат.\n\n"
    "Отвечай КОРОТКО. Пользователь читает это в чате, не в документе. "
    "Обычный ответ — 1-3 предложения. Не добавляй разделы вроде «Что "
    "дальше?», «Варианты действий», списки идей и предложений, если тебя "
    "об этом не просили явно — для выбора следующего шага используй "
    "suggest_replies (коротко), а не абзацы текста. Не пересказывай, что "
    "ты только что сделал, развёрнуто — одной фразы достаточно («Готово, "
    "заметка создана»). Если пользователь просит подробностей — тогда "
    "разворачивайся, но по умолчанию будь лаконичен.\n\n"
    "У каждого твоего ответа есть кнопка «Скопировать», которая копирует "
    "ВЕСЬ текст сообщения целиком, как есть. Если пользователь просит "
    "составить текст для отправки/вставки куда-то (письмо, сообщение, пост) "
    "— пиши ТОЛЬКО этот текст, без вступления вроде «Вот текст письма:» и "
    "без комментариев после, иначе они попадут в буфер обмена вместе с "
    "текстом. Комментарий или уточняющий вопрос — только отдельным сообщением "
    "до или после, не внутри того же ответа.\n\n"
    "Никогда не выдумывай факты — ни содержимое заметки/списка, ни то, что "
    "нашлось (или не нашлось) в вебе. list_folders, list_items_in_folder и "
    "list_all_items дают только название/id объектов, не их реальное "
    "содержимое; search_base даёт только обрезанный отрывок (300 символов "
    "для заметки) — НЕ полное содержимое. Прежде чем показать пользователю "
    "содержимое заметки или списка, отвечать по нему или считать, что там "
    "чего-то нет — сначала получи настоящие данные целиком (get_list — для "
    "списка, get_note — для заметки). Если данных нет или получить их не "
    "удалось — так и скажи, не сочиняй правдоподобный ответ. Никогда не "
    "изобретай инструмент, которого нет в списке доступных — если "
    "подходящего тула нет, так и скажи, не пытайся вызвать несуществующий.\n\n"
    "search_base ищет по буквальным словам и не понимает синонимы или "
    "однокоренные приставочные формы (например, 'купить', 'покупка' и "
    "'закупка' для него — разные слова, хотя по смыслу связаны). Если "
    "search_base ничего не нашёл, а объект правдоподобно должен быть в "
    "базе — прежде чем говорить «не нашёл», вызови list_all_items и "
    "просмотри заголовки сам: ты понимаешь смысл лучше текстового поиска. "
    "Но если это конкретное название реального места/заведения/бренда, а не "
    "что-то, что пользователь мог сам записать в заметки — не зацикливайся "
    "на внутреннем поиске: сразу попробуй web_search по этому названию "
    "напрямую, это вопрос про реальный мир, а не про базу заметок "
    "пользователя.\n\n"
    "Формулируя запрос для web_search про реальное место (бар, событие, "
    "магазин и т.п.) в другой стране — не используй только язык разговора "
    "с пользователем. Источников о конкретном городе на местном языке почти "
    "всегда на порядок больше, чем на русском (например, про Познань в "
    "Польше — по-польски, про Берлин — по-немецки или по-английски). Делай "
    "хотя бы один из запросов (можно параллельно, за один вызов LLM можно "
    "запросить сразу несколько web_search) на языке страны/города, о "
    "котором речь, а не только на языке пользователя — иначе результатов "
    "физически будет в разы меньше, даже если место реальное и известное.\n\n"
    "Особо строго с web_search: используй только то, что БУКВАЛЬНО есть в "
    "content результата. Никогда не составляй и не достраивай URL сам "
    "(особенно ссылки на Google Maps с координатами/place-id — их без "
    "реального источника не существует, ты их гарантированно придумаешь "
    "неверными). Если нужна ссылка на место — бери url прямо из результата "
    "поиска как есть, не переделывая; а если нужна именно ссылка-навигатор "
    "(чтобы пользователь мог проложить маршрут) — вызови create_maps_link с "
    "названием/адресом места, не пиши URL сам. Не связывай результаты разных "
    "запросов друг с другом по совпадению названия — если результат явно "
    "о другом городе/стране (например, ресторан в Алматы при вопросе про "
    "Познань), это не тот же объект, даже если название похоже. Если "
    "результаты поиска не дают точного ответа — прямо скажи, что нашёл "
    "только частично, и предложи пользователю проверить по ссылке самому, "
    "а не досочиняй недостающее. web_search по умолчанию depth=basic — "
    "если результаты оказались общими listicle-страницами без конкретного "
    "ответа на вопрос, ИЛИ если пользователь просил НЕСКОЛЬКО вариантов "
    "(список баров/мест/событий), а после отсева нерелевантного (билетные "
    "агрегаторы, другие города, дубли) осталось меньше 4-5 подходящих — "
    "попробуй тот же запрос ещё раз с depth=advanced (в пределах лимита "
    "вызовов на ход), прежде чем сдаваться с неполным списком. Если и "
    "после этого результат неполный или сомнительный — предложи "
    "suggest_replies с вариантом вроде «Поискать глубже», чтобы пользователь "
    "сам решил, стоит ли тратить ещё один поиск.\n\n"
    "Когда пользователь ссылается на папку или заметку неточно (своими "
    "словами, а не точным названием) — не угадывай молча. Найди похожие "
    "варианты (list_folders/search_base) и явно подтверди с пользователем, "
    "что ты понял правильно, прежде чем действовать. Если понимание "
    "подтвердилось и оно не очевидно из названия — сохрани его через "
    "remember_fact, чтобы не переспрашивать в следующий раз (сначала "
    "проверь list_memories, нет ли уже такого факта).\n\n"
    "Когда пользователь просит создать заметку/напоминание о конкретном "
    "будущем событии с известной датой (и желательно временем) — после "
    "создания заметки вызови create_calendar_event с теми же title/датой. "
    "Своей интеграции с календарём нет, но этот тул даёт пользователю кнопку "
    "«Добавить в календарь» — в один клик открывает системный диалог "
    "добавления события в Google/Apple/Outlook. Дату для start бери только "
    "из того, что явно сказал пользователь (или что нашлось в web_search "
    "как факт), — если дата не названа, сначала спроси, не угадывай.\n\n"
    "Перед тем как создавать что-то новое по теме — проверь search_base "
    "(по заметкам) и, если речь о конкретной папке, list_items_in_folder "
    "(по её содержимому), а не предполагай вслепую, что там есть или нет. "
    "Если папка пуста — не молчи об этом: предложи пользователю конкретный "
    "следующий шаг (например, какую заметку или список стоит завести) и "
    "уточни детали, а не только перечисляй вопросы одним блоком.\n\n"
    "Для отмечаемых пунктов (покупки, задачи, чек-листы) создавай список "
    "(create_list), а не заметку с текстом-имитацией списка — в списке "
    "пункты можно по-настоящему отмечать выполненными. Чтобы посмотреть "
    "реальные пункты — get_list. Чтобы отметить УЖЕ существующий пункт "
    "выполненным/купленным — toggle_list_entry, а не add_list_entry: "
    "add_list_entry создаёт новый пункт и превратит отметку в дублирование.\n\n"
    "Когда у твоего вопроса есть естественные короткие варианты ответа "
    "(выбор из существующих папок, да/нет, чек-лист или заметка) — заканчивай "
    "ход ВЫЗОВОМ ИНСТРУМЕНТА suggest_replies с 2-5 вариантами, чтобы "
    "пользователь мог кликнуть, а не печатать текстом. Никогда не пиши "
    "варианты просто текстом в духе «Варианты действий (можно выбрать "
    "кликом): 1. ... 2. ...» — если сам не вызвал suggest_replies, ничего "
    "кликабельного не появится и пользователь увидит нерабочий текст. Либо "
    "вызови инструмент, либо не упоминай про клик вообще. Если ожидается "
    "свободный текст — не вызывай suggest_replies.\n\n"
    "Удаление заметки перемещает её в корзину, не безвозвратно, но вызывай "
    "его только когда пользователь действительно просит удалить. Содержимое "
    "заметок пиши в формате Markdown. Веб-поиск используй экономно — только "
    "если ответа точно нет в базе пользователя."
)


def _build_system_prompt(memory_facts: list[str], custom_instructions: str) -> str:
    # ISO, не локализованное имя дня недели — strftime("%A") в контейнере
    # без ru_RU-локали всё равно выдал бы английское имя, а модели ISO-даты
    # достаточно, чтобы правильно резолвить "на этой неделе"/"вчера" и т.п.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"Сегодняшняя дата: {today} (ISO, UTC).\n\n" + SYSTEM_PROMPT_BASE
    if memory_facts:
        facts_block = "\n".join(f"- {f}" for f in memory_facts)
        prompt += f"\n\nЗапомненные факты об этом пользователе (используй их, не спрашивай заново):\n{facts_block}"
    if custom_instructions.strip():
        prompt += f"\n\nДополнительные инструкции от пользователя:\n{custom_instructions.strip()}"
    return prompt


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_dialog(db: AsyncSession, user: User, dialog_id: uuid.UUID) -> Item:
    item = await db.get(Item, dialog_id)
    if item is None or item.material_type != "dialog" or item.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диалог не найден")
    await ensure_space_access(db, item.space_id, user.id)
    return item


def _serialize(item: Item) -> DialogOut:
    return DialogOut(
        id=item.id,
        space_id=item.space_id,
        title=item.title,
        created_at=item.created_at,
        updated_at=item.updated_at,
        messages=item.properties.get("messages", []),
    )


def _to_llm_messages(records: list[dict], system_prompt: str) -> list[Message]:
    messages = [Message(role="system", content=system_prompt)]
    for r in records:
        role = r["role"]
        if role == "assistant":
            tool_calls = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc in r.get("tool_calls", [])
            ]
            messages.append(Message(role="assistant", content=r.get("content", ""), tool_calls=tool_calls))
        elif role == "tool":
            messages.append(
                Message(role="tool", content=r.get("content", ""), tool_call_id=r.get("tool_call_id"), name=r.get("name"))
            )
        else:
            messages.append(Message(role=role, content=r.get("content", "")))
    return messages


_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _strip_unverified_links(text: str, allowed_urls: set[str]) -> str:
    """Промпт один не удерживает модель от выдумывания правдоподобных
    ссылок (особенно Google Maps с координатами) — проверено на практике,
    инструкция "не выдумывай ссылки" не сработала. Поэтому режем на уровне
    кода: ссылка остаётся кликабельной, только если её URL буквально
    встречался в результатах web_search этого хода; иначе остаётся просто
    текст без ссылки."""

    def replace(match: re.Match[str]) -> str:
        link_text, url = match.group(1), match.group(2)
        return match.group(0) if url in allowed_urls else link_text

    return _MARKDOWN_LINK_RE.sub(replace, text)


def _flatten_transcript(records: list[dict]) -> str:
    # str(...) — подстраховка: если content когда-нибудь снова окажется не
    # строкой (см. MistralClient._from_wire), это не должно ронять весь
    # запрос ДО db.commit() и терять реплику пользователя целиком.
    parts = [str(r["content"]) for r in records if r["role"] in ("user", "assistant") and r.get("content")]
    return "\n\n".join(parts)


@router.get("", response_model=list[DialogSummaryOut])
async def list_dialogs(
    space_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Item]:
    await ensure_space_access(db, space_id, user.id)
    query = (
        select(Item)
        .where(Item.space_id == space_id, Item.material_type == "dialog", Item.deleted_at.is_(None))
        .order_by(Item.updated_at.desc())
    )
    return list((await db.execute(query)).scalars().all())


@router.post("", response_model=DialogOut, status_code=status.HTTP_201_CREATED)
async def create_dialog(
    payload: DialogCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DialogOut:
    await ensure_space_access(db, payload.space_id, user.id)
    item = await create_item_row(
        db,
        space_id=payload.space_id,
        author_id=user.id,
        material_type="dialog",
        title=payload.title or "Новый диалог",
        properties={"messages": []},
    )
    return _serialize(item)


@router.get("/{dialog_id}", response_model=DialogOut)
async def get_dialog(
    dialog_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DialogOut:
    item = await _get_dialog(db, user, dialog_id)
    return _serialize(item)


@router.delete("/{dialog_id}/messages/{message_id}", response_model=DialogOut)
async def delete_message(
    dialog_id: uuid.UUID,
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DialogOut:
    item = await _get_dialog(db, user, dialog_id)
    records: list[dict] = list(item.properties.get("messages", []))

    index = next((i for i, r in enumerate(records) if r["id"] == message_id), None)
    if index is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")

    target = records[index]
    if target["role"] == "tool":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Нельзя удалить результат инструмента отдельно — удали связанную реплику"
        )

    # Реплика ассистента с tool_calls тянет за собой свои "tool"-записи —
    # иначе при следующей отправке история для LLM была бы битой (висящий
    # tool_call без результата).
    tool_call_ids = {tc["id"] for tc in target.get("tool_calls", [])}
    remaining = [
        r
        for i, r in enumerate(records)
        if i != index and not (r["role"] == "tool" and r.get("tool_call_id") in tool_call_ids)
    ]

    item.properties = {**item.properties, "messages": remaining}
    item.content = _flatten_transcript(remaining)
    await db.commit()
    await db.refresh(item)
    return _serialize(item)


@router.post("/{dialog_id}/messages", response_model=DialogOut)
async def send_message(
    dialog_id: uuid.UUID,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DialogOut:
    item = await _get_dialog(db, user, dialog_id)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое сообщение")

    records: list[dict] = list(item.properties.get("messages", []))
    records.append({"id": str(uuid.uuid4()), "role": "user", "content": content, "created_at": _now_iso()})

    if item.title in ("", "Новый диалог"):
        item.title = content[:60]

    settings = get_settings()
    tool_definitions = get_tool_definitions(disabled=set(user.disabled_tools))
    ctx = ToolContext(db=db, user_id=user.id, space_id=item.space_id)
    web_search_calls = 0
    max_web_search_calls = settings.web_search_max_calls_per_turn
    verified_urls: set[str] = set()
    used_web_search = False
    used_advanced_web_search = False

    if not settings.llm_api_key:
        records.append(
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": "Ассистент ещё не настроен: не задан ключ LLM-провайдера (LLM_API_KEY).",
                "created_at": _now_iso(),
            }
        )
        item.properties = {**item.properties, "messages": records}
        item.content = _flatten_transcript(records)
        await db.commit()
        await db.refresh(item)
        return _serialize(item)

    llm_client = get_llm_client()

    memories_result = await db.execute(
        select(AssistantMemory.content).where(AssistantMemory.user_id == user.id).order_by(AssistantMemory.created_at)
    )
    memory_facts = [row[0] for row in memories_result.all()]
    system_prompt = _build_system_prompt(memory_facts, user.custom_instructions)

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            response = await llm_client.chat(_to_llm_messages(records, system_prompt), tool_definitions)
        except httpx.HTTPError:
            logger.exception("Ошибка обращения к LLM-провайдеру")
            records.append(
                {
                    "id": str(uuid.uuid4()),
                    "role": "assistant",
                    "content": "Не получилось получить ответ от LLM-провайдера — попробуй ещё раз чуть позже.",
                    "created_at": _now_iso(),
                }
            )
            break
        assistant_msg = response.message

        # suggest_replies — не настоящий тул с побочным эффектом, а разметка
        # для UI (чипы вместо свободного текста). Не кладём его в tool_calls
        # (не показываем как техническую "🔧 вызвал тул" строку) и не зовём
        # dispatch — сразу после него всегда конец хода, ждём клика/ввода.
        real_tool_calls = [tc for tc in assistant_msg.tool_calls if tc.name != "suggest_replies"]
        suggest_calls = [tc for tc in assistant_msg.tool_calls if tc.name == "suggest_replies"]

        assistant_record: dict = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": _strip_unverified_links(assistant_msg.content, verified_urls),
            "created_at": _now_iso(),
        }
        if real_tool_calls:
            assistant_record["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in real_tool_calls
            ]
        if suggest_calls:
            options: list[str] = []
            for tc in suggest_calls:
                options.extend(str(o).strip() for o in tc.arguments.get("options", []) if str(o).strip())
            assistant_record["suggested_replies"] = options
        records.append(assistant_record)

        if not assistant_msg.tool_calls:
            break

        for tc in real_tool_calls:
            if tc.name == "web_search":
                web_search_calls += 1
                if web_search_calls > max_web_search_calls:
                    result: dict = {"error": "Лимит веб-поиска на этот ход исчерпан"}
                else:
                    used_web_search = True
                    if str(tc.arguments.get("depth", "basic")).strip().lower() == "advanced":
                        used_advanced_web_search = True
                    result = await dispatch(tc.name, ctx, tc.arguments)
                    for search_result in result.get("results", []) or []:
                        url = search_result.get("url")
                        if url:
                            verified_urls.add(url)
            else:
                result = await dispatch(tc.name, ctx, tc.arguments)

            records.append(
                {
                    "id": str(uuid.uuid4()),
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": json.dumps(result, ensure_ascii=False),
                    "created_at": _now_iso(),
                }
            )

        if suggest_calls:
            break
    else:
        records.append(
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": "Не удалось завершить ответ за отведённое число шагов — попробуй переформулировать запрос.",
                "created_at": _now_iso(),
            }
        )

    # Модель не всегда помнит предложить более глубокий поиск сама (иногда
    # просто пишет вопрос текстом вместо вызова suggest_replies) — не
    # полагаемся только на промпт, гарантируем чип кодом, если в этом ходе
    # был хотя бы один web_search и ни один не был depth=advanced.
    if used_web_search and not used_advanced_web_search and records and records[-1]["role"] == "assistant":
        chip = "Поискать глубже"
        existing = records[-1].get("suggested_replies") or []
        if chip not in existing:
            records[-1]["suggested_replies"] = [*existing, chip]

    item.properties = {**item.properties, "messages": records}
    item.content = _flatten_transcript(records)
    await db.commit()
    await db.refresh(item)
    return _serialize(item)
