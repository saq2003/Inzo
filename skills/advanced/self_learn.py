"""Self-learning behavioral rules from user corrections.

Unlike preference learning (what the user likes), this skill learns
*behavioral* rules: corrections of the form ``correct: <wrong> ->
<right>``, ``never do X`` (forbidden), and ``always do Y`` (mandatory).
Rules persist as documents in ``data_dir/"learn.db"``. The agent later
loads them and calls :func:`apply_rules` to rewrite its own output.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_STORE_FILE = "learn.db"


def _store(data_dir: Path) -> SQLiteDocumentStore:
    return SQLiteDocumentStore(data_dir / _STORE_FILE)


def _load_rules(data_dir: Path) -> list[Mapping[str, Any]]:
    return _store(data_dir).search("", limit=500)


def apply_rules(text: str, rules: list[Mapping[str, Any]]) -> str:
    """Apply stored behavioral rules to ``text`` (pure, deterministic).

    - ``correction``: literal replacement of ``pattern`` with ``replacement``.
    - ``forbidden``: removes every occurrence of ``pattern``.
    - ``mandatory``: appends ``replacement`` when it is not already present.
    Only ``global``-scoped rules are applied here; skill-scoped rules carry
    their ``scope`` as metadata for the caller to filter on.
    """
    result = text
    for rule in rules:
        if rule.get("scope") != "global":
            continue
        kind = str(rule.get("kind", "correction"))
        pattern = str(rule.get("pattern", ""))
        replacement = str(rule.get("replacement", ""))
        if kind == "correction":
            if pattern:
                result = result.replace(pattern, replacement)
        elif kind == "forbidden":
            if pattern:
                result = re.sub(r"\s+", " ", result.replace(pattern, "")).strip()
        elif kind == "mandatory":
            if replacement and replacement not in result:
                result = result.rstrip() + " " + replacement
    return result


def _parse_correction(message: str) -> Mapping[str, str] | None:
    """Parse 'correct: <wrong> -> <right>' / 'never ...' / 'always ...'."""
    lowered = message.lower().strip()
    if lowered.startswith("correct:"):
        body = message.split(":", 1)[1]
        if "->" not in body:
            return None
        wrong, _, right = body.partition("->")
        wrong, right = wrong.strip(), right.strip()
        if not wrong or not right:
            return None
        return {
            "kind": "correction",
            "pattern": wrong,
            "replacement": right,
            "scope": "global",
        }
    if lowered.startswith("never do "):
        pattern = message[len("never do ") :].strip()
    elif lowered.startswith("never "):
        pattern = message[len("never ") :].strip()
    elif lowered.startswith("don't ") or lowered.startswith("dont "):
        pattern = message.split(" ", 1)[1].strip()
    else:
        pattern = ""
    if pattern:
        return {"kind": "forbidden", "pattern": pattern, "replacement": "", "scope": "global"}
    if lowered.startswith("always do "):
        replacement = message[len("always do ") :].strip()
    elif lowered.startswith("always "):
        replacement = message[len("always ") :].strip()
    else:
        return None
    if not replacement:
        return None
    return {"kind": "mandatory", "pattern": "", "replacement": replacement, "scope": "global"}


class SelfLearnSkill(Skill):
    """Learns and lists behavioral rules from user corrections."""

    name = "self_learn"
    description = (
        "Learns agent behavior rules from corrections: "
        "'correct: <wrong> -> <right>', 'never do X', 'always do Y'; "
        "'rules' lists what was learned."
    )
    intents = ("learn.correct", "learn.rules")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        message = context.message.strip()
        if message.lower() == "rules" or message.lower().startswith("rules"):
            return self._list_rules(data_dir)
        rule = _parse_correction(message)
        if rule is None:
            return (
                "self_learn: say 'correct: <wrong> -> <right>', "
                "'never do <X>', or 'always do <Y>'; 'rules' lists them."
            )
        doc: dict[str, Any] = dict(rule)
        doc["created"] = datetime.now(UTC).isoformat()
        doc["source"] = message
        rule_id = _store(data_dir).add(doc)
        try:
            await context.memory.remember(
                "user",
                f"behavioral rule learned ({doc['kind']}): {message}",
                durable=True,
                kind="rule",
            )
        except Exception as exc:
            _ = exc  # memory is optional in bare contexts; the rule is persisted above
        return f"rule learned [{doc['kind']}] (id={rule_id}): {self._describe(doc)}"

    def _list_rules(self, data_dir: Path) -> str:
        rules = _load_rules(data_dir)
        if not rules:
            return "no behavioral rules learned yet."
        lines = [f"learned behavioral rules ({len(rules)}):"]
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. [{rule.get('kind')}] {self._describe(rule)}")
        return "\n".join(lines)

    @staticmethod
    def _describe(rule: Mapping[str, Any]) -> str:
        kind = str(rule.get("kind", "correction"))
        if kind == "correction":
            return f"'{rule.get('pattern')}' -> '{rule.get('replacement')}'"
        if kind == "forbidden":
            return f"never: '{rule.get('pattern')}'"
        return f"always: '{rule.get('replacement')}'"


SKILLS: list[Skill] = [SelfLearnSkill()]
