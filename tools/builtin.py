"""Built-in tools: deterministic, local, capability-gated.

Deliberately absent: any shell/command/subprocess tool (Rule 12).
Each tool declares the capabilities it needs; the registry enforces them.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from intelligence.finance.calculations import compound_growth, format_money, loan_emi
from intelligence.nlp.pipeline import extract_expression, extract_numbers, safe_eval
from security.validation import sanitize_text
from tools.base import Tool, ToolParameter, ToolResult


class CalculatorTool(Tool):
    """Deterministic arithmetic via safe AST evaluation (no eval of code)."""

    name = "calculator"
    description = "Evaluate a pure arithmetic expression, e.g. '(2+3)*4'."
    parameters = (
        ToolParameter("expression", "string", "Arithmetic expression to evaluate."),
    )
    required_capabilities = ("tools.execute", "tool.calculator")

    async def run(self, args: dict[str, Any]) -> ToolResult:
        raw = sanitize_text(str(args["expression"]), 500)
        expression = extract_expression(raw) or raw
        try:
            value = safe_eval(expression)
        except ValueError as exc:
            return ToolResult(ok=False, output="", error=str(exc))
        return ToolResult(ok=True, output=f"{expression.strip()} = {value}")


class CurrentTimeTool(Tool):
    name = "current_time"
    description = "Return the current local date and time (ISO 8601)."
    parameters = ()
    required_capabilities = ("tools.execute", "tool.time")

    async def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, output=datetime.now().astimezone().isoformat())


class SaveNoteTool(Tool):
    """Persist a note via an injected callable (keeps tools decoupled)."""

    name = "save_note"
    description = "Save a short note to long-term memory."
    parameters = (
        ToolParameter("text", "string", "Note text to save."),
    )
    required_capabilities = ("tools.execute", "tool.note")

    def __init__(self, saver: Any = None) -> None:
        # ``saver``: async callable (text) -> id. Injected by wiring.
        self._saver = saver

    async def run(self, args: dict[str, Any]) -> ToolResult:
        text = sanitize_text(str(args["text"]), 2000)
        if not text:
            return ToolResult(ok=False, output="", error="empty note")
        if self._saver is None:
            return ToolResult(ok=False, output="", error="note storage not wired")
        note_id = await self._saver(text)
        return ToolResult(ok=True, output=f"note saved (id={note_id})")


class ReadFileTool(Tool):
    """Read a text file, sandboxed under an allowed root directory."""

    name = "read_file"
    description = "Read a UTF-8 text file under the allowed root."
    parameters = (
        ToolParameter("path", "string", "Relative path under the allowed root."),
        ToolParameter("max_chars", "number", "Max characters to read.", required=False),
    )
    required_capabilities = ("tools.execute", "tool.read_file")

    def __init__(self, root: str | Path = ".") -> None:
        self._root = Path(root).resolve()

    async def run(self, args: dict[str, Any]) -> ToolResult:
        rel = str(args["path"])
        max_chars = int(args.get("max_chars", 8000))
        target = (self._root / rel).resolve()
        # Sandbox: refuse anything escaping the root (incl. symlinks).
        if self._root not in target.parents and target != self._root:
            return ToolResult(ok=False, output="", error="path escapes allowed root")
        if not target.is_file():
            return ToolResult(ok=False, output="", error="not a file")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult(ok=False, output="", error=f"unreadable: {exc}")
        return ToolResult(ok=True, output=text[:max_chars])


class FinanceCalcTool(Tool):
    """Deterministic finance calculations (Python computes, LLM explains)."""

    name = "finance_calc"
    description = (
        "Run a finance calculation. request like "
        "'compound principal=10000 rate=8 years=5' or 'emi principal=500000 rate=9 months=60'."
    )
    parameters = (
        ToolParameter("request", "string", "Calculation request text."),
    )
    required_capabilities = ("tools.execute", "tool.finance")

    async def run(self, args: dict[str, Any]) -> ToolResult:
        request = sanitize_text(str(args["request"]), 500).lower()
        numbers = extract_numbers(request)
        try:
            if request.startswith("compound") and len(numbers) >= 3:
                result = compound_growth(numbers[0], numbers[1], numbers[2])
                return ToolResult(ok=True, output=f"future value = {format_money(result)}")
            if request.startswith("emi") and len(numbers) >= 3:
                result = loan_emi(numbers[0], numbers[1], int(numbers[2]))
                return ToolResult(ok=True, output=f"monthly EMI = {format_money(result)}")
        except ValueError as exc:
            return ToolResult(ok=False, output="", error=str(exc))
        return ToolResult(
            ok=False,
            output="",
            error="unsupported finance request; try 'compound principal=… rate=… years=…' or 'emi …'",
        )


def builtin_tools(root: str | Path = ".", note_saver: Any = None) -> list[Tool]:
    """Return the default local tool set (no shell tool exists by design)."""
    return [
        CalculatorTool(),
        CurrentTimeTool(),
        SaveNoteTool(saver=note_saver),
        ReadFileTool(root=root),
        FinanceCalcTool(),
    ]
