"""Tool registry: registration + permission-checked, timeout-bound execution.

Execution order per call: capability checks (Rule 13) -> arg validation
(Rule 11) -> run with timeout (Rule 9). Failures are returned as
ToolResult / raised as typed errors, never as raw tracebacks to users.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.logging_config import get_logger
from security.permissions import PermissionManager
from tools.base import Tool, ToolDefinition, ToolResult

logger = get_logger(__name__)


class UnknownToolError(KeyError):
    """Raised when a tool name is not registered."""


class ToolRegistry:
    """Holds tool implementations and executes them safely."""

    def __init__(self, permissions: PermissionManager) -> None:
        self._tools: dict[str, Tool] = {}
        self._permissions = permissions

    def register(self, tool: Tool) -> None:
        """Register a tool instance under its ``name``."""
        if not tool.name or tool.name in self._tools:
            raise ValueError(f"invalid or duplicate tool name: {tool.name!r}")
        self._tools[tool.name] = tool
        logger.info("tool registered", extra={"tool": tool.name})

    def get(self, name: str) -> Tool:
        """Return the tool, or raise UnknownToolError."""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"unknown tool: {name}") from exc

    def definitions(self) -> list[ToolDefinition]:
        """Serializable tool catalog for the API."""
        return [
            ToolDefinition(
                name=t.name,
                description=t.description,
                parameters=t.parameters,
                required_capabilities=t.required_capabilities,
            )
            for t in self._tools.values()
        ]

    def names(self) -> list[str]:
        """Registered tool names."""
        return sorted(self._tools)

    async def execute(
        self,
        name: str,
        *,
        actor: str,
        args: dict[str, Any] | None = None,
        timeout_s: float = 10.0,
    ) -> ToolResult:
        """Permission-check, validate, and run a tool with a timeout."""
        tool = self.get(name)
        # Rule 13: every required capability checked BEFORE execution.
        for capability in tool.required_capabilities:
            self._permissions.require(actor, capability)
        cleaned = tool.validate_args(dict(args or {}))
        logger.info("tool execute", extra={"tool": name, "actor": actor})
        try:
            result = await asyncio.wait_for(tool.run(cleaned), timeout=timeout_s)
        except TimeoutError as exc:
            raise TimeoutError(f"tool '{name}' timed out after {timeout_s}s") from exc
        if not result.ok:
            logger.warning("tool failed", extra={"tool": name, "error": result.error})
        return result
