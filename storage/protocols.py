"""INZO storage layer: replaceable persistence protocols (Rule 3, Rule 6).

Concrete backends implement these protocols; INZO Core only depends on the
protocols, so swapping SQLite for another store needs no core rewrite.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


class KeyValueStore(Protocol):
    """Simple string key/value persistence."""

    def get(self, key: str) -> str | None: ...
    def put(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> bool: ...
    def count(self) -> int: ...


class DocumentStore(Protocol):
    """JSON-document persistence with ids and naive text search."""

    def add(self, doc: Mapping[str, Any]) -> str: ...
    def get(self, doc_id: str) -> Mapping[str, Any] | None: ...
    def search(self, query: str, limit: int = 5) -> list[Mapping[str, Any]]: ...
    def count(self) -> int: ...


@dataclass(frozen=True)
class VectorRecord:
    """One embedded item in a vector store."""

    id: str
    vector: list[float]
    metadata: Mapping[str, Any] = field(default_factory=dict)


class VectorStore(Protocol):
    """Replaceable vector-search backend (Rule: start simple, swap later)."""

    def upsert(self, records: list[VectorRecord]) -> None: ...
    def query(
        self, vector: list[float], top_k: int = 5
    ) -> list[tuple[VectorRecord, float]]: ...
    def count(self) -> int: ...
