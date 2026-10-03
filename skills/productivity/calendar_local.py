"""Local calendar: add/list/delete events with conflict detection."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE = "calendar.db"
_INDEX_KEY = "events:index"


@dataclass(frozen=True)
class CalendarEvent:
    """A calendar event with timezone-aware ISO start/end."""

    id: str
    title: str
    start: datetime
    end: datetime


def _event_to_json(event: CalendarEvent) -> str:
    return json.dumps(
        {
            "title": event.title,
            "start": event.start.isoformat(),
            "end": event.end.isoformat(),
        }
    )


def _load_events(context: SkillContext) -> list[CalendarEvent]:
    """Read all events; tolerate a missing store file."""
    path = require_data_dir(context) / _STORE
    if not path.exists():
        return []
    kv = SQLiteKVStore(path)
    raw_index = kv.get(_INDEX_KEY)
    ids: list[str] = cast(list[str], json.loads(raw_index)) if raw_index else []
    events: list[CalendarEvent] = []
    for event_id in ids:
        raw = kv.get(f"event:{event_id}")
        if raw is None:
            continue
        data = cast(dict[str, str], json.loads(raw))
        try:
            start = datetime.fromisoformat(str(data.get("start", "")))
            end = datetime.fromisoformat(str(data.get("end", "")))
        except ValueError:
            continue
        events.append(
            CalendarEvent(
                id=event_id, title=str(data.get("title", "")), start=start, end=end
            )
        )
    events.sort(key=lambda e: e.start)
    return events


def _save_events(context: SkillContext, events: list[CalendarEvent]) -> None:
    kv = SQLiteKVStore(require_data_dir(context) / _STORE)
    for event in events:
        kv.put(f"event:{event.id}", _event_to_json(event))
    kv.put(_INDEX_KEY, json.dumps([e.id for e in events]))


def _format_event(event: CalendarEvent) -> str:
    return (
        f"{event.id[:8]}: {event.title} — "
        f"{event.start.strftime('%Y-%m-%d %H:%M')} to {event.end.strftime('%H:%M')}"
    )


class CalendarLocalSkill(Skill):
    """Local event store with overlap warnings on add."""

    name = "calendar_local"
    description = (
        "Local calendar: 'add <title> | <start_iso> | <end_iso>' stores an event "
        "(warns on overlap), 'list [YYYY-MM-DD]' shows events, "
        "'delete <id>' removes one."
    )
    intents = ("calendar.add", "calendar.list", "calendar.delete")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("add "):
            return self._add(context, text[4:])
        if lowered.startswith("list"):
            return self._list(context, text[4:].strip())
        if lowered.startswith("delete "):
            return self._delete(context, text[7:].strip())
        return (
            "calendar: 'add <title> | <start_iso> | <end_iso>' | 'list [YYYY-MM-DD]' | "
            "'delete <id>'"
        )

    def _add(self, context: SkillContext, arg: str) -> str:
        parts = [p.strip() for p in arg.split("|")]
        if len(parts) != 3:
            return "add usage: 'add <title> | <start_iso> | <end_iso>'"
        title, raw_start, raw_end = parts
        try:
            start = datetime.fromisoformat(raw_start)
            end = datetime.fromisoformat(raw_end)
        except ValueError as exc:
            return f"add failed: bad ISO datetime ({exc})"
        if not title:
            return "add failed: title is empty"
        if end <= start:
            return "add failed: end must be after start"
        if start.tzinfo is None:
            start = start.astimezone()
        if end.tzinfo is None:
            end = end.astimezone()
        events = _load_events(context)
        conflicts = [
            e for e in events if e.start < end and start < e.end
        ]
        event = CalendarEvent(id=uuid.uuid4().hex, title=title, start=start, end=end)
        _save_events(context, [*events, event])
        lines = [f"event added: {_format_event(event)}"]
        for conflict in conflicts:
            lines.append(f"  warning: overlaps '{conflict.title}' ({_format_event(conflict)})")
        return "\n".join(lines)

    def _list(self, context: SkillContext, arg: str) -> str:
        events = _load_events(context)
        if arg:
            events = [e for e in events if e.start.strftime("%Y-%m-%d") == arg]
            label = f" on {arg}"
        else:
            label = ""
        if not events:
            return f"no events{label}"
        lines = [f"events{label}:"]
        lines.extend(f"  {_format_event(e)}" for e in events)
        return "\n".join(lines)

    def _delete(self, context: SkillContext, arg: str) -> str:
        prefix = arg.strip().lower()
        if not prefix:
            return "delete usage: 'delete <id>'"
        events = _load_events(context)
        matches = [e for e in events if e.id.lower().startswith(prefix)]
        if not matches:
            return f"no event matches id '{arg.strip()}'"
        if len(matches) > 1:
            return "ambiguous id — matches: " + ", ".join(_format_event(e) for e in matches)
        removed = matches[0]
        remaining = [e for e in events if e.id != removed.id]
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)
        kv.delete(f"event:{removed.id}")
        kv.put(_INDEX_KEY, json.dumps([e.id for e in remaining]))
        return f"deleted: {_format_event(removed)}"


SKILLS: list[Skill] = [CalendarLocalSkill()]
