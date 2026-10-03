"""Background task endpoints: submit, list, inspect."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import dependencies
from app.schemas import TaskInfo, TaskSubmitRequest
from intelligence.research.engine import ResearchEngine
from workers import tasks as task_fns
from workers.queue import TaskHandle

router = APIRouter()


def _to_info(handle: TaskHandle) -> TaskInfo:
    return TaskInfo(
        id=handle.id,
        name=handle.name,
        status=handle.status.value,
        result=handle.result,
        error=handle.error,
    )


@router.post("/api/tasks", response_model=TaskInfo)
async def submit_task(request: TaskSubmitRequest) -> TaskInfo:
    """Submit a background task (indexing, memory consolidation, research)."""
    queue = dependencies.get_task_queue()
    memory = dependencies.get_memory_manager()

    if request.kind == "index_documents":
        paths = [str(p) for p in request.payload.get("paths", [])]
        factory = lambda: task_fns.index_documents(paths, memory.retriever)  # noqa: E731
    elif request.kind == "consolidate_memory":
        factory = lambda: task_fns.consolidate_memory(memory)  # noqa: E731
    elif request.kind == "research":
        topic = str(request.payload.get("topic", ""))
        urls = [str(u) for u in request.payload.get("urls", [])]
        engine = ResearchEngine()
        factory = lambda: task_fns.research_topic(topic, engine, urls)  # noqa: E731
    else:  # pragma: no cover - schema constrains this
        raise HTTPException(status_code=400, detail="unknown task kind")

    handle = await queue.submit(request.name, factory)
    return _to_info(handle)


@router.get("/api/tasks", response_model=list[TaskInfo])
async def list_tasks() -> list[TaskInfo]:
    """List background tasks."""
    return [_to_info(h) for h in dependencies.get_task_queue().list()]


@router.get("/api/tasks/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str) -> TaskInfo:
    """Inspect one background task."""
    handle = dependencies.get_task_queue().get(task_id)
    if handle is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _to_info(handle)
