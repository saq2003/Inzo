"""Shared protocols and value types for the INZO agent core (Rule 6).

Adapters implement these protocols so providers stay replaceable (Rule 3)
and are never hard-coded (Rule 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    """Result of one model generation call."""

    text: str
    model: str
    latency_s: float = 0.0
    tokens_used: int | None = None


class LLMAdapter(Protocol):
    """Interface every language-model backend must implement."""

    name: str

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        timeout_s: float = 30.0,
    ) -> LLMResponse:
        """Generate a completion. Must honor ``timeout_s`` (Rule 9)."""
        ...


@dataclass(frozen=True)
class PlanStep:
    """One step of an execution plan."""

    id: str
    description: str
    tool_name: str | None = None
    args: dict[str, object] = field(default_factory=dict)
    requires_capability: str | None = None


@dataclass(frozen=True)
class Plan:
    """An ordered, verifiable plan for handling a user intent."""

    intent: str
    steps: tuple[PlanStep, ...]
    reasoning: str


@dataclass(frozen=True)
class AgentResult:
    """Everything the agent did for one user message."""

    reply: str
    intent: str
    plan: Plan
    tool_outputs: tuple[str, ...]
    verified: bool
    issues: tuple[str, ...]
