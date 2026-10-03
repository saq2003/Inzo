"""Input validation helpers (Rule 11, Rule 12 support)."""

from __future__ import annotations


def sanitize_text(text: str, max_length: int = 8000) -> str:
    """Strip control characters and clamp length for untrusted text."""
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch in ("\n", "\t"))
    return clamp_length(cleaned.strip(), max_length)


def clamp_length(text: str, max_length: int) -> str:
    """Hard-clamp ``text`` to ``max_length`` characters."""
    if max_length < 0:
        raise ValueError("max_length must be >= 0")
    return text[:max_length]
