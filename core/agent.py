"""Agent orchestrator: intent -> plan -> execute -> verify -> respond.

The orchestrator wires the planner, model router, verifier, tool registry,
skill registry, memory, and permission manager. It performs no I/O itself
beyond delegating to those components (Rule 7: async throughout).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.logging_config import get_logger
from core.planner import Planner
from core.protocols import AgentResult, Plan
from core.reasoning import ReasoningTrace
from core.router import ModelRouter
from core.verifier import Verifier
from intelligence.nlp.pipeline import detect_intent
from memory.manager import MemoryManager
from security.permissions import PermissionManager
from skills.registry import SkillRegistry
from tools.registry import ToolRegistry

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentConfig:
    """Static agent configuration."""

    actor: str = "inzo-agent"
    system_prompt: str = (
        "You are INZO, a Python-first personal AI assistant. "
        "Be concise, accurate, and never fabricate information."
    )


class Agent:
    """Coordinates one conversational turn end to end."""

    def __init__(
        self,
        *,
        router: ModelRouter,
        planner: Planner,
        verifier: Verifier,
        tools: ToolRegistry,
        skills: SkillRegistry,
        memory: MemoryManager,
        permissions: PermissionManager,
        config: AgentConfig | None = None,
    ) -> None:
        self.router = router
        self.planner = planner
        self.verifier = verifier
        self.tools = tools
        self.skills = skills
        self.memory = memory
        self.permissions = permissions
        self.config = config or AgentConfig()

    async def handle(self, message: str, *, actor: str = "user") -> AgentResult:
        """Handle one user message and return the full agent result."""
        trace = ReasoningTrace()
        trace.add("input", f"actor={actor} message={message[:120]!r}")

        intent = detect_intent(message)
        trace.add("intent", intent)

        plan: Plan = self.planner.plan(intent, message)
        trace.add("plan", plan.reasoning + f" ({len(plan.steps)} steps)")

        tool_outputs: list[str] = []
        for step in plan.steps:
            if step.tool_name is None:
                # Memory recall handled directly (no tool round-trip needed).
                hits = await self.memory.recall(str(step.args.get("query", "")), limit=3)
                summary = "; ".join(h.text for h in hits) or "no relevant memories"
                tool_outputs.append(f"[memory] {summary}")
                trace.add("recall", summary[:120])
                continue
            try:
                result = await self.tools.execute(
                    step.tool_name, actor=actor, args=dict(step.args)
                )
                line = f"[{step.tool_name}] {result.output if result.ok else result.error}"
            except Exception as exc:  # permission / validation / timeout -> user-safe
                line = f"[{step.tool_name}] failed: {exc}"
            tool_outputs.append(line)
            trace.add("tool", line[:160])

        # Skill augmentation: a matching enabled skill may add context.
        skill = self.skills.match(intent)
        if skill is not None:
            trace.add("skill", f"matched skill: {skill.name}")

        adapter = self.router.route("chat")
        prompt = (
            f"USER ({actor}): {message}\n"
            f"INTENT: {intent}\n"
            f"TOOL RESULTS:\n" + "\n".join(tool_outputs)
        )
        response = await adapter.generate(
            prompt, system=self.config.system_prompt, timeout_s=30.0
        )
        trace.add("generate", f"adapter={adapter.name}")

        reply_parts = [response.text]
        for line in tool_outputs:
            reply_parts.append(line)
        reply = "\n".join(reply_parts)

        verification = self.verifier.verify(reply)
        trace.add("verify", f"ok={verification.ok} issues={len(verification.issues)}")

        await self.memory.remember("user", message)
        await self.memory.remember("assistant", reply[:500])

        logger.info(
            "agent turn complete",
            extra={"actor": actor, "intent": intent, "verified": verification.ok},
        )
        return AgentResult(
            reply=reply,
            intent=intent,
            plan=plan,
            tool_outputs=tuple(tool_outputs),
            verified=verification.ok,
            issues=verification.issues,
        )
