"""Smart notes: keyword auto-tags plus full-text-ish search."""

from __future__ import annotations

import re
from datetime import datetime
from typing import cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_STORE = "smart_notes.db"
_MAX_TAGS = 5

STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "have", "has",
        "had", "were", "was", "are", "but", "not", "you", "your", "our",
        "their", "they", "them", "then", "than", "when", "where", "which",
        "who", "whom", "will", "would", "could", "should", "about", "into",
        "over", "after", "before", "between", "under", "again", "once",
        "here", "there", "what", "all", "any", "can", "her", "him", "his",
        "its", "may", "more", "most", "other", "some", "such", "only",
        "own", "same", "too", "very", "just", "also", "per",
    }
)


def auto_tags(text: str, max_tags: int = _MAX_TAGS) -> list[str]:
    """Top keywords by frequency (stopwords removed), at most ``max_tags``."""
    counts: dict[str, int] = {}
    for word in re.findall(r"[a-z]+", text.lower()):
        if len(word) >= 3 and word not in STOPWORDS:
            counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:max_tags]]


class SmartNotesSkill(Skill):
    """Notes with automatic keyword tags and substring search."""

    name = "smart_notes"
    description = (
        "Smart notes: 'save <text>' stores a note with auto-generated keyword "
        "tags (top 5 by frequency, stopwords removed), 'search <query>' finds "
        "matching notes."
    )
    intents = ("note.save", "note.search")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("save "):
            return self._save(context, text[5:].strip())
        if lowered.startswith("search "):
            return self._search(context, text[7:].strip())
        return "notes: 'save <text>' | 'search <query>'"

    def _save(self, context: SkillContext, text: str) -> str:
        if not text:
            return "save failed: note text is empty"
        tags = auto_tags(text)
        store = SQLiteDocumentStore(require_data_dir(context) / _STORE)
        note_id = store.add(
            {
                "text": text,
                "tags": tags,
                "created": datetime.now().astimezone().isoformat(),
            }
        )
        tag_str = ", ".join(tags) if tags else "none"
        return f"note saved ({note_id[:8]}) — tags: {tag_str}"

    def _search(self, context: SkillContext, query: str) -> str:
        if not query:
            return "search usage: 'search <query>'"
        store = SQLiteDocumentStore(require_data_dir(context) / _STORE)
        hits = store.search(query, limit=10)
        if not hits:
            return f"no notes match '{query}'"
        lines = [f"notes matching '{query}':"]
        for hit in hits:
            data = cast(dict[str, object], hit)
            text = str(data.get("text", ""))
            tags = data.get("tags")
            tag_str = ", ".join(str(t) for t in tags) if isinstance(tags, list) else ""
            snippet = text if len(text) <= 140 else text[:137] + "..."
            lines.append(f"  {str(data.get('id', ''))[:8]}: {snippet} [tags: {tag_str}]")
        return "\n".join(lines)


SKILLS: list[Skill] = [SmartNotesSkill()]
