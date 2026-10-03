"""Speaker identification skill: voiceprint enroll + cosine-match identify.

Real (deterministic, stdlib): ``cosine_similarity`` over embedding vectors and
voiceprint persistence in a SQLite KV store. Embedding extraction itself needs
a model engine, so it is defined as :class:`SpeakerEmbedder` with a stub that
raises :class:`AdapterNotConfiguredError` instead of fabricating embeddings.
"""

from __future__ import annotations

import json
import math
from typing import Protocol, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_IDENTIFY_THRESHOLD = 0.75
_DB_NAME = "voiceprints.db"
_INDEX_KEY = "voiceprint:index"


class AdapterNotConfiguredError(RuntimeError):
    """Raised when a speaker-embedding adapter is required but not configured."""


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity of two vectors (deterministic, pure).

    Returns 0.0 when either vector is empty or has zero magnitude.

    Raises:
        ValueError: if the vectors have different lengths.
    """
    if len(a) != len(b):
        raise ValueError(f"embedding length mismatch: {len(a)} vs {len(b)}")
    if not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _index(store: SQLiteKVStore) -> list[str]:
    """Return enrolled speaker names from the index key."""
    raw = store.get(_INDEX_KEY)
    if raw is None:
        return []
    names: list[str] = cast("list[str]", json.loads(raw))
    return names


def enroll_voiceprint(store: SQLiteKVStore, name: str, embedding: list[float]) -> None:
    """Store a voiceprint embedding for ``name`` (overwrites any existing)."""
    store.put(f"voiceprint:{name}", json.dumps(embedding))
    names = _index(store)
    if name not in names:
        names.append(name)
        store.put(_INDEX_KEY, json.dumps(names))


def identify_speaker(
    store: SQLiteKVStore,
    embedding: list[float],
    *,
    threshold: float = _IDENTIFY_THRESHOLD,
) -> tuple[str | None, float]:
    """Identify a speaker by best cosine match; returns (name, score).

    Returns ``(None, best_score)`` when no stored voiceprint reaches
    ``threshold``.
    """
    best_name: str | None = None
    best_score = 0.0
    for name in _index(store):
        raw = store.get(f"voiceprint:{name}")
        if raw is None:
            continue
        stored: list[float] = cast("list[float]", json.loads(raw))
        score = cosine_similarity(embedding, stored)
        if score > best_score:
            best_name, best_score = name, score
    if best_name is None or best_score < threshold:
        return None, best_score
    return best_name, best_score


class SpeakerEmbedder(Protocol):
    """Plug-in point: turns raw mic samples into a speaker embedding vector.

    A production adapter implements this with a speaker-embedding model
    (e.g. Resemblyzer, ECAPA). Until configured, the skill raises instead of
    fabricating embeddings.
    """

    def embed(self, samples: bytes) -> list[float]:
        """Return the speaker embedding for raw PCM samples."""
        ...


class StubSpeakerEmbedder:
    """Speaker-embedder stub: always reports that it is not configured."""

    def embed(self, samples: bytes) -> list[float]:
        raise AdapterNotConfiguredError(
            "speaker embedding not configured: plug in a SpeakerEmbedder adapter"
        )


class SpeakerIdSkill(Skill):
    """Enrolls and identifies speakers from voiceprints."""

    name = "speaker_id"
    description = "Enrolls voiceprints and identifies speakers by cosine similarity."
    intents = ("speaker.enroll", "speaker.identify")
    required_capabilities = ("skills.execute", "memory.write", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Needs hardware/model: a SpeakerEmbedder adapter turns mic samples into "
        "embedding vectors, and enrollment/identification need mic audio. "
        "Inject via SpeakerIdSkill(embedder=...)."
    )

    def __init__(self, embedder: SpeakerEmbedder | None = None) -> None:
        self._embedder: SpeakerEmbedder = embedder or StubSpeakerEmbedder()

    async def handle(self, context: SkillContext) -> str:
        """Enroll or identify a speaker.

        Message protocol: ``enroll: <name>`` or ``identify`` — the audio must
        come from a configured embedder adapter.
        """
        data_dir = require_data_dir(context)
        store = SQLiteKVStore(data_dir / _DB_NAME)
        text = context.message.strip().lower()
        if text.startswith("enroll:"):
            new_name = text.split("enroll:", 1)[1].strip()
            if not new_name:
                return "speaker: usage is 'enroll: <name>'"
            try:
                embedding = self._embedder.embed(b"")
            except AdapterNotConfiguredError as exc:
                return f"speaker: {exc}"
            enroll_voiceprint(store, new_name, embedding)
            return f"speaker: enrolled voiceprint for '{new_name}'"
        if text.startswith("identify"):
            try:
                embedding = self._embedder.embed(b"")
            except AdapterNotConfiguredError as exc:
                return f"speaker: {exc}"
            name, score = identify_speaker(store, embedding)
            if name is None:
                return f"speaker: unknown (best score {score:.2f})"
            return f"speaker: identified as '{name}' (score {score:.2f})"
        return "speaker: say 'enroll: <name>' or 'identify'"


SKILLS: list[Skill] = [SpeakerIdSkill()]
