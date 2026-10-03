"""Background task functions: indexing, memory processing, research.

Each is an async callable returning a short result string, suitable for
submission to a ``TaskQueue``. Heavy work is pushed off the event loop
(Rule 8).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


async def index_documents(paths: list[str], retriever: Any) -> str:
    """Read text files and index them for vector retrieval."""
    loop = asyncio.get_running_loop()

    def _work() -> int:
        count = 0
        for raw in paths:
            path = Path(raw)
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # Chunk long documents for better retrieval granularity.
            for i in range(0, len(text), 2000):
                chunk = text[i : i + 2000].strip()
                if chunk:
                    retriever.index(chunk, {"source": str(path)})
                    count += 1
        return count

    indexed = await loop.run_in_executor(None, _work)
    return f"indexed {indexed} chunks from {len(paths)} paths"


async def consolidate_memory(memory: Any) -> str:
    """Summarize recent turns into one durable memory item."""
    turns = memory.recent_turns(10)
    if not turns:
        return "nothing to consolidate"
    summary = " | ".join(f"{t.role}: {t.content[:80]}" for t in turns)
    await memory.remember("system", f"session summary: {summary}", durable=True, kind="note")
    return f"consolidated {len(turns)} turns"


async def research_topic(topic: str, engine: Any, urls: list[str]) -> str:
    """Run a research task over ``urls`` and summarize findings."""
    results = await engine.research(topic, urls)
    ok = sum(1 for v in results.values() if not v.startswith("fetch failed"))
    return f"researched '{topic}': {ok}/{len(urls)} sources ok"
