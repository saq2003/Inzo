"""Local NLP helpers (stdlib only, Rule 1): tokenize, intent, expressions."""

from __future__ import annotations

import ast
import re
from decimal import Decimal, InvalidOperation

_TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")
# Runs of characters that can appear in an arithmetic expression.
_EXPR_CANDIDATE_RE = re.compile(r"[0-9+\-*/%().\s^]+")


def tokenize(text: str) -> list[str]:
    """Split text into lowercase word tokens."""
    return _TOKEN_RE.findall(text.lower())


def detect_intent(text: str) -> str:
    """Rule-based local intent detection.

    Returns one of: ``calculate``, ``get_time``, ``save_note``,
    ``recall_memory``, ``finance``, ``chat``.
    """
    lowered = text.lower()
    if any(w in lowered for w in ("emi", "interest", "budget", "portfolio", "compound", "invest")):
        return "finance"
    if any(w in lowered for w in ("calculate", "compute", "+", "-", "*", "/")) or (
        ("what is" in lowered or "what's" in lowered) and re.search(r"\d", text)
    ):
        if extract_expression(text):
            return "calculate"
    if any(w in lowered for w in ("time is it", "current time", "what time")):
        return "get_time"
    # Recall is checked before save: "do you remember …" is a query, not a note.
    if any(
        w in lowered
        for w in ("recall", "what did i", "do you remember", "my notes", "list my notes")
    ):
        return "recall_memory"
    if any(w in lowered for w in ("remember", "note this", "save note", "take a note")):
        return "save_note"
    return "chat"


def extract_expression(text: str) -> str | None:
    """Extract the longest valid arithmetic expression from ``text``.

    Finds runs of arithmetic characters, trims trailing operators, then
    shrinks from the right until ``safe_eval`` accepts the candidate.
    Returns None when nothing parses as pure arithmetic.
    """
    best: str | None = None
    for match in _EXPR_CANDIDATE_RE.finditer(text):
        candidate = match.group(0).strip().rstrip("+-*/%^")
        while len(candidate) >= 3:
            try:
                safe_eval(candidate)
                break
            except Exception:
                candidate = candidate[:-1].rstrip().rstrip("+-*/%^")
        else:
            continue
        if not re.search(r"\d", candidate):
            continue
        if best is None or len(candidate) > len(best):
            best = candidate
    return best


def extract_numbers(text: str) -> list[Decimal]:
    """Extract all decimal numbers from ``text``."""
    out: list[Decimal] = []
    for match in re.finditer(r"-?\d+(?:\.\d+)?", text):
        try:
            out.append(Decimal(match.group(0)))
        except InvalidOperation:
            continue
    return out


def _is_safe_node(node: ast.AST) -> bool:
    allowed = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
        ast.USub, ast.UAdd, ast.Load,
    )
    return isinstance(node, allowed)


def safe_eval(expression: str) -> Decimal:
    """Safely evaluate an arithmetic expression (no builtins, no names).

    Raises ValueError on anything that is not pure arithmetic.
    """
    try:
        tree = ast.parse(expression.replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {exc}") from exc
    for node in ast.walk(tree):
        if not _is_safe_node(node):
            raise ValueError(f"unsupported expression element: {type(node).__name__}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError("only numeric constants are allowed")
    try:
        # S307 justified: AST whitelist above guarantees pure arithmetic —
        # no names, no attribute access, no calls. __builtins__ is empty.
        result = eval(compile(tree, "<inzo-expr>", "eval"), {"__builtins__": {}}, {})  # noqa: S307
    except ZeroDivisionError as exc:
        raise ValueError("division by zero") from exc
    except ArithmeticError as exc:
        raise ValueError(f"arithmetic error: {exc}") from exc
    return Decimal(str(result))
