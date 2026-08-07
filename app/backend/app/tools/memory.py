import uuid
from typing import Any

from sqlalchemy import select

from app.llm.base import ToolDefinition
from app.models import AssistantMemory
from app.tools.registry import ToolContext, ToolError

REMEMBER_FACT = ToolDefinition(
    name="remember_fact",
    description=(
        "Запомнить факт о пользователе или его личных обозначениях (например, что конкретное "
        "слово означает конкретную папку) — будет доступно во всех последующих диалогах, не "
        "только в этом. Перед тем как запоминать, проверь через list_memories, что такого факта "
        "ещё нет."
    ),
    parameters={
        "type": "object",
        "properties": {"fact": {"type": "string", "description": "Короткий факт в свободной форме"}},
        "required": ["fact"],
    },
)


async def remember_fact(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    fact = str(args.get("fact", "")).strip()
    if not fact:
        raise ToolError("Пустой факт")
    memory = AssistantMemory(user_id=ctx.user_id, content=fact)
    ctx.db.add(memory)
    await ctx.db.commit()
    await ctx.db.refresh(memory)
    return {"id": str(memory.id), "fact": fact}


LIST_MEMORIES = ToolDefinition(
    name="list_memories",
    description="Посмотреть, что уже запомнено о пользователе — используй перед remember_fact, чтобы не дублировать.",
    parameters={"type": "object", "properties": {}},
)


async def list_memories(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.db.execute(
        select(AssistantMemory).where(AssistantMemory.user_id == ctx.user_id).order_by(AssistantMemory.created_at)
    )
    memories = result.scalars().all()
    return {"memories": [{"id": str(m.id), "fact": m.content} for m in memories]}


FORGET_FACT = ToolDefinition(
    name="forget_fact",
    description="Удалить ранее запомненный факт, если он устарел или неверен.",
    parameters={
        "type": "object",
        "properties": {"memory_id": {"type": "string", "description": "id факта из list_memories"}},
        "required": ["memory_id"],
    },
)


async def forget_fact(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        memory_id = uuid.UUID(str(args.get("memory_id")))
    except (ValueError, TypeError):
        raise ToolError(f"Некорректный id факта: {args.get('memory_id')}") from None

    memory = await ctx.db.get(AssistantMemory, memory_id)
    if memory is None or memory.user_id != ctx.user_id:
        raise ToolError("Факт не найден")
    await ctx.db.delete(memory)
    await ctx.db.commit()
    return {"deleted": True}
