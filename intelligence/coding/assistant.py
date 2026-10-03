"""Coding assistant: static code help that never executes code (Rule 12).

Explains snippets with heuristics and generates test templates. It does
not run, eval, or shell out to anything derived from user input.
"""

from __future__ import annotations

import ast


class CodingAssistant:
    """Safe static code analysis helpers."""

    def explain(self, code: str) -> str:
        """Describe the structure of a Python snippet (no execution)."""
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return f"syntax error: {exc}"
        kinds: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kinds["functions"] = kinds.get("functions", 0) + 1
            elif isinstance(node, ast.ClassDef):
                kinds["classes"] = kinds.get("classes", 0) + 1
            elif isinstance(node, ast.Import | ast.ImportFrom):
                kinds["imports"] = kinds.get("imports", 0) + 1
        if not kinds:
            return "snippet parsed: no functions, classes, or imports found"
        parts = [f"{count} {name}" for name, count in sorted(kinds.items())]
        return "snippet defines: " + ", ".join(parts)

    def make_test_template(self, func_name: str) -> str:
        """Generate a pytest test template for ``func_name`` (no execution)."""
        safe = "".join(c if c.isalnum() or c == "_" else "_" for c in func_name)
        return (
            f"def test_{safe}():\n"
            f'    """Test {safe}."""\n'
            f"    # TODO: arrange / act / assert\n"
            f"    assert callable({safe})\n"
        )
