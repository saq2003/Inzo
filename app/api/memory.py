"""Memory endpoints: store, recall, stats."""

from __future__ import annotations

from fastapi import APIRouter

from app import dependencies
from app.schemas import (
    MemoryHit,
    MemoryRecallRequest,
    MemoryRecallResponse,
    MemoryStatsResponse,
    MemoryStoreRequest,
    MemoryStoreResponse,
)
from security.validation import sanitize_text

router = APIRouter()


@router.post("/api/memory/store", response_model=MemoryStoreResponse)
async def store_memory(request: MemoryStoreRequest) -> MemoryStoreResponse:
    """Persist a durable memory and index it for retrieval."""
    memory = dependencies.get_memory_manager()
    text = sanitize_text(request.text)
    memory_id = await memory.remember("user", text, durable=True, kind=request.kind)
    return MemoryStoreResponse(id=memory_id or "", kind=request.kind)


@router.post("/api/memory/recall", response_model=MemoryRecallResponse)
async def recall_memory(request: MemoryRecallRequest) -> MemoryRecallResponse:
    """Recall relevant memories for a query."""
    memory = dependencies.get_memory_manager()
    hits = await memory.recall(sanitize_text(request.query, 1000), limit=request.limit)
    return MemoryRecallResponse(
        hits=[
            MemoryHit(id=h.id, text=h.text, score=round(h.score, 4), source=h.source)
            for h in hits
        ]
    )


@router.get("/api/memory/stats", response_model=MemoryStatsResponse)
async def memory_stats() -> MemoryStatsResponse:
    """Memory subsystem counts."""
    stats = dependencies.get_memory_manager().stats()
    return MemoryStatsResponse(**stats)
