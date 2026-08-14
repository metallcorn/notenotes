from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    # Провайдер-специфичные данные, которые нужно хранить непрозрачно и
    # вернуть провайдеру как есть на следующем ходу — например, у Gemini
    # 3.x каждый functionCall обязан нести thoughtSignature обратно, иначе
    # 400 INVALID_ARGUMENT ("missing thought_signature"). Mistral это поле
    # просто никогда не заполняет.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """Одна реплика в провайдер-независимом формате. Конкретный клиент
    (MistralClient и будущие Gemini/OpenAI/Claude) переводит её в свой
    протокольный формат и обратно — это единственное, что должно измениться
    при смене провайдера (пользователь явно попросил заменяемость на случай,
    если Mistral не справится)."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # для role="tool" — какой вызов это результат
    name: str | None = None  # для role="tool" — имя вызванной функции


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema параметров функции


@dataclass
class LLMResponse:
    message: Message
    finish_reason: str


class LLMClient(Protocol):
    async def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse: ...


class EmptyLLMResponseError(Exception):
    """Провайдер ответил 200, но без текста и без tool_calls — реальный
    случай, пойманный на Gemini под давлением free-tier квоты: вместо
    честной 429 иногда прилетает пустой candidate с finishReason=STOP.
    Раньше это тихо превращалось в пустой пузырь в чате — теперь клиент
    поднимает эту ошибку явно, чтобы routers/dialogs.py показал тот же
    честный "попробуй ещё раз", что и для сетевых сбоев, вместо тишины."""
