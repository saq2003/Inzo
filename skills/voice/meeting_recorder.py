"""Meeting recorder skill: session lifecycle, transcripts, extractive summaries.

Real (deterministic, stdlib): sessions, segments, and transcripts are stored
in a SQLite document store; :func:`extractive_summary` scores sentences by
word frequency and returns the top-N in original order.
"""

from __future__ import annotations

import re
from collections import Counter

from skills.base import Skill, SkillContext, SkillError, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_DB_NAME = "meetings.db"
_SUMMARY_SENTENCES = 3
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9']+")


def _is_closed(store: SQLiteDocumentStore, session_id: str) -> bool:
    """Return True when a ``session_close`` marker exists for the session."""
    return any(
        doc.get("type") == "session_close" and doc.get("session_id") == session_id
        for doc in store.search(f"session_close {session_id}", limit=1000)
    )


def start_meeting(store: SQLiteDocumentStore, title: str) -> str:
    """Start a meeting session; returns its session id."""
    return store.add({"type": "session", "title": title})


def add_segment(store: SQLiteDocumentStore, session_id: str, text: str) -> str:
    """Append a transcript segment to an open session; returns segment id.

    Raises:
        SkillError: if the session does not exist or is closed.
    """
    session = store.get(session_id)
    if session is None or session.get("type") != "session":
        raise SkillError(f"unknown meeting session: {session_id}")
    if _is_closed(store, session_id):
        raise SkillError(f"meeting session is closed: {session_id}")
    return store.add({"type": "segment", "session_id": session_id, "text": text})


def stop_meeting(store: SQLiteDocumentStore, session_id: str) -> None:
    """Close a meeting session.

    Raises:
        SkillError: if the session does not exist.
    """
    session = store.get(session_id)
    if session is None or session.get("type") != "session":
        raise SkillError(f"unknown meeting session: {session_id}")
    store.add({"type": "session_close", "session_id": session_id})


def get_transcript(store: SQLiteDocumentStore, session_id: str) -> str:
    """Assemble the full transcript of a session in segment order."""
    segments = [
        doc
        for doc in store.search(f"segment {session_id}", limit=1000)
        if doc.get("type") == "segment" and doc.get("session_id") == session_id
    ]
    texts = [str(seg.get("text", "")) for seg in segments]
    return "\n".join(text for text in texts if text).strip()


def extractive_summary(text: str, max_sentences: int = _SUMMARY_SENTENCES) -> str:
    """Return an extractive summary: top sentences by word-frequency score.

    Scores each sentence by the sum of its words' frequencies in the whole
    text, picks the top-N, and returns them in original order. Deterministic.
    """
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    if len(sentences) <= max_sentences:
        return " ".join(sentences)
    freq: Counter[str] = Counter()
    for sentence in sentences:
        freq.update(_WORD.findall(sentence.lower()))
    scored = [
        (sum(freq[w] for w in _WORD.findall(sentence.lower())), idx, sentence)
        for idx, sentence in enumerate(sentences)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    top = sorted(scored[:max_sentences], key=lambda item: item[1])
    return " ".join(sentence for _, _, sentence in top)


def summarize_meeting(store: SQLiteDocumentStore, session_id: str) -> str:
    """Summarize a session's transcript.

    Raises:
        SkillError: if the session has no transcript.
    """
    transcript = get_transcript(store, session_id)
    if not transcript:
        raise SkillError(f"meeting session has no transcript: {session_id}")
    return extractive_summary(transcript)


class MeetingRecorderSkill(Skill):
    """Records meeting sessions and summarizes them extractively."""

    name = "meeting_recorder"
    description = "Records meeting transcripts and produces extractive summaries."
    intents = ("meeting.start", "meeting.stop", "meeting.summary")
    required_capabilities = ("skills.execute", "memory.write")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        """Drive the session lifecycle from the message.

        Message protocol: ``start: <title>``,
        ``segment: <session-id> | <text>``, ``stop: <session-id>``,
        ``summary: <session-id>``.
        """
        data_dir = require_data_dir(context)
        store = SQLiteDocumentStore(data_dir / _DB_NAME)
        text = context.message.strip()
        lowered = text.lower()
        try:
            if lowered.startswith("start:"):
                title = text.split(":", 1)[1].strip() or "untitled meeting"
                session_id = start_meeting(store, title)
                return f"meeting started: '{title}' (id={session_id})"
            if lowered.startswith("segment:"):
                rest = text.split(":", 1)[1]
                session_id, _, segment_text = rest.partition("|")
                session_id, segment_text = session_id.strip(), segment_text.strip()
                if not session_id or not segment_text:
                    return "meeting: usage is 'segment: <session-id> | <text>'"
                seg_id = add_segment(store, session_id, segment_text)
                return f"segment added (id={seg_id})"
            if lowered.startswith("stop:"):
                session_id = text.split(":", 1)[1].strip()
                stop_meeting(store, session_id)
                return f"meeting stopped (id={session_id})"
            if lowered.startswith("summary:"):
                session_id = text.split(":", 1)[1].strip()
                summary = summarize_meeting(store, session_id)
                return f"summary: {summary}"
        except SkillError as exc:
            return f"meeting error: {exc}"
        return (
            "meeting: use 'start: <title>', 'segment: <id> | <text>', "
            "'stop: <id>', or 'summary: <id>'"
        )


SKILLS: list[Skill] = [MeetingRecorderSkill()]
