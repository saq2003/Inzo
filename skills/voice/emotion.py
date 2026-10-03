"""Voice emotion skill: lexicon-based emotion scoring on text.

Real (deterministic, stdlib): :func:`score_emotion` counts Hindi + English
emotion words and returns normalized scores per emotion; :func:`dominant`
returns the top emotion (``"neutral"`` when nothing matches).
"""

from __future__ import annotations

import re

from skills.base import Skill, SkillContext

EMOTIONS: tuple[str, ...] = ("joy", "sadness", "anger", "fear", "surprise")

#: Word → emotion lexicon (Hindi + English).
_LEXICON: dict[str, str] = {
    # joy
    "khush": "joy",
    "khushi": "joy",
    "happy": "joy",
    "glad": "joy",
    "mazaa": "joy",
    "maza": "joy",
    "achha": "joy",
    "badhiya": "joy",
    "great": "joy",
    "awesome": "joy",
    "celebrate": "joy",
    "love": "joy",
    "pyaar": "joy",
    # sadness
    "dukh": "sadness",
    "sad": "sadness",
    "udaas": "sadness",
    "rona": "sadness",
    "cry": "sadness",
    "crying": "sadness",
    "depressed": "sadness",
    "akela": "sadness",
    "lonely": "sadness",
    "miss": "sadness",
    "tired": "sadness",
    "thak": "sadness",
    # anger
    "gussa": "anger",
    "angry": "anger",
    "naraz": "anger",
    "nafrat": "anger",
    "hate": "anger",
    "irritated": "anger",
    "annoyed": "anger",
    "frustrated": "anger",
    "chid": "anger",
    "bewakoof": "anger",
    # fear
    "dar": "fear",
    "darr": "fear",
    "fear": "fear",
    "scared": "fear",
    "afraid": "fear",
    "ghabrahat": "fear",
    "tension": "fear",
    "worried": "fear",
    "chinta": "fear",
    "khatra": "fear",
    "danger": "fear",
    # surprise
    "hairan": "surprise",
    "hairani": "surprise",
    "surprised": "surprise",
    "surprise": "surprise",
    "shocked": "surprise",
    "wow": "surprise",
    "arre": "surprise",
    "kamaal": "surprise",
    "amazing": "surprise",
    "unexpected": "surprise",
}

_WORD = re.compile(r"[a-z\u0900-\u097f]+")


def score_emotion(text: str) -> dict[str, float]:
    """Score emotions in ``text``; returns normalized per-emotion scores.

    Scores sum to 1.0 when any lexicon word matches, else all zeros.
    Deterministic.
    """
    counts: dict[str, float] = {emotion: 0.0 for emotion in EMOTIONS}
    words = _WORD.findall(text.lower())
    for word in words:
        emotion = _LEXICON.get(word)
        if emotion is not None:
            counts[emotion] += 1.0
    total = sum(counts.values())
    if total == 0.0:
        return counts
    return {emotion: value / total for emotion, value in counts.items()}


def dominant(text: str) -> str:
    """Return the dominant emotion in ``text`` (``"neutral"`` if none)."""
    scores = score_emotion(text)
    best = max(EMOTIONS, key=lambda emotion: scores[emotion])
    if scores[best] == 0.0:
        return "neutral"
    return best


class EmotionSkill(Skill):
    """Detects emotion in voice transcripts via a Hindi+English lexicon."""

    name = "voice_emotion"
    description = "Lexicon-based emotion scoring (joy, sadness, anger, fear, surprise)."
    intents = ("voice.emotion",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        """Score the message text and report the dominant emotion."""
        scores = score_emotion(context.message)
        top = dominant(context.message)
        detail = ", ".join(f"{e}={scores[e]:.2f}" for e in EMOTIONS)
        return f"emotion: {top} ({detail})"


SKILLS: list[Skill] = [EmotionSkill()]
