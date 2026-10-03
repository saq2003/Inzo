"""Reasoning trace: an auditable record of how the agent reached its answer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class TraceStep:
    label: str
    detail: str
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ReasoningTrace:
    """Append-only trace of agent reasoning (stdlib only)."""

    def __init__(self) -> None:
        self._steps: list[TraceStep] = []

    def add(self, label: str, detail: str) -> None:
        """Append a reasoning step."""
        self._steps.append(TraceStep(label=label, detail=detail))

    def summarize(self) -> str:
        """Render the trace as a human-readable summary."""
        lines = [f"- {s.label}: {s.detail}" for s in self._steps]
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._steps)
