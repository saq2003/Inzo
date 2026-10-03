"""File organizer (fully local, stdlib only).

Organizes the top-level files of a directory into
``<dir>/organized/<ext|noext>/<YYYY-MM>/`` buckets by extension and
modification month.

* DRY-RUN by default: ``organize <dir>`` (or ``preview``) only lists the
  planned moves.
* ``organize <dir> confirm`` executes the moves.
* ``files.undo`` restores the most recent batch from the undo log in
  ``data_dir/"file_organizer.db"``.

Safety: never deletes anything; refuses system paths (``/``, the home
directory itself, ``/usr``, ``/etc``, ``/var``, ``/opt``, ``/root``,
``/bin``, ``/sbin``, ``/System``, ...); skips the ``organized/`` folder
itself on repeat runs.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from skills.base import Skill, SkillContext, SkillError, require_data_dir

_DB_NAME = "file_organizer.db"
_ORGANIZED = "organized"

_FORBIDDEN_PREFIXES = (
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/etc"),
    Path("/var"),
    Path("/opt"),
    Path("/root"),
    Path("/boot"),
    Path("/proc"),
    Path("/sys"),
    Path("/dev"),
    Path("/System"),
    Path("/Library"),
    Path("/Applications"),
)


def _refuse(path: Path) -> str | None:
    """Return a refusal reason, or None if ``path`` may be organized."""
    home = Path.home()
    if path == Path("/") or path == home:
        return "refusing to organize / or the home directory itself"
    if any(path == prefix or prefix in path.parents for prefix in _FORBIDDEN_PREFIXES):
        return f"refusing system path: {path}"
    return None


class _MoveLog:
    """Undo log: records executed moves as batches."""

    def __init__(self, path: Path) -> None:
        self._path = str(path)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS batches ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS moves ("
                "batch_id INTEGER NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL)"
            )

    def record(self, moves: list[tuple[Path, Path]]) -> int:
        with sqlite3.connect(self._path) as conn:
            cur = conn.execute(
                "INSERT INTO batches (ts) VALUES (?)", (datetime.now(UTC).isoformat(),)
            )
            batch_id = cur.lastrowid
            if batch_id is None:
                raise SkillError("sqlite did not return a batch id")
            conn.executemany(
                "INSERT INTO moves (batch_id, src, dst) VALUES (?, ?, ?)",
                [(batch_id, str(src), str(dst)) for src, dst in moves],
            )
        return batch_id

    def latest(self) -> tuple[int, list[tuple[Path, Path]]]:
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                "SELECT id FROM batches ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return 0, []
            batch_id = int(row[0])
            rows = conn.execute(
                "SELECT src, dst FROM moves WHERE batch_id = ? ORDER BY rowid DESC",
                (batch_id,),
            ).fetchall()
        return batch_id, [(Path(r[0]), Path(r[1])) for r in rows]

    def drop(self, batch_id: int) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute("DELETE FROM moves WHERE batch_id = ?", (batch_id,))
            conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))


def plan_moves(directory: Path) -> list[tuple[Path, Path]]:
    """Compute (src, dst) moves for top-level files of ``directory``."""
    moves: list[tuple[Path, Path]] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.name == _ORGANIZED:
            continue
        ext = entry.suffix.lower().lstrip(".") or "noext"
        stamp = datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC)
        bucket = stamp.strftime("%Y-%m")
        dest_dir = directory / _ORGANIZED / ext / bucket
        dest = dest_dir / entry.name
        if dest.exists():
            stem, suffix = entry.stem, entry.suffix
            n = 1
            while (dest_dir / f"{stem}_{n}{suffix}").exists():
                n += 1
            dest = dest_dir / f"{stem}_{n}{suffix}"
        if dest != entry:
            moves.append((entry, dest))
    return moves


class FileOrganizerSkill(Skill):
    """Organizes a directory's files (dry-run default, undoable)."""

    name = "file_organizer"
    description = (
        "Organizes a directory's files into organized/<ext>/<YYYY-MM>/ "
        "buckets; dry-run by default, 'confirm' executes, 'undo' restores; "
        "never deletes; refuses system paths."
    )
    intents = ("files.organize", "files.undo")
    required_capabilities = ("skills.execute", "system.read", "memory.write")
    background = True
    local_only = True

    def _log(self, context: SkillContext) -> _MoveLog:
        return _MoveLog(require_data_dir(context) / _DB_NAME)

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("files.undo") or lowered == "undo":
            return self._undo(context)
        # "organize <dir> [confirm]" / "files.organize <dir> [confirm]" / "preview <dir>"
        payload = text
        for prefix in ("files.organize", "organize", "preview"):
            if lowered.startswith(prefix):
                payload = text[len(prefix) :].strip()
                break
        confirm = payload.lower().endswith(" confirm")
        if confirm:
            payload = payload[: -len(" confirm")].strip()
        target = Path(payload or ".").expanduser().resolve()
        refusal = _refuse(target)
        if refusal:
            return f"file_organizer: {refusal}"
        if not target.is_dir():
            return f"file_organizer: not a directory: {target}"
        moves = plan_moves(target)
        if not moves:
            return f"file_organizer: nothing to organize in {target}"
        if not confirm:
            lines = [f"dry-run: {len(moves)} move(s) planned in {target} (add 'confirm' to run):"]
            lines.extend(f"  {src.name} -> {dst.relative_to(target)}" for src, dst in moves[:20])
            if len(moves) > 20:
                lines.append(f"  ... and {len(moves) - 20} more")
            return "\n".join(lines)
        done = 0
        for src, dst in moves:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                done += 1
            except OSError as exc:
                return f"file_organizer: move failed ({src.name}: {exc}); {done} moved before failure"
        batch_id = self._log(context).record(moves[:done])
        return f"file_organizer: moved {done} file(s) (batch #{batch_id}); 'undo' restores them"

    def _undo(self, context: SkillContext) -> str:
        log = self._log(context)
        batch_id, moves = log.latest()
        if not moves:
            return "file_organizer: nothing to undo"
        restored = 0
        for src, dst in moves:
            try:
                if dst.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dst), str(src))
                    restored += 1
            except OSError:
                continue
        log.drop(batch_id)
        # Best-effort cleanup of now-empty bucket dirs.
        for _, dst in moves:
            parent = dst.parent
            try:
                while parent.name != _ORGANIZED and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
            except OSError:
                break
        return f"file_organizer: restored {restored}/{len(moves)} file(s) from batch #{batch_id}"


SKILLS: list[Skill] = [FileOrganizerSkill()]
