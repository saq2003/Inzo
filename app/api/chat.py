"""Chat endpoint: runs messages through the agent orchestrator."""

from __future__ import annotations

from fastapi import APIRouter

from app import dependencies
from app.schemas import ChatRequest, ChatResponse, ToolCallRecord
from security.validation import sanitize_text

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle one chat turn via the agent (plan -> execute -> verify)."""
    agent = dependencies.get_agent()
    message = sanitize_text(request.message)
    result = await agent.handle(message, actor=request.actor or "user")
    return ChatResponse(
        reply=result.reply,
        intent=result.intent,
        plan_steps=[f"{s.id}: {s.description}" for s in result.plan.steps],
        tool_calls=[
            ToolCallRecord(
                tool=line.split("]")[0].lstrip("["),
                ok="failed" not in line,
                output=line,
            )
            for line in result.tool_outputs
        ],
        verified=result.verified,
        issues=list(result.issues),
    )
