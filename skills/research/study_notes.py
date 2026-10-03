"""Study notes generator: text -> headings, key points, glossary, quiz.

Pure stdlib text processing, fully local. Headings are detected from
markdown headers, ALL-CAPS lines, or short colon-terminated lines; key
points are the top frequency-scored sentences; the glossary mines
"X is/are/means Y" patterns; the quiz turns key sentences into 5
fill-in-the-blank questions.
"""

from __future__ import annotations

import re

from skills.base import Skill, SkillContext

_STOPWORDS = frozenset(
    "a about after again all also an and any are around because been before "
    "being between both but can does down during each from further had has "
    "have having into itself more most other over same some such than that "
    "the their them then there these they this those through under what when "
    "where which while with would your".split()
)
_GLOSSARY_RE = re.compile(
    r"\b([A-Z][A-Za-z ]{2,28}?)\s+(is|are|means|mean|refers to)\s+([^.!?\n]{8,140})"
)


def _sentences(text: str) -> list[str]:
    collapsed = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", collapsed)
    return [p.strip() for p in parts if len(p.strip()) > 20]


def _content_words(sentence: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{3,}", sentence.lower()) if w not in _STOPWORDS]


def detect_headings(text: str, limit: int = 10) -> list[str]:
    """Markdown headers, ALL-CAPS lines, or short colon-terminated lines."""
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
        elif len(stripped) < 80 and stripped == stripped.upper() and re.search(r"[A-Z]", stripped):
            headings.append(stripped)
        elif len(stripped) < 60 and stripped.endswith(":"):
            headings.append(stripped[:-1].strip())
        if len(headings) >= limit:
            break
    return [h for h in headings if h]


def key_points(text: str, n: int = 5) -> list[str]:
    """Top-``n`` sentences by word-frequency scoring, in original order."""
    sentences = _sentences(text)
    if len(sentences) <= n:
        return sentences
    freq: dict[str, int] = {}
    for sentence in sentences:
        for word in _content_words(sentence):
            freq[word] = freq.get(word, 0) + 1
    scored = [
        (sum(freq.get(w, 0) for w in _content_words(s)), i)
        for i, s in enumerate(sentences)
    ]
    top = sorted(sorted(scored, reverse=True)[:n], key=lambda item: item[1])
    return [sentences[i] for _, i in top]


def build_glossary(text: str, limit: int = 8) -> list[tuple[str, str]]:
    """Mine 'X is/are/means Y' definitions into (term, definition) pairs."""
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _GLOSSARY_RE.finditer(text):
        term = " ".join(match.group(1).split())
        definition = " ".join(match.group(3).split()).rstrip(",;")
        if term.lower() not in seen and len(term.split()) <= 4:
            seen.add(term.lower())
            entries.append((term, definition))
        if len(entries) >= limit:
            break
    return entries


def make_quiz(text: str, n: int = 5) -> list[tuple[str, str]]:
    """Fill-in-the-blank questions from key sentences: (question, answer)."""
    quiz: list[tuple[str, str]] = []
    for sentence in key_points(text, n):
        candidates = re.findall(r"[A-Za-z]{5,}", sentence)
        if not candidates:
            continue
        answer = max(candidates, key=len)
        question = re.sub(re.escape(answer), "_____", sentence, count=1)
        quiz.append((question, answer))
    return quiz[:n]


class StudyNotesSkill(Skill):
    """Turns raw text into structured study notes with a self-quiz."""

    name = "study_notes"
    description = (
        "Converts text into study notes: detected headings, key points, "
        "a glossary of 'X is Y' definitions, and fill-in-the-blank quiz "
        "questions."
    )
    intents = ("study.notes",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        for prefix in ("study notes", "notes"):
            if text.lower().startswith(prefix):
                text = text[len(prefix) :].strip(" :")
                break
        if len(text) < 40:
            return "usage: notes <text to study> (paste at least a paragraph)"
        lines = ["Study notes", ""]
        headings = detect_headings(text)
        lines.append("Headings:")
        lines.extend(f"- {h}" for h in headings) if headings else lines.append("(none detected)")
        lines.extend(["", "Key points:"])
        points = key_points(text)
        lines.extend(f"- {p}" for p in points) if points else lines.append("(none found)")
        lines.extend(["", "Glossary:"])
        glossary = build_glossary(text)
        if glossary:
            lines.extend(f"- {term}: {definition}" for term, definition in glossary)
        else:
            lines.append("(no 'X is Y' definitions found)")
        lines.extend(["", "Quiz:"])
        quiz = make_quiz(text)
        if quiz:
            for i, (question, answer) in enumerate(quiz, 1):
                lines.append(f"Q{i}: {question}")
                lines.append(f"A{i}: {answer}")
        else:
            lines.append("(not enough content for quiz questions)")
        return "\n".join(lines)


SKILLS: list[Skill] = [StudyNotesSkill()]
