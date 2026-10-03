"""Pomodoro focus timer: persisted state machine with a 60s tick."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE = "pomodoro.db"
_STATE_KEY = "state"

_FOCUS_S = 25 * 60
_BREAK_S = 5 * 60
_LONG_BREAK_S = 15 * 60


@dataclass
class PomodoroState:
    """phase is idle|focus|break|long_break; ends_at is ISO when running."""

    phase: str = "idle"
    ends_at: str | None = None
    completed: int = 0


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


def _load_state(context: SkillContext) -> PomodoroState:
    kv = SQLiteKVStore(require_data_dir(context) / _STORE)
    raw = kv.get(_STATE_KEY)
    if raw is None:
        return PomodoroState()
    data = cast(dict[str, object], json.loads(raw))
    phase = data.get("phase")
    ends_at = data.get("ends_at")
    completed = data.get("completed")
    return PomodoroState(
        phase=phase if isinstance(phase, str) else "idle",
        ends_at=ends_at if isinstance(ends_at, str) else None,
        completed=completed if isinstance(completed, int) else 0,
    )


def _save_state(context: SkillContext, state: PomodoroState) -> None:
    kv = SQLiteKVStore(require_data_dir(context) / _STORE)
    kv.put(
        _STATE_KEY,
        json.dumps(
            {"phase": state.phase, "ends_at": state.ends_at, "completed": state.completed}
        ),
    )


def _describe(state: PomodoroState, now: datetime) -> str:
    if state.phase == "idle" or state.ends_at is None:
        return f"pomodoro idle — {state.completed} focus session(s) completed"
    try:
        ends = datetime.fromisoformat(state.ends_at)
    except ValueError:
        return "pomodoro state corrupt — use 'stop' to reset"
    remaining = max(0, int((ends - now).total_seconds()))
    return (
        f"pomodoro {state.phase}: {remaining // 60}m {remaining % 60:02d}s left "
        f"({state.completed} completed)"
    )


class FocusPomodoroSkill(Skill):
    """Pomodoro timer: 25m focus, 5m break, 15m long break every 4th."""

    name = "focus_pomodoro"
    description = (
        "Focus timer: 'start' begins a 25-minute focus block, 'status' shows "
        "the current phase and remaining time, 'stop' resets. The 60-second "
        "tick advances phases and notifies on transitions."
    )
    intents = ("focus.start", "focus.stop", "focus.status")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 60.0

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip().lower()
        if text.startswith("start"):
            return await self._start(context)
        if text.startswith("stop"):
            return self._stop(context)
        if text.startswith("status"):
            return _describe(_load_state(context), datetime.now().astimezone())
        return await self._advance(context)

    async def _start(self, context: SkillContext) -> str:
        state = _load_state(context)
        if state.phase != "idle":
            return "pomodoro already running — " + _describe(state, datetime.now().astimezone())
        now = datetime.now().astimezone()
        state.phase = "focus"
        state.ends_at = (now + timedelta(seconds=_FOCUS_S)).isoformat()
        _save_state(context, state)
        await _notify(context, "pomodoro: focus started (25m)")
        return "focus started — 25 minutes. good luck."

    def _stop(self, context: SkillContext) -> str:
        _save_state(context, PomodoroState())
        return "pomodoro stopped and reset"

    async def _advance(self, context: SkillContext) -> str:
        state = _load_state(context)
        now = datetime.now().astimezone()
        if state.phase == "idle" or state.ends_at is None:
            return _describe(state, now)
        try:
            ends = datetime.fromisoformat(state.ends_at)
        except ValueError:
            _save_state(context, PomodoroState())
            return "pomodoro state was corrupt — reset to idle"
        if now < ends:
            return _describe(state, now)
        if state.phase == "focus":
            state.completed += 1
            if state.completed % 4 == 0:
                state.phase = "long_break"
                state.ends_at = (now + timedelta(seconds=_LONG_BREAK_S)).isoformat()
                message = "pomodoro: 4 sessions done — take a 15 minute long break"
            else:
                state.phase = "break"
                state.ends_at = (now + timedelta(seconds=_BREAK_S)).isoformat()
                message = "pomodoro: focus finished — take a 5 minute break"
        else:
            state.phase = "focus"
            state.ends_at = (now + timedelta(seconds=_FOCUS_S)).isoformat()
            message = "pomodoro: break over — next 25 minute focus block started"
        _save_state(context, state)
        await _notify(context, message)
        return message


SKILLS: list[Skill] = [FocusPomodoroSkill()]
