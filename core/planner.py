"""Task planner: turns a detected intent into an ordered, verifiable plan.

The planner is deterministic and local (Rule 15). It never invents tool
names: every step references a tool that must exist in the ToolRegistry,
and every capability it names must be grantable by the PermissionManager.
"""

from __future__ import annotations

from app.logging_config import get_logger
from core.protocols import Plan, PlanStep
from intelligence.nlp.pipeline import extract_expression

logger = get_logger(__name__)


class Planner:
    """Rule-based planner mapping intents to tool-backed plans."""

    def plan(self, intent: str, message: str) -> Plan:
        """Build a plan for ``intent`` derived from ``message``."""
        steps: list[PlanStep] = []
        reasoning: str

        if intent == "calculate":
            expression = extract_expression(message) or message.strip()
            steps.append(
                PlanStep(
                    id="calc-1",
                    description=f"Evaluate arithmetic expression: {expression}",
                    tool_name="calculator",
                    args={"expression": expression},
                    requires_capability="tool.calculator",
                )
            )
            reasoning = "Arithmetic intent -> deterministic calculator tool."
        elif intent == "get_time":
            steps.append(
                PlanStep(
                    id="time-1",
                    description="Read the current local time.",
                    tool_name="current_time",
                    args={},
                    requires_capability="tool.time",
                )
            )
            reasoning = "Time intent -> current_time tool."
        elif intent == "save_note":
            steps.append(
                PlanStep(
                    id="note-1",
                    description="Persist the user's note to memory.",
                    tool_name="save_note",
                    args={"text": message.strip()},
                    requires_capability="tool.note",
                )
            )
            reasoning = "Note intent -> save_note tool."
        elif intent == "recall_memory":
            steps.append(
                PlanStep(
                    id="recall-1",
                    description="Recall relevant memories for the query.",
                    tool_name=None,
                    args={"query": message.strip()},
                    requires_capability=None,
                )
            )
            reasoning = "Recall intent -> memory retrieval (no tool needed)."
        elif intent == "finance":
            steps.append(
                PlanStep(
                    id="fin-1",
                    description="Run deterministic finance calculation.",
                    tool_name="finance_calc",
                    args={"request": message.strip()},
                    requires_capability="tool.finance",
                )
            )
            reasoning = "Finance intent -> deterministic finance engine (Python computes)."
        else:
            reasoning = "General chat intent -> direct model response, no tools."

        plan = Plan(intent=intent, steps=tuple(steps), reasoning=reasoning)
        logger.info(
            "plan built",
            extra={"intent": intent, "steps": len(plan.steps)},
        )
        return plan
