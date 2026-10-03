"""SQLite-backed local stores (stdlib ``sqlite3`` — Rule 1, Rule 15).

Development default. Production can swap any backend implementing the
storage protocols without touching INZO Core.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import UTC
from pathlib import Path
from typing import Any


class SQLiteKVStore:
    """Persistent string key/value store backed by SQLite."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def get(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def delete(self, key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            return cur.rowcount > 0

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM kv").fetchone()
        return int(row[0])


class SQLiteDocumentStore:
    """Persistent JSON document store backed by SQLite."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS docs "
                "(id TEXT PRIMARY KEY, body TEXT NOT NULL, created TEXT NOT NULL)"
            )

    def add(self, doc: Mapping[str, Any]) -> str:
        from datetime import datetime

        doc_id = str(uuid.uuid4())
        body = json.dumps(dict(doc))
        created = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO docs (id, body, created) VALUES (?, ?, ?)",
                (doc_id, body, created),
            )
        return doc_id

    def get(self, doc_id: str) -> Mapping[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT body FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            return None
        data: dict[str, Any] = json.loads(row[0])
        data["id"] = doc_id
        return data

    def search(self, query: str, limit: int = 5) -> list[Mapping[str, Any]]:
        """Naive case-insensitive substring search over stored JSON bodies."""
        terms = [t for t in query.lower().split() if t]
        with self._connect() as conn:
            rows = conn.execute("SELECT id, body FROM docs ORDER BY created DESC").fetchall()
        scored: list[tuple[int, Mapping[str, Any]]] = []
        for doc_id, body in rows:
            data: dict[str, Any] = json.loads(body)
            data["id"] = doc_id
            haystack = body.lower()
            score = sum(haystack.count(t) for t in terms)
            if score > 0 or not terms:
                scored.append((score, data))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [doc for _, doc in scored[:limit]]

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM docs").fetchone()
        return int(row[0])
