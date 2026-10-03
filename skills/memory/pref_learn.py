"""Preference learning skill: learns corrections from natural phrasing.

Real (deterministic, stdlib): correction patterns such as "no, I meant X",
"actually prefer Y", and "galat, sahi hai Z" are parsed into (key, value)
pairs stored in a SQLite KV store; :func:`get_preference` reads them back.
"""

from __future__ import annotations

import json
import re
from typing import cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_DB_NAME = "prefs.db"

#: (regex, key) — the first capture group becomes the value.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bno[,.]?\s+i\s+meant\s+(.+)", re.IGNORECASE), "correction"),
    (re.compile(r"\bactually\s+prefer\s+(.+)", re.IGNORECASE), "preference"),
    (re.compile(r"\bgalat[,.]?\s+sahi\s+hai\s+(.+)", re.IGNORECASE), "correction"),
    (re.compile(r"\bi\s+prefer\s+(.+?)\s+over\s+.+", re.IGNORECASE), "preference"),
)

_STRIP_TRAILING = re.compile(r"[.!?]+$")


def parse_correction(text: str) -> tuple[str, str] | None:
    """Parse a correction utterance into (key, value); None when no pattern fits."""
    cleaned = text.strip()
    for pattern, key in _PATTERNS:
        match = pattern.search(cleaned)
        if match:
            value = _STRIP_TRAILING.sub("", match.group(1).strip())
            if value:
                return key, value
    return None


def learn_correction(store: SQLiteKVStore, key: str, value: str) -> None:
    """Persist a learned preference as JSON ``{"key","value"}`` under ``key``."""
    store.put(f"pref:{key}", json.dumps({"key": key, "value": value}))


def get_preference(store: SQLiteKVStore, key: str) -> str | None:
    """Return the learned value for ``key``, or None when unknown."""
    raw = store.get(f"pref:{key}")
    if raw is None:
        return None
    data: dict[str, str] = cast("dict[str, str]", json.loads(raw))
    return data.get("value")


class PrefLearnSkill(Skill):
    """Learns user preferences from correction phrasing."""

    name = "pref_learn"
    description = "Learns preferences from corrections like 'no, I meant X'."
    intents = ("pref.correct",)
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        """Parse the message for a correction pattern and store it."""
        data_dir = require_data_dir(context)
        store = SQLiteKVStore(data_dir / _DB_NAME)
        parsed = parse_correction(context.message)
        if parsed is None:
            return (
                "pref: no correction pattern found — try 'no, I meant X', "
                "'actually prefer Y', or 'galat, sahi hai Z'"
            )
        key, value = parsed
        learn_correction(store, key, value)
        return f"pref: learned {key} = '{value}'"


SKILLS: list[Skill] = [PrefLearnSkill()]
