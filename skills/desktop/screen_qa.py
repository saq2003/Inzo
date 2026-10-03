"""Screen question-answering (adapter-based; honest when unconfigured).

Two plug-in boundaries, both implemented outside this codebase:

* :class:`ScreenCapture` — grabs the screen (needs OS/display access).
* :class:`VisionModel` — answers a question about an image (needs a model).

What IS real and local: the question router (keyword-based classification
into ``ocr`` / ``count`` / ``locate`` / ``describe``) and the answer cache
in ``data_dir/"screenqa.db"`` keyed by question + image hash. When an
adapter is missing, the skill says so plainly and stores the question for
later instead of inventing an answer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol, cast

from skills.base import Skill, SkillContext, require_data_dir
from skills.desktop.tray_app import NotConfiguredError
from storage.sqlite_store import SQLiteKVStore

_DB_NAME = "screenqa.db"
_ANSWERS_KEY = "answers"
_PENDING_KEY = "pending"

_ROUTERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ocr", ("read", "text", "ocr", "says", "written")),
    ("count", ("how many", "count", "number of")),
    ("locate", ("where", "find", "locate", "position", "button")),
)


class ScreenCapture(Protocol):
    """OS screen-capture integration point."""

    def capture(self) -> bytes:
        """Return a screenshot as raw image bytes (e.g. PNG)."""
        ...


class VisionModel(Protocol):
    """Vision model integration point."""

    def describe(self, image: bytes, question: str) -> str:
        """Answer ``question`` about ``image``."""
        ...


class _UnconfiguredCapture:
    def capture(self) -> bytes:
        raise NotConfiguredError(
            "no ScreenCapture configured: inject one via "
            "ScreenQASkill(capture=...) implemented outside this codebase."
        )


class _UnconfiguredVision:
    def describe(self, image: bytes, question: str) -> str:
        raise NotConfiguredError(
            "no VisionModel configured: inject one via "
            "ScreenQASkill(vision=...) implemented outside this codebase."
        )


def route_question(question: str) -> str:
    """Classify a question into ocr/count/locate/describe (keyword router)."""
    lowered = question.lower()
    for kind, keywords in _ROUTERS:
        if any(kw in lowered for kw in keywords):
            return kind
    return "describe"


def _cache_key(question: str, image: bytes) -> str:
    digest = hashlib.sha256(question.encode("utf-8") + image).hexdigest()
    return f"answer:{digest}"


def _get_json(store: SQLiteKVStore, key: str) -> list[dict[str, str]]:
    raw = store.get(key)
    return cast("list[dict[str, str]]", json.loads(raw)) if raw else []


def _put_json(store: SQLiteKVStore, key: str, value: list[dict[str, str]]) -> None:
    store.put(key, json.dumps(value))


class ScreenQASkill(Skill):
    """Answers questions about the screen via capture+vision adapters."""

    name = "screen_qa"
    description = (
        "Answers questions about the current screen: routes the question, "
        "caches answers, and uses pluggable ScreenCapture/VisionModel "
        "adapters (honest 'not configured' path when missing)."
    )
    intents = ("screen.ask",)
    required_capabilities = ("skills.execute", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Screen capture and vision need OS/hardware/model integration outside "
        "this codebase: ScreenQASkill(capture=..., vision=...). Question "
        "routing and answer caching are local."
    )

    def __init__(
        self,
        capture: ScreenCapture | None = None,
        vision: VisionModel | None = None,
    ) -> None:
        self._capture: ScreenCapture = capture if capture is not None else _UnconfiguredCapture()
        self._vision: VisionModel = vision if vision is not None else _UnconfiguredVision()

    def _store(self, context: SkillContext) -> SQLiteKVStore:
        return SQLiteKVStore(require_data_dir(context) / _DB_NAME)

    async def handle(self, context: SkillContext) -> str:
        question = context.message.strip()
        if question.lower().startswith("screen.ask"):
            question = question[len("screen.ask") :].strip()
        if not question:
            return "screen_qa: usage: 'screen.ask <your question about the screen>'"
        store = self._store(context)
        try:
            image = self._capture.capture()
        except NotConfiguredError as exc:
            pending = _get_json(store, _PENDING_KEY)
            pending.append({"question": question, "route": route_question(question)})
            _put_json(store, _PENDING_KEY, pending)
            return (
                f"screen capture adapter not configured: {exc} "
                f"Question saved ({len(pending)} pending); no answer invented."
            )
        key = _cache_key(question, image)
        cached = store.get(key)
        if cached is not None:
            return f"[cached] {cached}"
        route = route_question(question)
        try:
            answer = self._vision.describe(image, question)
        except NotConfiguredError as exc:
            return (
                f"vision adapter not configured: {exc} "
                f"(question routed as '{route}'; screenshot captured but not analyzed)"
            )
        store.put(key, answer)
        return f"[{route}] {answer}"


SKILLS: list[Skill] = [ScreenQASkill()]
