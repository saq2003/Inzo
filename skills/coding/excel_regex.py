"""Regex builder/tester + Excel formula generator (fully local).

* ``regex <description>`` — picks a pattern from a curated library
  (email, phone, numbers, dates, URL, IPv4, hex color, ...) by keyword
  matching and explains it.
* ``test <pattern-or-key> <text>`` — compiles the pattern (library key or
  raw regex) and reports match/no-match with groups.
* ``formula <kind> <key=value ...>`` — generates VLOOKUP, XLOOKUP,
  SUMIFS, INDEX/MATCH, and IFERROR formulas from parameters.
"""

from __future__ import annotations

import re
import shlex

from skills.base import Skill, SkillContext

PATTERNS: dict[str, tuple[str, str]] = {
    "email": (
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "email address",
    ),
    "phone": (
        r"\+?\d[\d\s\-().]{7,}\d",
        "international phone number (loose)",
    ),
    "int": (r"-?\d+", "integer"),
    "decimal": (r"-?\d+(?:\.\d+)?", "decimal number"),
    "number": (r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", "number incl. scientific notation"),
    "date_iso": (r"\d{4}-\d{2}-\d{2}", "date YYYY-MM-DD"),
    "date_dmy": (r"\d{2}/\d{2}/\d{4}", "date DD/MM/YYYY"),
    "time": (r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", "time HH:MM[:SS] 24h"),
    "url": (r"https?://[^\s/$.?#].[^\s]*", "http/https URL"),
    "ipv4": (r"(?:\d{1,3}\.){3}\d{1,3}", "IPv4 address (format only)"),
    "hexcolor": (r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", "hex color #rgb/#rrggbb"),
    "zip_us": (r"\d{5}(?:-\d{4})?", "US ZIP code"),
    "word": (r"[A-Za-z]+", "single word (letters)"),
}

_KEYWORDS: dict[str, list[str]] = {
    "email": ["email", "e-mail", "mail"],
    "phone": ["phone", "mobile", "tel", "contact"],
    "int": ["integer", "whole number"],
    "decimal": ["decimal", "float"],
    "number": ["number", "numeric", "amount"],
    "date_iso": ["iso date", "yyyy-mm-dd"],
    "date_dmy": ["date", "dmy", "dd/mm"],
    "time": ["time", "clock", "hh:mm"],
    "url": ["url", "link", "website"],
    "ipv4": ["ip", "ipv4", "address"],
    "hexcolor": ["color", "colour", "hex"],
    "zip_us": ["zip", "postal", "pincode"],
    "word": ["word", "letters"],
}


def find_pattern(description: str) -> tuple[str, str, str]:
    """Return (key, pattern, explanation) best matching ``description``."""
    lowered = description.lower()
    best: tuple[str, str, str] | None = None
    best_score = 0
    for key, keywords in _KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lowered)
        if score > best_score:
            pattern, explanation = PATTERNS[key]
            best = (key, pattern, explanation)
            best_score = score
    if best is None:
        raise ValueError(
            f"no pattern matches {description!r}; known: {', '.join(sorted(PATTERNS))}"
        )
    return best


def test_pattern(pattern: str, text: str) -> str:
    """Test ``pattern`` against ``text``; report match details."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"invalid regex: {exc}"
    match = compiled.search(text)
    if not match:
        return f"no match for /{pattern}/ in {text!r}"
    groups = ", ".join(repr(g) for g in match.groups()) or "(no groups)"
    return f"match: {match.group()!r} at {match.start()}-{match.end()}; groups: {groups}"


def _params(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in shlex.split(text):
        if "=" in token:
            key, _, value = token.partition("=")
            out[key.strip().lower()] = value.strip()
    return out


def _need(params: dict[str, str], key: str) -> str:
    value = params.get(key, "")
    if not value:
        raise ValueError(f"formula needs {key}=<value>")
    return value


def formula_vlookup(params: dict[str, str]) -> str:
    lookup = _need(params, "lookup")
    table = _need(params, "table")
    col = _need(params, "col")
    exact = params.get("exact", "true").lower() not in ("false", "0", "no")
    return f"=VLOOKUP({lookup},{table},{col},{'FALSE' if exact else 'TRUE'})"


def formula_xlookup(params: dict[str, str]) -> str:
    lookup = _need(params, "lookup")
    lookup_range = _need(params, "lookup_range")
    return_range = _need(params, "return_range")
    fallback = params.get("if_not_found", "")
    tail = f',"{fallback}"' if fallback else ""
    return f"=XLOOKUP({lookup},{lookup_range},{return_range}{tail})"


def formula_sumifs(params: dict[str, str]) -> str:
    sum_range = _need(params, "sum_range")
    criteria = params.get("criteria", "")
    if not criteria:
        raise ValueError("formula needs criteria=<range1>,<value1>[;<range2>,<value2>]")
    parts = [sum_range]
    for chunk in criteria.split(";"):
        bits = [b.strip() for b in chunk.split(",", 1)]
        if len(bits) != 2:
            raise ValueError(f"bad criteria chunk: {chunk!r}")
        parts.extend(bits)
    return f"=SUMIFS({','.join(parts)})"


def formula_index_match(params: dict[str, str]) -> str:
    lookup = _need(params, "lookup")
    lookup_range = _need(params, "lookup_range")
    return_range = _need(params, "return_range")
    return f"=INDEX({return_range},MATCH({lookup},{lookup_range},0))"


def formula_iferror(params: dict[str, str]) -> str:
    expr = _need(params, "expr")
    fallback = params.get("fallback", '""')
    return f"=IFERROR({expr},{fallback})"


_FORMULAS = {
    "vlookup": (formula_vlookup, "lookup= table= col= [exact=true]"),
    "xlookup": (formula_xlookup, "lookup= lookup_range= return_range= [if_not_found=]"),
    "sumifs": (formula_sumifs, "sum_range= criteria=<range>,<value>[;<range>,<value>]"),
    "indexmatch": (formula_index_match, "lookup= lookup_range= return_range="),
    "iferror": (formula_iferror, "expr= [fallback=]"),
}


class ExcelRegexSkill(Skill):
    """Builds/tests regexes and generates Excel formulas (local)."""

    name = "excel_regex"
    description = (
        "Builds regex patterns from descriptions, tests patterns against "
        "text, and generates Excel formulas (VLOOKUP/XLOOKUP/SUMIFS/"
        "INDEX-MATCH/IFERROR)."
    )
    intents = ("regex.build", "regex.test", "excel.formula")
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("regex"):
            description = text[len("regex") :].strip()
            if not description:
                return f"regex: known patterns: {', '.join(sorted(PATTERNS))}"
            try:
                key, pattern, explanation = find_pattern(description)
            except ValueError as exc:
                return f"regex error: {exc}"
            return f"pattern '{key}' ({explanation}):\n`{pattern}`"
        if lowered.startswith("test"):
            rest = text[len("test") :].strip().split(None, 1)
            if len(rest) != 2:
                return "regex test usage: 'test <pattern-or-key> <text>'"
            raw_pattern, sample = rest
            pattern = PATTERNS[raw_pattern.lower()][0] if raw_pattern.lower() in PATTERNS else raw_pattern
            return test_pattern(pattern, sample)
        if lowered.startswith("formula"):
            rest = text[len("formula") :].strip().split(None, 1)
            if not rest or rest[0].lower() not in _FORMULAS:
                kinds = ", ".join(f"{k} ({hint})" for k, (_, hint) in _FORMULAS.items())
                return f"formula usage: 'formula <kind> <key=value ...>'; kinds: {kinds}"
            builder, _ = _FORMULAS[rest[0].lower()]
            try:
                return f"formula:\n`{builder(_params(rest[1] if len(rest) > 1 else ''))}`"
            except ValueError as exc:
                return f"formula error: {exc}"
        return (
            "excel_regex: try 'regex <description>', 'test <pattern-or-key> <text>', "
            "or 'formula <vlookup|xlookup|sumifs|indexmatch|iferror> <key=value ...>'."
        )


SKILLS: list[Skill] = [ExcelRegexSkill()]
