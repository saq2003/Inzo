"""Memory manager: unified facade over short-term, long-term, and retrieval."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.logging_config import get_logger
from memory.long_term import LongTermMemory
from memory.retrieval import RetrievalHit, Retriever
from memory.short_term import MemoryItem, ShortTermMemory
from storage.protocols import DocumentStore

logger = get_logger(__name__)


@dataclass(frozen=True)
class MemoryHit:
    id: str
    text: str
    score: float
    source: str  # "vector" | "keyword" | "recent"


class MemoryManager:
    """Coordinates working memory, durable memory, and vector retrieval."""

    def __init__(
        self,
        document_store: DocumentStore,
        *,
        short_term: ShortTermMemory | None = None,
        retriever: Retriever | None = None,
    ) -> None:
        self.short_term = short_term or ShortTermMemory()
        self.long_term = LongTermMemory(document_store)
        self.retriever = retriever or Retriever()

    async def remember(
        self, role: str, content: str, *, durable: bool = False, kind: str = "note"
    ) -> str | None:
        """Buffer a turn; optionally persist it durably and index it."""
        self.short_term.add(role, content)
        if not durable:
            return None
        # CPU-light work stays inline; heavier indexing runs off the loop.
        loop = asyncio.get_running_loop()
        memory_id = await loop.run_in_executor(
            None, lambda: self.long_term.save(content, kind=kind)
        )
        await loop.run_in_executor(
            None, lambda: self.retriever.index(content, {"memory_id": memory_id})
        )
        logger.info("memory stored", extra={"id": memory_id, "kind": kind})
        return memory_id

    async def recall(self, query: str, limit: int = 5) -> list[MemoryHit]:
        """Recall relevant memories: vector search, keyword search, recency."""
        loop = asyncio.get_running_loop()
        vector_hits: list[RetrievalHit] = await loop.run_in_executor(
            None, lambda: self.retriever.search(query, top_k=limit)
        )
        keyword_docs = await loop.run_in_executor(
            None, lambda: self.long_term.search(query, limit=limit)
        )
        hits: list[MemoryHit] = [
            MemoryHit(id=h.id, text=h.text, score=h.score, source="vector")
            for h in vector_hits
            if h.score > 0
        ]
        seen = {h.id for h in hits}
        for doc in keyword_docs:
            doc_id = str(doc.get("id", ""))
            metadata_id = str(doc.get("memory_id", doc_id))
            if metadata_id in seen or doc_id in seen:
                continue
            hits.append(
                MemoryHit(
                    id=doc_id,
                    text=str(doc.get("text", "")),
                    score=0.5,
                    source="keyword",
                )
            )
        return hits[:limit]

    def recent_turns(self, n: int = 10) -> list[MemoryItem]:
        """Return recent conversation turns."""
        return self.short_term.recent(n)

    def stats(self) -> dict[str, int]:
        """Return memory subsystem counts."""
        return {
            "short_term_items": len(self.short_term),
            "long_term_items": self.long_term.count(),
            "vector_items": self.retriever.count(),
        }
