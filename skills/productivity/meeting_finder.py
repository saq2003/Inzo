"""Meeting finder: free slots from the local calendar."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from skills.base import Skill, SkillContext
from skills.productivity.calendar_local import _load_events

_WORK_START = time(9, 0)
_WORK_END = time(18, 0)
_GRANULARITY_MIN = 15
_MAX_SLOTS = 6


class MeetingFinderSkill(Skill):
    """Finds free meeting slots inside 09:00-18:00, skipping busy events."""

    name = "meeting_finder"
    description = (
        "Free-slot finder: 'find <minutes> [YYYY-MM-DD]' scans 09:00-18:00 on "
        "the given day (default today), skips events from the local calendar, "
        "and returns the first free slots long enough for the meeting."
    )
    intents = ("meeting.find",)
    required_capabilities = ("skills.execute", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        if not text.lower().startswith("find "):
            return "meeting usage: 'find <minutes> [YYYY-MM-DD]'"
        parts = text[5:].split()
        try:
            minutes = int(parts[0])
        except ValueError as exc:
            return f"find failed: minutes must be an integer ({exc})"
        if minutes <= 0:
            return "find failed: minutes must be positive"
        if len(parts) > 1:
            try:
                day = date.fromisoformat(parts[1])
            except ValueError as exc:
                return f"find failed: bad date ({exc})"
        else:
            day = datetime.now().astimezone().date()
        return self._find(context, minutes, day)

    def _find(self, context: SkillContext, minutes: int, day: date) -> str:
        tz = datetime.now().astimezone().tzinfo
        day_start = datetime.combine(day, _WORK_START).replace(tzinfo=tz)
        day_end = datetime.combine(day, _WORK_END).replace(tzinfo=tz)
        busy: list[tuple[datetime, datetime]] = []
        for event in _load_events(context):
            if event.start.date() != day and event.end.date() != day:
                continue
            busy.append((max(event.start, day_start), min(event.end, day_end)))
        busy = [(s, e) for s, e in busy if e > s]
        busy.sort()

        slots: list[tuple[datetime, datetime]] = []
        cursor = day_start
        step = timedelta(minutes=_GRANULARITY_MIN)
        needed = timedelta(minutes=minutes)
        for start, end in [*busy, (day_end, day_end)]:
            while cursor + needed <= start and len(slots) < _MAX_SLOTS:
                slots.append((cursor, cursor + needed))
                cursor += step
            cursor = max(cursor, end)
        if not slots:
            return f"no {minutes}-minute slot free on {day.isoformat()}"
        lines = [f"free {minutes}-minute slots on {day.isoformat()}:"]
        lines.extend(
            f"  {s.strftime('%H:%M')}-{e.strftime('%H:%M')}" for s, e in slots
        )
        return "\n".join(lines)


SKILLS: list[Skill] = [MeetingFinderSkill()]
