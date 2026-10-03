"""Local skill marketplace: index, verify, and install skill packs.

Real local logic over a simple index schema::

    {"name", "version", "author", "description", "files": [rel paths],
     "capabilities": [...], "sha256": {rel path: hex}}

``index <dir>`` walks a directory, hashes every file with
``hashlib.sha256``, and writes the index JSON under
``data_dir/"marketplace"/``. ``verify <index.json> [srcdir]`` re-hashes
and reports mismatches. ``install <index.json> <srcdir>`` copies files
into ``skills/_thirdparty/<name>/`` after safety checks: the name must
be a plain identifier, must not collide with an existing skill
directory, and no file may escape the target (no ``..``, no absolute
paths, no symlinks). Hashes are verified before copying.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from skills.base import Skill, SkillContext, SkillError, require_data_dir

_INDEX_DIR = "marketplace"
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SKIP_DIRS = {"__pycache__", ".git", ".hg", ".svn", "node_modules"}
_SKIP_SUFFIXES = (".pyc", ".pyo")


def _skills_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _relative_files(src: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(src.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(src)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix in _SKIP_SUFFIXES:
            continue
        files.append(rel.as_posix())
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(src: Path) -> dict[str, Any]:
    manifest_path = src / "skill.json"
    if not manifest_path.is_file():
        return {}
    try:
        data = cast("dict[str, Any]", json.loads(manifest_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def build_index(src: Path) -> dict[str, Any]:
    """Build the marketplace index dict for ``src`` (pure local logic)."""
    manifest = _read_manifest(src)
    files = _relative_files(src)
    sha256 = {rel: _sha256(src / rel) for rel in files}
    capabilities = manifest.get("capabilities", [])
    return {
        "name": str(manifest.get("name", src.name)),
        "version": str(manifest.get("version", "0.1.0")),
        "author": str(manifest.get("author", "unknown")),
        "description": str(manifest.get("description", "")),
        "files": files,
        "capabilities": list(capabilities) if isinstance(capabilities, list) else [],
        "sha256": sha256,
        "indexed_at": datetime.now(UTC).isoformat(),
        "source_dir": str(src),
    }


def _load_index(index_path: Path) -> dict[str, Any]:
    try:
        data = cast("dict[str, Any]", json.loads(index_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SkillError(f"cannot read index {index_path}: {exc}") from exc
    if not isinstance(data, dict) or "files" not in data or "sha256" not in data:
        raise SkillError(f"{index_path} is not a valid marketplace index")
    return data


def verify_index(index: dict[str, Any], src: Path) -> dict[str, list[str]]:
    """Re-hash ``src`` against ``index``; returns ok/mismatched/missing."""
    sha256 = cast("dict[str, str]", index.get("sha256", {}))
    result: dict[str, list[str]] = {"ok": [], "mismatched": [], "missing": []}
    for rel in cast("list[str]", index.get("files", [])):
        target = src / rel
        if not target.is_file():
            result["missing"].append(rel)
        elif _sha256(target) == sha256.get(rel):
            result["ok"].append(rel)
        else:
            result["mismatched"].append(rel)
    return result


def _safe_install_target(name: str) -> Path:
    if not _NAME_RE.match(name):
        raise SkillError(f"unsafe skill name: {name!r}")
    root = _skills_root()
    for candidate in (root / name, root / "_thirdparty" / name):
        if candidate.exists():
            raise SkillError(f"refusing install: '{name}' collides with {candidate}")
    target = root / "_thirdparty" / name
    if ".." in target.parts:
        raise SkillError(f"unsafe install path for {name!r}")
    return target


class SkillMarketplaceSkill(Skill):
    """Local index/verify/install for third-party skill packs."""

    name = "skill_marketplace"
    description = (
        "Local skill marketplace: 'index <dir>' builds a sha256 index, "
        "'verify <index.json> [srcdir]' re-hashes, "
        "'install <index.json> <srcdir>' installs into skills/_thirdparty/."
    )
    intents = ("market.index", "market.verify", "market.install")
    required_capabilities = ("skills.execute", "system.read", "memory.write")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        message = context.message.strip()
        lowered = message.lower()
        if lowered.startswith("index "):
            src = Path(message.split(None, 1)[1].strip()).expanduser()
            return self._index(data_dir, src)
        if lowered.startswith("verify "):
            parts = message.split()
            index_path = Path(parts[1]).expanduser()
            maybe_src = Path(parts[2]).expanduser() if len(parts) > 2 else None
            return self._verify(index_path, maybe_src)
        if lowered.startswith("install "):
            parts = message.split()
            if len(parts) != 3:
                return "usage: install <index.json> <srcdir>"
            return self._install(Path(parts[1]).expanduser(), Path(parts[2]).expanduser())
        return (
            "skill_marketplace: 'index <dir>', 'verify <index.json> [srcdir]', "
            "'install <index.json> <srcdir>'."
        )

    def _index(self, data_dir: Path, src: Path) -> str:
        if not src.is_dir():
            return f"not a directory: {src}"
        index = build_index(src)
        out_dir = data_dir / _INDEX_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{index['name']}.index.json"
        out_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        return (
            f"indexed '{index['name']}' v{index['version']}: "
            f"{len(index['files'])} files -> {out_path}"
        )

    def _verify(self, index_path: Path, src: Path | None) -> str:
        try:
            index = _load_index(index_path)
        except SkillError as exc:
            return str(exc)
        if src is None:
            src_text = str(index.get("source_dir", ""))
            if not src_text:
                return "verify needs a srcdir: 'verify <index.json> <srcdir>'"
            srcdir = Path(src_text)
        else:
            srcdir = src
        if not srcdir.is_dir():
            return f"not a directory: {srcdir}"
        result = verify_index(index, srcdir)
        lines = [
            f"verify '{index.get('name')}' against {srcdir}:",
            f"- ok: {len(result['ok'])}",
            f"- mismatched: {len(result['mismatched'])}",
            f"- missing: {len(result['missing'])}",
        ]
        for rel in result["mismatched"]:
            lines.append(f"  MISMATCH: {rel}")
        for rel in result["missing"]:
            lines.append(f"  MISSING: {rel}")
        return "\n".join(lines)

    def _install(self, index_path: Path, src: Path) -> str:
        try:
            index = _load_index(index_path)
        except SkillError as exc:
            return str(exc)
        if not src.is_dir():
            return f"not a directory: {src}"
        name = str(index.get("name", ""))
        try:
            target = _safe_install_target(name)
        except SkillError as exc:
            return str(exc)
        result = verify_index(index, src)
        if result["mismatched"] or result["missing"]:
            return (
                f"refusing install: {len(result['mismatched'])} mismatched, "
                f"{len(result['missing'])} missing files (verify first)"
            )
        try:
            target.mkdir(parents=True)
            for rel in cast("list[str]", index.get("files", [])):
                if rel.startswith("/") or ".." in Path(rel).parts:
                    raise SkillError(f"unsafe file path in index: {rel!r}")
                source_file = src / rel
                if source_file.is_symlink():
                    raise SkillError(f"refusing symlink: {rel!r}")
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, dest)
        except (OSError, SkillError) as exc:
            return f"install failed: {exc}"
        return f"installed '{name}' v{index.get('version')} ({len(result['ok'])} files) -> {target}"


SKILLS: list[Skill] = [SkillMarketplaceSkill()]
