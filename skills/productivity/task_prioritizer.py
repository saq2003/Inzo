"""Task list with a deterministic priority score."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE = "tasks.db"
_INDEX_KEY = "tasks:index"
_ADD_RE = re.compile(
    r"^add\s+(.+?)(?:\s+importance\s+([1-5]))?(?:\s+due\s+(\S+))?(?:\s+effort\s+(\d+))?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Task:
    """A task with importance 1-5, optional ISO due, and effort in minutes."""

    id: str
    title: str
    importance: int
    due: datetime | None
    effort_min: int


def score_task(task: Task, now: datetime) -> float:
    """Priority score: importance*2 + due urgency - effort/60.

    Urgency is 30 minus days until due (floor 0), so nearer deadlines score
    higher; overdue tasks score above 30. Tasks without a due date get no
    urgency bonus.
    """
    urgency = 0.0
    if task.due is not None:
        days = (task.due - now).total_seconds() / 86400
        urgency = max(0.0, 30.0 - days)
    return task.importance * 2 + urgency - task.effort_min / 60


def _task_to_json(task: Task) -> str:
    return json.dumps(
        {
            "title": task.title,
            "importance": task.importance,
            "due": task.due.isoformat() if task.due else None,
            "effort_min": task.effort_min,
        }
    )


def _load_tasks(context: SkillContext) -> list[Task]:
    """Read all tasks; tolerate a missing store file."""
    path = require_data_dir(context) / _STORE
    if not path.exists():
        return []
    kv = SQLiteKVStore(path)
    raw_index = kv.get(_INDEX_KEY)
    ids: list[str] = cast(list[str], json.loads(raw_index)) if raw_index else []
    tasks: list[Task] = []
    for task_id in ids:
        raw = kv.get(f"task:{task_id}")
        if raw is None:
            continue
        data = cast(dict[str, object], json.loads(raw))
        due_raw = data.get("due")
        due: datetime | None = None
        if isinstance(due_raw, str) and due_raw:
            try:
                due = datetime.fromisoformat(due_raw)
            except ValueError:
                due = None
        importance = data.get("importance")
        effort = data.get("effort_min")
        tasks.append(
            Task(
                id=task_id,
                title=str(data.get("title", "")),
                importance=int(importance) if isinstance(importance, int) else 3,
                due=due,
                effort_min=int(effort) if isinstance(effort, int) else 30,
            )
        )
    return tasks


def _save_index(context: SkillContext, ids: list[str]) -> None:
    SQLiteKVStore(require_data_dir(context) / _STORE).put(_INDEX_KEY, json.dumps(ids))


def _parse_due(raw: str) -> datetime:
    try:
        due = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"bad due datetime: {raw!r} (use ISO, e.g. 2026-10-05T17:00)") from exc
    if due.tzinfo is None:
        due = due.astimezone()
    return due


class TaskPrioritizerSkill(Skill):
    """Task list ranked by a deterministic priority score."""

    name = "task_prioritizer"
    description = (
        "Task manager: 'add <title> [importance 1-5] [due <iso>] [effort <min>]' "
        "stores a task, 'prioritize' ranks open tasks by score "
        "(importance*2 + due urgency - effort/60), 'done <id>' completes one."
    )
    intents = ("task.add", "task.prioritize", "task.done")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("add "):
            return self._add(context, text)
        if lowered.startswith("prioritize"):
            return self._prioritize(context)
        if lowered.startswith("done "):
            return self._done(context, text[5:].strip())
        return (
            "tasks: 'add <title> [importance 1-5] [due <iso>] [effort <min>]' | "
            "'prioritize' | 'done <id>'"
        )

    def _add(self, context: SkillContext, text: str) -> str:
        match = _ADD_RE.match(text)
        if not match or not match.group(1).strip():
            return (
                "add usage: 'add <title> [importance 1-5] [due <iso>] [effort <min>]'"
            )
        title = match.group(1).strip()
        importance = int(match.group(2)) if match.group(2) else 3
        due: datetime | None = None
        if match.group(3):
            try:
                due = _parse_due(match.group(3))
            except ValueError as exc:
                return f"add failed: {exc}"
        effort = int(match.group(4)) if match.group(4) else 30
        if effort < 0:
            return "add failed: effort must be >= 0"
        task = Task(id=uuid.uuid4().hex, title=title, importance=importance, due=due, effort_min=effort)
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)
        kv.put(f"task:{task.id}", _task_to_json(task))
        raw_index = kv.get(_INDEX_KEY)
        ids: list[str] = cast(list[str], json.loads(raw_index)) if raw_index else []
        _save_index(context, [*ids, task.id])
        return f"task added ({task.id[:8]}): {title}"

    def _prioritize(self, context: SkillContext) -> str:
        tasks = _load_tasks(context)
        if not tasks:
            return "no open tasks"
        now = datetime.now().astimezone()
        ranked = sorted(tasks, key=lambda t: score_task(t, now), reverse=True)
        lines = ["tasks by priority:"]
        for task in ranked:
            due_str = task.due.strftime("%Y-%m-%d %H:%M") if task.due else "no due"
            lines.append(
                f"  {task.id[:8]} [{score_task(task, now):.1f}] {task.title} "
                f"(imp {task.importance}, due {due_str}, {task.effort_min}m)"
            )
        return "\n".join(lines)

    def _done(self, context: SkillContext, arg: str) -> str:
        prefix = arg.lower()
        if not prefix:
            return "done usage: 'done <id>'"
        tasks = _load_tasks(context)
        matches = [t for t in tasks if t.id.lower().startswith(prefix)]
        if not matches:
            return f"no task matches id '{arg}'"
        if len(matches) > 1:
            return "ambiguous id: " + ", ".join(f"{t.id[:8]} {t.title}" for t in matches)
        done = matches[0]
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)
        kv.delete(f"task:{done.id}")
        _save_index(context, [t.id for t in tasks if t.id != done.id])
        return f"done: {done.title}"


SKILLS: list[Skill] = [TaskPrioritizerSkill()]
