"""INZO tool system: base types (Rule 6, Rule 11, Rule 12, Rule 13).

Tools are the only way the agent touches the outside world. There is
deliberately NO shell/command tool: Rule 12 forbids executing arbitrary
shell commands from natural-language input, so no such tool exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: str  # "string" | "number" | "boolean" | "object"
    description: str
    required: bool = True


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    error: str | None = None


class Tool(ABC):
    """Base class for all tools. Subclass and implement ``run``."""

    name: str = "unnamed"
    description: str = ""
    parameters: tuple[ToolParameter, ...] = ()
    required_capabilities: tuple[str, ...] = ("tools.execute",)

    def validate_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Check required params are present; return a cleaned copy."""
        missing = [
            p.name for p in self.parameters if p.required and p.name not in args
        ]
        if missing:
            raise ValueError(f"missing required args: {', '.join(missing)}")
        allowed = {p.name for p in self.parameters}
        return {k: v for k, v in args.items() if k in allowed}

    @abstractmethod
    async def run(self, args: dict[str, Any]) -> ToolResult:
        """Execute the tool with validated args."""
        ...


@dataclass(frozen=True)
class ToolDefinition:
    """Serializable view of a tool for the API."""

    name: str
    description: str
    parameters: tuple[ToolParameter, ...] = field(default_factory=tuple)
    required_capabilities: tuple[str, ...] = field(default_factory=tuple)
