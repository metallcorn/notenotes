import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.deps import get_current_user
from app.llm.base import Message
from app.llm.factory import get_llm_client
from app.models import User

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Разовое преобразование фрагмента/всей заметки — обычный chat-комплишн без
# тулов и без истории диалога (не то же самое, что AI-ассистент в
# app/routers/dialogs.py): пользователь работает прямо в редакторе, не
# заводя диалог, и ждёт только текст результата, а не рассуждения модели.
# Общее правило для всех действий: реальная жалоба — при переформатировании
# терялись ссылки (markdown [text](url), в редакторе выглядят подчёркнутыми
# словами, не голым http). Структурная причина уже исправлена на фронтенде
# (NoteEditor.tsx — раньше выделение сериализовалось в чистый текст без
# marks ДО отправки в модель, теперь ссылки доходят до неё). Это —
# дополнительный слой: даже когда ссылка доходит целиком, модель не должна
# сама решить её "причесать" или выкинуть при реорганизации структуры.
_COMMON_SUFFIX = (
    " Никогда не выдумывай новые факты, числа, ссылки или детали, которых не было в исходном "
    "тексте — только переставляй/сокращай/переформулируй то, что реально есть. Если в исходном "
    "тексте есть markdown-ссылки [текст](url) — сохрани их все в результате как есть, с тем же "
    "текстом и тем же url, ничего не переписывай в них и не убирай."
)

_PROMPTS: dict[str, str] = {
    "summarize": (
        "Сократи текст пользователя до краткого содержания, сохраняя ключевые факты. Ответь "
        "ТОЛЬКО результатом в формате Markdown, без вступлений вроде «Вот краткое содержание:» и "
        "без комментариев — то, что ты вернёшь, целиком заменит исходный текст. Язык ответа — "
        "язык исходного текста." + _COMMON_SUFFIX
    ),
    "reformat": (
        "Переформатируй текст пользователя в более структурированный Markdown — заголовки, списки, "
        "таблицы где уместно. Меняется ТОЛЬКО структура/подача, не сами слова: копируй формулировки, "
        "названия, подписи полей и цифры ДОСЛОВНО, как в исходном тексте, включая любые языковые "
        "вставки (например, официальное название учреждения или текст с печати на другом языке, "
        "внутри текста на другом языке) — не переводи и не перефразируй их на язык остального текста "
        "или на какой-либо один язык целиком. Реальный случай: исходный текст был на русском с "
        "польскими названиями/надписями внутри — модель «причесала» это и перевела всё целиком на "
        "польский, хотя нужно было просто разложить как есть в таблицы/списки, сохранив каждую "
        "формулировку на том языке, на котором она была. Ответь ТОЛЬКО результатом, без вступлений и "
        "комментариев — то, что ты вернёшь, целиком заменит исходный текст." + _COMMON_SUFFIX
    ),
}


# Модели систематически оборачивают ответ в ```markdown … ``` целиком,
# несмотря на явный запрет во всех промптах ("ответь ТОЛЬКО результатом") —
# проверено вживую. Результат вставляется прямо в редактор заметки, поэтому
# такая обёртка превратилась бы в буквальный блок кода в заметке, а не в
# форматированный текст. Снимаем обёртку кодом, а не полагаемся на промпт.
_WRAPPED_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n(.*)\n```$", re.DOTALL)


def _strip_wrapping_fence(text: str) -> str:
    match = _WRAPPED_FENCE_RE.match(text.strip())
    return match.group(1) if match else text


class TransformIn(BaseModel):
    action: Literal["summarize", "reformat", "rewrite"]
    text: str = Field(min_length=1, max_length=20000)
    instruction: str = Field(default="", max_length=500)


@router.post("/transform")
async def transform_text(payload: TransformIn, user: User = Depends(get_current_user)) -> dict:
    settings = get_settings()
    if not settings.llm_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Ассистент ещё не настроен")

    if payload.action == "rewrite":
        instruction = payload.instruction.strip()
        if not instruction:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Укажи, как переписать текст")
        system_prompt = (
            f"Перепиши текст пользователя: {instruction}. Смысл и факты сохраняются, меняется "
            "стиль/формулировка. Ответь ТОЛЬКО результатом в формате Markdown, без вступлений и "
            "комментариев — то, что ты вернёшь, целиком заменит исходный текст. Язык ответа — язык "
            "исходного текста." + _COMMON_SUFFIX
        )
    else:
        system_prompt = _PROMPTS[payload.action]

    client = get_llm_client()
    try:
        response = await client.chat(
            [Message(role="system", content=system_prompt), Message(role="user", content=payload.text)], []
        )
    except Exception:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Не получилось обратиться к LLM-провайдеру") from None

    return {"result": _strip_wrapping_fence(response.message.content)}
