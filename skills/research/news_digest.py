"""RSS/Atom news digest with a local SQLite cache (stdlib, fully local).

Fetches a configurable feed list (defaults are 3 public, keyless feeds),
parses RSS2 and Atom with ``xml.etree.ElementTree``, caches items in
``data_dir/"news.db"`` (dedupe by link — the same schema the morning
briefing reads), and refreshes on an hourly tick. "digest" returns the
top 8 headlines.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import cast
from urllib.parse import urlparse

from skills.base import Skill, SkillContext, SkillError, require_data_dir

_DEFAULT_FEEDS: tuple[tuple[str, str], ...] = (
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Hacker News", "https://hnrss.org/frontpage"),
    ("NPR News", "https://feeds.npr.org/1001/rss.xml"),
)
_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
_DIGEST_LIMIT = 8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds (
    url TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    link TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    published TEXT NOT NULL DEFAULT '',
    fetched_ts REAL NOT NULL
);
"""


async def _fetch(url: str, *, timeout: float = 8.0, retries: int = 2) -> str | None:
    """Fetch ``url`` with bounded retries; return decoded text or None."""
    if urlparse(url).scheme.lower() not in ("http", "https"):
        return None
    request = urllib.request.Request(  # noqa: S310 — scheme allowlisted to http/https above
        url, headers={"User-Agent": "inzo-news/0.1"}
    )
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw_bytes = cast("bytes", response.read())
                return raw_bytes.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — network is unreliable; retry, then give up
            attempt += 1
            if attempt > retries:
                return None
            await asyncio.sleep(min(2.0**attempt, 4.0))


def _child_text(parent: ET.Element, tag: str) -> str:
    child = parent.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _parse_feed(xml_text: str, source: str) -> list[tuple[str, str, str]]:
    """Parse RSS2 (channel/item) and Atom (feed/entry); return (title, link, published)."""
    try:
        # stdlib-only project (defusedxml is not stdlib); feeds are fetched
        # over https with timeouts and parse failures return []
        root = ET.fromstring(xml_text)  # noqa: S314
    except ET.ParseError:
        return []
    items: list[tuple[str, str, str]] = []
    for item in root.iter("item"):  # RSS2
        title, link = _child_text(item, "title"), _child_text(item, "link")
        if title and link:
            items.append((title, link, _child_text(item, "pubDate")))
    for entry in root.findall("a:entry", _ATOM_NS):  # Atom
        title_el = entry.find("a:title", _ATOM_NS)
        link_el = entry.find("a:link", _ATOM_NS)
        pub_el = entry.find("a:published", _ATOM_NS)
        if pub_el is None:
            pub_el = entry.find("a:updated", _ATOM_NS)
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.get("href") or "").strip() if link_el is not None else ""
        published = (pub_el.text or "").strip() if pub_el is not None else ""
        if title and link:
            items.append((title, link, published))
    return items


class NewsStore:
    """SQLite feed list + cached items (dedupe by link)."""

    def __init__(self, path: object) -> None:
        self._path = str(path)
        with sqlite3.connect(self._path) as conn:
            conn.executescript(_SCHEMA)
            for name, url in _DEFAULT_FEEDS:
                conn.execute(
                    "INSERT OR IGNORE INTO feeds (url, name) VALUES (?, ?)", (url, name)
                )

    def feeds(self) -> list[tuple[str, str]]:
        """Configured (name, url) feeds."""
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute("SELECT name, url FROM feeds ORDER BY name").fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]

    def add_feed(self, name: str, url: str) -> None:
        """Add a feed URL (must be http/https)."""
        if urlparse(url).scheme.lower() not in ("http", "https"):
            raise SkillError(f"refusing non-http(s) feed URL: {url!r}")
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO feeds (url, name) VALUES (?, ?)", (url, name)
            )

    def cache(self, items: list[tuple[str, str, str, str]]) -> int:
        """Cache (title, link, source, published) items; returns new count."""
        now = time.time()
        with sqlite3.connect(self._path) as conn:
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO news_items (title, link, source, published, fetched_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                [(t, link, src, pub, now) for t, link, src, pub in items],
            )
            return conn.total_changes - before

    def top(self, limit: int = _DIGEST_LIMIT) -> list[tuple[str, str]]:
        """Newest cached (title, source) headlines."""
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT title, source FROM news_items ORDER BY fetched_ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]


class NewsDigestSkill(Skill):
    """Fetches RSS/Atom feeds, caches them, and serves headline digests."""

    name = "news_digest"
    description = (
        "Maintains an RSS/Atom cache ('digest' refreshes and shows top 8 "
        "headlines; 'feeds' lists sources; 'feed add <url>' adds one)."
    )
    intents = ("news.digest",)
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "network.fetch")
    background = True
    local_only = True
    tick_interval_s = 3600.0

    def _store(self, context: SkillContext) -> NewsStore:
        return NewsStore(require_data_dir(context) / "news.db")

    async def _refresh(self, store: NewsStore) -> tuple[int, int]:
        """Fetch all feeds into the cache; returns (feeds_ok, new_items)."""
        feeds_ok, new_items = 0, 0
        for name, url in store.feeds():
            raw = await _fetch(url)
            if raw is None:
                continue
            parsed = _parse_feed(raw, name)
            if parsed:
                feeds_ok += 1
                new_items += store.cache([(t, link, name, pub) for t, link, pub in parsed])
        return feeds_ok, new_items

    async def handle(self, context: SkillContext) -> str:
        store = self._store(context)
        text = context.message.strip()
        low = text.lower()
        if low.startswith("feed add "):
            url = text[len("feed add ") :].strip()
            name = urlparse(url).netloc or url
            store.add_feed(name, url)
            return f"feed added: {name} ({url})"
        if low in ("feeds", "feed list", "list feeds"):
            feeds = store.feeds()
            return "feeds:\n" + "\n".join(f"- {name}: {url}" for name, url in feeds)
        feeds_ok, new_items = await self._refresh(store)
        top = store.top()
        if not top:
            return f"digest: no headlines cached ({feeds_ok} feed(s) reachable)"
        lines = [f"News digest — {len(top)} headlines ({new_items} new):", ""]
        lines.extend(f"{i + 1}. {title} ({source})" for i, (title, source) in enumerate(top))
        return "\n".join(lines)


SKILLS: list[Skill] = [NewsDigestSkill()]
