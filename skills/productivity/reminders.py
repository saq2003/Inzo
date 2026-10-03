"""Local reminders with a 60-second background tick (English + Hinglish)."""

from __future__ import annotations

import inspect
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE = "reminders.db"
_INDEX_KEY = "reminders:index"

_IN_RE = re.compile(r"^add\s+in\s+(\d+)\s*(?:m(?:in(?:ute)?s?)?)\s+(.+)$", re.IGNORECASE)
_AT_RE = re.compile(r"^add\s+at\s+(\d{1,2}):(\d{2})\s+(.+)$", re.IGNORECASE)
_HINGLISH_RE = re.compile(
    r"^(?:add\s+)?(\d+)\s*minutes?\s+m(?:e|ein)\s+yaad\s+dilao\s+(.+)$", re.IGNORECASE
)


@dataclass(frozen=True)
class Reminder:
    """A stored reminder: text and due time (ISO, timezone-aware)."""

    id: str
    text: str
    due_iso: str


async def _notify(context: SkillContext, text: str) -> bool:
    """Deliver a notification when a notification center is wired."""
    center = context.notifications
    if center is None:
        return False
    send = getattr(center, "send", None) or getattr(center, "notify", None)
    if send is None:
        return False
    result = send(text)
    if inspect.isawaitable(result):
        await result
    return True


def _load_ids(kv: SQLiteKVStore) -> list[str]:
    raw = kv.get(_INDEX_KEY)
    if raw is None:
        return []
    data = cast(list[str], json.loads(raw))
    return [str(item) for item in data]


def _pending(context: SkillContext) -> list[Reminder]:
    kv = SQLiteKVStore(require_data_dir(context) / _STORE)
    reminders: list[Reminder] = []
    for reminder_id in _load_ids(kv):
        raw = kv.get(f"reminder:{reminder_id}")
        if raw is None:
            continue
        data = cast(dict[str, str], json.loads(raw))
        reminders.append(
            Reminder(
                id=reminder_id,
                text=str(data.get("text", "")),
                due_iso=str(data.get("due_iso", "")),
            )
        )
    reminders.sort(key=lambda r: r.due_iso)
    return reminders


class RemindersSkill(Skill):
    """Sets reminders; the 60s tick fires due ones via notification."""

    name = "reminders"
    description = (
        "Local reminders: 'add in <N> minutes <text>', 'add at HH:MM <text>', "
        "or Hinglish '<N> minute me yaad dilao <text>'; 'list' shows pending. "
        "The 60-second tick fires due reminders and marks them done."
    )
    intents = ("reminder.add", "reminder.list")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 60.0

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        if text.lower() == "list":
            return self._list(context)
        match = _IN_RE.match(text) or _HINGLISH_RE.match(text)
        if match:
            due = datetime.now().astimezone() + timedelta(minutes=int(match.group(1)))
            return self._add(context, match.group(2).strip(), due)
        match = _AT_RE.match(text)
        if match:
            now = datetime.now().astimezone()
            due = now.replace(
                hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0
            )
            if due <= now:
                due = due + timedelta(days=1)
            return self._add(context, match.group(3).strip(), due)
        if text.lower().startswith("add"):
            return (
                "reminder usage: 'add in <N> minutes <text>' | 'add at HH:MM <text>' | "
                "'<N> minute me yaad dilao <text>'"
            )
        return await self._fire_due(context)

    def _add(self, context: SkillContext, text: str, due: datetime) -> str:
        if not text:
            return "reminder failed: text is empty"
        reminder_id = uuid.uuid4().hex[:8]
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)
        kv.put(
            f"reminder:{reminder_id}",
            json.dumps({"text": text, "due_iso": due.isoformat()}),
        )
        ids = _load_ids(kv)
        kv.put(_INDEX_KEY, json.dumps([*ids, reminder_id]))
        return f"reminder set for {due.strftime('%Y-%m-%d %H:%M')}: {text}"

    def _list(self, context: SkillContext) -> str:
        reminders = _pending(context)
        if not reminders:
            return "no pending reminders"
        lines = ["pending reminders:"]
        for reminder in reminders:
            due = datetime.fromisoformat(reminder.due_iso)
            lines.append(f"  {due.strftime('%Y-%m-%d %H:%M')}: {reminder.text}")
        return "\n".join(lines)

    async def _fire_due(self, context: SkillContext) -> str:
        reminders = _pending(context)
        if not reminders:
            return "no pending reminders"
        now = datetime.now().astimezone()
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)
        ids = _load_ids(kv)
        fired = 0
        for reminder in reminders:
            try:
                due = datetime.fromisoformat(reminder.due_iso)
            except ValueError:
                continue
            if due <= now:
                await _notify(context, f"reminder: {reminder.text}")
                kv.delete(f"reminder:{reminder.id}")
                if reminder.id in ids:
                    ids.remove(reminder.id)
                fired += 1
        kv.put(_INDEX_KEY, json.dumps(ids))
        if fired:
            return f"fired {fired} due reminder(s)"
        return "no reminders due"


SKILLS: list[Skill] = [RemindersSkill()]
