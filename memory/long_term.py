"""Long-term memory: durable facts/notes on the replaceable DocumentStore."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from storage.protocols import DocumentStore


class LongTermMemory:
    """Persist and search durable memories via a DocumentStore backend."""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def save(self, text: str, kind: str = "note", tags: list[str] | None = None) -> str:
        """Persist one memory; returns its id."""
        if not text.strip():
            raise ValueError("cannot save empty memory")
        return self._store.add(
            {"text": text, "kind": kind, "tags": tags or []}
        )

    def get(self, memory_id: str) -> Mapping[str, Any] | None:
        """Fetch one memory by id."""
        return self._store.get(memory_id)

    def search(self, query: str, limit: int = 5) -> list[Mapping[str, Any]]:
        """Keyword search over stored memories."""
        return self._store.search(query, limit=limit)

    def count(self) -> int:
        return self._store.count()
