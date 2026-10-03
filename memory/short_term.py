"""Short-term (working) memory: bounded in-process conversation buffer."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class MemoryItem:
    role: str  # "user" | "assistant" | "system"
    content: str
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ShortTermMemory:
    """FIFO buffer of recent turns; oldest items evict automatically."""

    def __init__(self, max_items: int = 50) -> None:
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        self._items: deque[MemoryItem] = deque(maxlen=max_items)

    def add(self, role: str, content: str) -> MemoryItem:
        """Append a turn; returns the stored item."""
        item = MemoryItem(role=role, content=content)
        self._items.append(item)
        return item

    def recent(self, n: int = 10) -> list[MemoryItem]:
        """Return up to ``n`` most recent items, oldest first."""
        return list(self._items)[-n:]

    def clear(self) -> None:
        """Drop all buffered turns."""
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
