"""Camera Q&A skill (hardware-gated, real event/query logging).

The ``CameraFeed`` and ``VisionModel`` Protocols are the plug-in points:
a real feed supplies frames and a real vision model answers questions
about them. The bundled stubs raise ``NotConfigured`` so the skill never
invents what the camera sees. Motion events and asked questions are
logged honestly to ``data_dir/"home.db"``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore


class NotConfigured(Exception):
    """Raised by stub adapters when no real hardware backend is plugged in."""


class CameraFeed(Protocol):
    """Plug-in point: supplies a snapshot frame from a camera.

    Attach with ``CameraQaSkill.set_feed``.
    """

    def snapshot(self) -> bytes:
        """Return a JPEG/PNG snapshot frame."""
        ...


class VisionModel(Protocol):
    """Plug-in point: answers a natural-language question about a frame.

    Attach with ``CameraQaSkill.set_vision``.
    """

    def describe(self, frame: bytes, question: str) -> str:
        """Answer ``question`` about the given frame bytes."""
        ...


class StubFeed:
    """Ships with the skill; always fails honestly."""

    def snapshot(self) -> bytes:
        raise NotConfigured(
            "no camera feed configured — plug a CameraFeed implementation "
            "via CameraQaSkill.set_feed"
        )


class StubVision:
    """Ships with the skill; always fails honestly."""

    def describe(self, frame: bytes, question: str) -> str:
        raise NotConfigured(
            "no vision model configured — plug a VisionModel implementation "
            "via CameraQaSkill.set_vision"
        )


class CameraQaSkill(Skill):
    """Answers questions about camera frames and logs motion events."""

    name = "camera_qa"
    description = (
        "Ask questions about what the home camera sees and log motion events. "
        "Needs a CameraFeed + VisionModel adapter; without them it reports "
        "not-configured and only records the query."
    )
    intents = ("camera.ask",)
    required_capabilities = ("skills.execute", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Requires a real camera and vision model. Implement the CameraFeed "
        "Protocol (snapshot) and VisionModel Protocol (describe), attach via "
        "CameraQaSkill.set_feed / set_vision; stubs raise NotConfigured."
    )

    def __init__(self) -> None:
        self._feed: CameraFeed = StubFeed()
        self._vision: VisionModel = StubVision()

    def set_feed(self, feed: CameraFeed) -> None:
        """Attach a real camera-feed implementation."""
        self._feed = feed

    def set_vision(self, vision: VisionModel) -> None:
        """Attach a real vision-model implementation."""
        self._vision = vision

    def _log(self, context: SkillContext, doc: dict[str, Any]) -> None:
        store = SQLiteDocumentStore(require_data_dir(context) / "home.db")
        store.add(doc)

    def _answer(self, context: SkillContext, question: str) -> str:
        """Real pipeline: snapshot frame, ask vision model, log the query."""
        try:
            frame = self._feed.snapshot()
        except NotConfigured as exc:
            self._log(
                context,
                {
                    "kind": "camera_query",
                    "question": question,
                    "answer": None,
                    "ts": datetime.now(UTC).isoformat(),
                },
            )
            return f"not configured: {exc} (query recorded)"
        try:
            answer = self._vision.describe(frame, question)
        except NotConfigured as exc:
            self._log(
                context,
                {
                    "kind": "camera_query",
                    "question": question,
                    "answer": None,
                    "ts": datetime.now(UTC).isoformat(),
                },
            )
            return f"not configured: {exc} (frame captured, query recorded)"
        self._log(
            context,
            {
                "kind": "camera_query",
                "question": question,
                "answer": answer,
                "ts": datetime.now(UTC).isoformat(),
            },
        )
        return answer

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()

        if text.lower().startswith("motion "):
            detail = text[7:].strip() or "motion detected"
            self._log(
                context,
                {
                    "kind": "motion_event",
                    "detail": detail,
                    "ts": datetime.now(UTC).isoformat(),
                },
            )
            return f"motion event recorded: {detail}"

        if text.lower().startswith("log "):
            detail = text[4:].strip() or "event"
            self._log(
                context,
                {
                    "kind": "motion_event",
                    "detail": detail,
                    "ts": datetime.now(UTC).isoformat(),
                },
            )
            return f"camera event recorded: {detail}"

        if text.lower() in ("events", "history"):
            store = SQLiteDocumentStore(require_data_dir(context) / "home.db")
            docs = store.search("motion_event camera_query", limit=20)
            if not docs:
                return "no camera events or queries recorded yet"
            lines = [
                f"{d.get('ts')} [{d.get('kind')}] {d.get('detail') or d.get('question')}"
                for d in docs
            ]
            return "\n".join(lines)

        question = text
        for prefix in ("ask ", "camera "):
            if question.lower().startswith(prefix):
                question = question[len(prefix) :]
                break
        if not question.strip():
            return "usage: ask <question> | motion <detail> | events"
        return self._answer(context, question.strip())


SKILLS: list[Skill] = [CameraQaSkill()]
