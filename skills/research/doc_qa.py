"""Document Q&A over local .txt/.md files (stdlib, fully local).

"index <dir>" walks the directory (skipping hidden files/dirs), chunks
each .txt/.md file by paragraphs, and stores chunks in
``data_dir/"docqa.db"`` via ``SQLiteDocumentStore``. "ask <question>"
keyword-scores the chunks and returns an answer excerpt with
``file:chunk`` citations.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast

from skills.base import Skill, SkillContext, SkillError, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_EXTENSIONS = (".txt", ".md")
_CHUNK_TARGET = 600


def _iter_files(root: Path) -> list[Path]:
    """Sorted .txt/.md files under ``root``, skipping hidden entries."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if filename.startswith("."):
                continue
            if filename.lower().endswith(_EXTENSIONS):
                found.append(Path(dirpath) / filename)
    return sorted(found)


def _chunk_text(text: str, target: int = _CHUNK_TARGET) -> list[str]:
    """Split text into paragraph-grouped chunks of roughly ``target`` chars."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) + 1 > target:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}".strip() if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def index_directory(data_dir: Path, source: Path) -> str:
    """Index .txt/.md files under ``source`` into ``data_dir/"docqa.db"``."""
    root = source if source.is_absolute() else data_dir / source
    if not root.is_dir():
        raise SkillError(f"not a directory: {source}")
    db_path = data_dir / "docqa.db"
    if db_path.exists():
        db_path.unlink()  # clean re-index; SQLiteDocumentStore has no delete
    store = SQLiteDocumentStore(db_path)
    files = _iter_files(root)
    doc_count = 0
    for path in files:
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, chunk in enumerate(_chunk_text(text)):
            doc: dict[str, Any] = {"path": rel, "chunk": idx, "text": chunk}
            store.add(doc)
            doc_count += 1
    return f"indexed {len(files)} file(s), {doc_count} chunk(s) from {root}"


def ask_question(data_dir: Path, question: str, limit: int = 3) -> str:
    """Keyword-score indexed chunks and return an excerpt with citations."""
    db_path = data_dir / "docqa.db"
    if not db_path.exists():
        return "no index yet — run 'index <directory>' first"
    store = SQLiteDocumentStore(db_path)
    hits = store.search(question, limit=limit)
    if not hits:
        return "no indexed content matches that question"
    lines = [f"Answer (from {len(hits)} matching chunk(s)):", ""]
    for hit in hits:
        doc = cast("dict[str, Any]", dict(hit))
        path = str(doc.get("path", "?"))
        chunk = doc.get("chunk", "?")
        excerpt = str(doc.get("text", ""))[:500]
        lines.append(f"[{path} · chunk {chunk}]")
        lines.append(excerpt)
        lines.append("")
    return "\n".join(lines).rstrip()


class DocQASkill(Skill):
    """Indexes local documents and answers questions with citations."""

    name = "doc_qa"
    description = (
        "Indexes .txt/.md files ('index <dir>') into paragraph chunks and "
        "answers questions ('ask <question>') with file:chunk citations."
    )
    intents = ("doc.index", "doc.qa")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "system.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        text = context.message.strip()
        low = text.lower()
        if low.startswith("index ") or low == "index":
            arg = text[len("index") :].strip() if low.startswith("index ") else ""
            if not arg:
                return "usage: index <directory> (relative paths resolve under the skill data dir)"
            return index_directory(data_dir, Path(arg))
        if low.startswith("ask ") or low == "ask":
            question = text[len("ask") :].strip() if low.startswith("ask ") else ""
            if not question:
                return "usage: ask <question>"
            return ask_question(data_dir, question)
        return "doc_qa usage: 'index <directory>' then 'ask <question>'"


SKILLS: list[Skill] = [DocQASkill()]
