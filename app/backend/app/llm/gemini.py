from __future__ import annotations

import httpx

from app.llm.base import LLMResponse, Message, ToolCall, ToolDefinition

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiClient:
    """LLMClient поверх Google Gemini generateContent API. Протокол заметно
    отличается от OpenAI-совместимого (Mistral): нет role="system" в
    contents (отдельное поле systemInstruction), нет role="tool" (function-
    ответы идут как role="function"), id вызова не участвует в протоколе
    вовсе — сопоставление по имени функции и порядку, не по tool_call_id
    (в отличие от Mistral, где _to_llm_messages в dialogs.py явно этого
    требует — здесь просто игнорируем id при сборке wire-формата)."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def _to_wire(self, messages: list[Message]) -> tuple[dict | None, list[dict]]:
        system_parts: list[str] = []
        contents: list[dict] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            if m.role == "user":
                contents.append({"role": "user", "parts": [{"text": m.content}]})
            elif m.role == "assistant":
                if m.tool_calls:
                    parts = []
                    for tc in m.tool_calls:
                        part: dict = {"functionCall": {"name": tc.name, "args": tc.arguments}}
                        signature = tc.metadata.get("thought_signature")
                        if signature:
                            part["thoughtSignature"] = signature
                        parts.append(part)
                    contents.append({"role": "model", "parts": parts})
                else:
                    contents.append({"role": "model", "parts": [{"text": m.content}]})
            elif m.role == "tool":
                contents.append(
                    {
                        "role": "function",
                        "parts": [{"functionResponse": {"name": m.name, "response": {"result": m.content}}}],
                    }
                )
        system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
        return system_instruction, contents

    def _from_wire(self, candidate: dict) -> Message:
        parts = candidate.get("content", {}).get("parts", [])
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for i, part in enumerate(parts):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                # У Gemini нет id вызова в протоколе — генерируем свой для
                # внутреннего представления (ToolCall.id используется только
                # внутри нашего кода для сопоставления с результатом в этом
                # же ходу, наружу в Gemini не уходит). thoughtSignature —
                # наоборот, обязана уйти обратно нетронутой на следующем
                # ходу (см. metadata в base.py) — Gemini 3.x требует её,
                # иначе 400 INVALID_ARGUMENT.
                metadata = {}
                if part.get("thoughtSignature"):
                    metadata["thought_signature"] = part["thoughtSignature"]
                tool_calls.append(
                    ToolCall(id=f"gemini-{i}", name=fc["name"], arguments=fc.get("args") or {}, metadata=metadata)
                )
        return Message(role="assistant", content="".join(text_parts), tool_calls=tool_calls)

    async def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse:
        system_instruction, contents = self._to_wire(messages)
        payload: dict = {"contents": contents}
        if system_instruction:
            payload["system_instruction"] = system_instruction
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools
                    ]
                }
            ]

        url = GEMINI_API_URL.format(model=self._model)
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, params={"key": self._api_key}, json=payload)
            resp.raise_for_status()
            data = resp.json()

        candidate = data["candidates"][0]
        return LLMResponse(message=self._from_wire(candidate), finish_reason=candidate.get("finishReason", ""))
