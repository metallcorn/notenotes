from __future__ import annotations

import json

import httpx

from app.llm.base import LLMResponse, Message, ToolCall, ToolDefinition
from app.llm.retry import post_with_retry, raise_for_status_with_body

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"


class MistralClient:
    """LLMClient поверх Mistral chat completions API — протокол tool-calling
    совместим с форматом OpenAI (id/type/function.arguments как JSON-строка)."""

    def __init__(self, api_key: str, model: str, temperature: float | None = None) -> None:
        self._api_key = api_key
        self._model = model
        # None = не передавать параметр вовсе (дефолт провайдера), а не 0.0:
        # разница существенная, 0.0 — это осознанный детерминизм.
        self._temperature = temperature

    def _to_wire(self, messages: list[Message]) -> list[dict]:
        wire = []
        for m in messages:
            entry: dict = {"role": m.role, "content": m.content}
            if m.role == "assistant" and m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]
            if m.role == "tool":
                entry["tool_call_id"] = m.tool_call_id
                entry["name"] = m.name
            wire.append(entry)
        return wire

    def _from_wire(self, message: dict) -> Message:
        tool_calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            # Тот же случай, что поймали на Groq: для тулов без параметров
            # arguments иногда приходит буквально строкой "null", а не
            # "{}" — json.loads даёт None, обработчики тулов ждут dict.
            if not isinstance(args, dict):
                args = {}
            tool_calls.append(ToolCall(id=tc["id"], name=fn["name"], arguments=args))

        raw_content = message.get("content")
        if isinstance(raw_content, list):
            # Иногда (например, при reasoning-ответах) content приходит не
            # строкой, а массивом частей [{"type": "text", "text": "..."}] —
            # склеиваем текстовые куски вместо падения при сохранении.
            content = "".join(part.get("text", "") for part in raw_content if isinstance(part, dict))
        else:
            content = raw_content or ""

        return Message(role="assistant", content=content, tool_calls=tool_calls)

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        cache_key: str | None = None,
    ) -> LLMResponse:
        payload: dict = {"model": self._model, "messages": self._to_wire(messages)}
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        # Кэш промпта: подсказка провайдеру направить запрос туда, где уже
        # лежит общий префикс. Кэшированные входные токены стоят 10% от
        # обычного тарифа. Работает только если префикс реально совпадает —
        # поэтому всё изменчивое (время) вынесено в КОНЕЦ системного
        # промпта, см. _build_system_prompt в routers/dialogs.py.
        if cache_key:
            payload["prompt_cache_key"] = cache_key
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
            payload["tool_choice"] = "auto"

        # Реальный найденный случай: /ai/transform (reformat) на заметке в
        # 15.5К символов упирался в httpx.ReadTimeout при 60с — модели
        # реально нужно больше времени, когда и вход, и ожидаемый
        # структурированный ответ большие, это не сеть барахлит и не баг,
        # а нормально долгая генерация. 180с — тот же клиент используют и
        # короткие ходы диалога-ассистента (dialogs.py), для них это просто
        # более щедрый потолок, не мешает быстрым ответам.
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await post_with_retry(
                client,
                MISTRAL_API_URL,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            raise_for_status_with_body(resp, "Mistral")
            data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage") or {}
        return LLMResponse(
            message=self._from_wire(choice["message"]),
            finish_reason=choice.get("finish_reason", ""),
            prompt_tokens=usage.get("prompt_tokens", 0) or 0,
            cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0,
            completion_tokens=usage.get("completion_tokens", 0) or 0,
        )
