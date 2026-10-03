"""Local vector store: deterministic stdlib-only embeddings + cosine search.

This is the development default (Rule 15: runnable locally, zero services).
Swap in a real embedding model and vector database by implementing
``storage.protocols.VectorStore`` — no core changes needed.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from storage.protocols import VectorRecord

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class HashEmbedding:
    """Deterministic bag-of-words hashing embedding (no model, no network).

    Tokens are hashed into ``dim`` buckets and L2-normalized. Good enough
    for local development and testing; not a semantic embedding.
    """

    dim: int = 128

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _TOKEN_RE.findall(text.lower()):
            bucket = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dim
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # inputs are L2-normalized


class LocalVectorStore:
    """In-memory vector store with cosine similarity (implements VectorStore)."""

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    def upsert(self, records: list[VectorRecord]) -> None:
        for record in records:
            self._records[record.id] = record

    def query(
        self, vector: list[float], top_k: int = 5
    ) -> list[tuple[VectorRecord, float]]:
        scored = [
            (record, _cosine(vector, record.vector))
            for record in self._records.values()
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._records)
