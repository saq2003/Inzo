"""Retrieval: embed text, index it, and vector-search it later."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from memory.vector_store import HashEmbedding, LocalVectorStore
from storage.protocols import VectorRecord, VectorStore


@dataclass(frozen=True)
class RetrievalHit:
    id: str
    text: str
    score: float
    metadata: Mapping[str, object]


class Retriever:
    """Indexes texts into a VectorStore and retrieves by semantic-ish similarity."""

    def __init__(
        self,
        store: VectorStore | None = None,
        embedding: HashEmbedding | None = None,
    ) -> None:
        self._store = store or LocalVectorStore()
        self._embedding = embedding or HashEmbedding()

    def index(self, text: str, metadata: Mapping[str, object] | None = None) -> str:
        """Embed and index ``text``; returns the record id."""
        record_id = str(uuid.uuid4())
        self._store.upsert(
            [
                VectorRecord(
                    id=record_id,
                    vector=self._embedding.embed(text),
                    metadata={"text": text, **(metadata or {})},
                )
            ]
        )
        return record_id

    def search(self, query: str, top_k: int = 5) -> list[RetrievalHit]:
        """Return the most similar indexed texts to ``query``."""
        vector = self._embedding.embed(query)
        hits: list[RetrievalHit] = []
        for record, score in self._store.query(vector, top_k=top_k):
            text = str(record.metadata.get("text", ""))
            hits.append(
                RetrievalHit(id=record.id, text=text, score=score, metadata=record.metadata)
            )
        return hits

    def count(self) -> int:
        return self._store.count()
