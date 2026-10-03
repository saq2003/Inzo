"""Diet log skill (fully local, deterministic).

Logs meals as ``{name, kcal, protein_g}`` to ``data_dir/"health.db"`` and
reports today's totals against a configurable kcal target (default 2200).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore, SQLiteKVStore

TARGET_KEY = "diet:target_kcal"
DEFAULT_TARGET_KCAL = 2200.0


def _is_number(value: str) -> bool:
    """True when the token parses as a float."""
    try:
        float(value)
        return True
    except ValueError:
        return False


class DietLogSkill(Skill):
    """Logs meals and tracks daily totals vs a kcal target."""

    name = "diet_log"
    description = (
        "Logs meals (name, kcal, optional protein) and reports today's "
        "totals against a configurable daily calorie target."
    )
    intents = ("diet.log", "diet.today")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    def _stores(self, context: SkillContext) -> tuple[SQLiteKVStore, SQLiteDocumentStore]:
        path = require_data_dir(context) / "health.db"
        return SQLiteKVStore(path), SQLiteDocumentStore(path)

    def _target(self, context: SkillContext) -> float:
        kv, _ = self._stores(context)
        raw = kv.get(TARGET_KEY)
        if raw is None:
            return DEFAULT_TARGET_KCAL
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError("stored kcal target is corrupt") from exc

    def _today_meals(self, context: SkillContext) -> list[Mapping[str, Any]]:
        _, docs = self._stores(context)
        today = datetime.now(UTC).date().isoformat()
        return [
            d
            for d in docs.search("meal", limit=1000)
            if d.get("kind") == "meal"
            and datetime.fromisoformat(str(d["ts"])).date().isoformat() == today
        ]

    def _report(self, context: SkillContext) -> str:
        meals = self._today_meals(context)
        target = self._target(context)
        kcal = sum(float(m["kcal"]) for m in meals)
        protein = sum(float(m.get("protein_g", 0.0)) for m in meals)
        lines = [f"today: {len(meals)} meal(s)", f"calories: {kcal:.0f} / {target:.0f} kcal"]
        remaining = target - kcal
        if remaining >= 0:
            lines.append(f"remaining: {remaining:.0f} kcal")
        else:
            lines.append(f"over target by {-remaining:.0f} kcal")
        lines.append(f"protein: {protein:.0f} g")
        return "\n".join(lines)

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lower = text.lower()

        if lower in ("today", "report", "summary"):
            return self._report(context)

        if lower.startswith("target"):
            try:
                target = float(lower.split()[1])
            except (IndexError, ValueError) as exc:
                return f"usage: target <kcal> ({exc})"
            if target <= 0:
                return "target must be positive"
            kv, _ = self._stores(context)
            kv.put(TARGET_KEY, json.dumps(target))
            return f"daily calorie target set to {target:.0f} kcal"

        if lower.startswith("log"):
            # "log <name> <kcal> [protein_g]" — numbers are trailing tokens,
            # in the same order as the command words (kcal first).
            tokens = text[3:].strip().split()
            protein_g = 0.0
            name_tokens: list[str]
            if len(tokens) >= 3 and _is_number(tokens[-2]) and _is_number(tokens[-1]):
                kcal = float(tokens[-2])
                protein_g = float(tokens[-1])
                name_tokens = tokens[:-2]
            elif len(tokens) >= 2 and _is_number(tokens[-1]):
                kcal = float(tokens[-1])
                name_tokens = tokens[:-1]
            else:
                return "usage: log <name> <kcal> [protein_g]"
            if kcal <= 0:
                return "kcal must be positive"
            name = " ".join(name_tokens).strip()
            if not name:
                return "usage: log <name> <kcal> [protein_g]"
            _, docs = self._stores(context)
            meal: dict[str, Any] = {
                "kind": "meal",
                "name": name,
                "kcal": kcal,
                "protein_g": protein_g,
                "ts": datetime.now(UTC).isoformat(),
            }
            docs.add(meal)
            return f"logged: {name} ({kcal:.0f} kcal, {protein_g:.0f} g protein)"

        return "diet: 'log <name> <kcal> [protein_g]', 'today', 'target <kcal>'"


SKILLS: list[Skill] = [DietLogSkill()]
