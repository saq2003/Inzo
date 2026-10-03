"""Repository documentation generator (fully local, stdlib only).

Walks a repository directory (skipping hidden entries, ``.git``,
``__pycache__``, ``node_modules``, virtualenvs, and build caches),
extracts module/class/function docstrings with ``ast``, and emits a
Markdown document with a file tree plus an API summary.

Files that fail to parse are listed, not fatal.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from skills.base import Skill, SkillContext

_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
    ".tox",
}


@dataclass
class _DocEntry:
    kind: str  # "module" | "class" | "function"
    name: str
    doc: str
    signature: str = ""
    children: list[_DocEntry] = field(default_factory=list)


def _docstring(node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    doc = ast.get_docstring(node) or ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def _func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    parts: list[str] = []
    for arg in node.args.args:
        parts.append(arg.arg)
    if node.args.vararg:
        parts.append("*" + node.args.vararg.arg)
    for arg in node.args.kwonlyargs:
        parts.append(arg.arg)
    if node.args.kwarg:
        parts.append("**" + node.args.kwarg.arg)
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}def {node.name}({', '.join(parts)})"


def _extract_module(path: Path) -> _DocEntry:
    entry = _DocEntry(kind="module", name=path.name, doc="")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        entry.doc = f"(unparseable: {exc})"
        return entry
    entry.doc = _docstring(tree)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            cls = _DocEntry(
                kind="class", name=node.name, doc=_docstring(node), signature=node.name
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    cls.children.append(
                        _DocEntry(
                            kind="function",
                            name=child.name,
                            doc=_docstring(child),
                            signature=_func_signature(child),
                        )
                    )
            entry.children.append(cls)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entry.children.append(
                _DocEntry(
                    kind="function",
                    name=node.name,
                    doc=_docstring(node),
                    signature=_func_signature(node),
                )
            )
    return entry


def _iter_py_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        if rel.parts and rel.parts[0] in _SKIP_DIRS:
            continue
        found.append(path)
    return found


def document_repo(root: Path) -> str:
    """Walk ``root`` and return a Markdown doc (tree + API summary)."""
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    files = _iter_py_files(root)
    lines = [f"# Repository docs: {root.name}", "", "## File tree", ""]
    if not files:
        lines.append("(no Python files found)")
    else:
        for path in files:
            depth = len(path.relative_to(root).parts) - 1
            lines.append(f"{'  ' * depth}- `{path.relative_to(root).as_posix()}`")
    lines += ["", "## API summary", ""]
    for path in files:
        rel = path.relative_to(root).as_posix()
        entry = _extract_module(path)
        lines.append(f"### `{rel}`")
        lines.append(entry.doc or "(no module docstring)")
        lines.append("")
        for child in entry.children:
            if child.kind == "class":
                lines.append(f"- class `{child.signature}` — {child.doc or 'no docstring'}")
                for method in child.children:
                    lines.append(
                        f"  - `{method.signature}` — {method.doc or 'no docstring'}"
                    )
            else:
                lines.append(f"- `{child.signature}` — {child.doc or 'no docstring'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class RepoDocsSkill(Skill):
    """Generates Markdown documentation for a local repository."""

    name = "repo_docs"
    description = (
        "Walks a repo directory, extracts module/class/function docstrings "
        "with ast, and emits a Markdown doc (file tree + API summary)."
    )
    intents = ("repo.docs",)
    required_capabilities = ("skills.execute", "system.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        target = context.message.strip() or "."
        # Strip a leading intent word if present ("repo.docs <path>").
        first, _, rest = target.partition(" ")
        if first.lower() in ("repo.docs", "docs"):
            target = rest.strip() or "."
        root = Path(target).expanduser()
        if not root.is_absolute() and context.data_dir is not None:
            root = Path(context.data_dir) / root
        try:
            doc = document_repo(root.resolve())
        except ValueError as exc:
            return f"repo docs error: {exc}"
        except OSError as exc:
            return f"repo docs error: cannot read {root}: {exc}"
        saved = ""
        if context.data_dir is not None:
            try:
                out = Path(context.data_dir) / f"repo_docs_{root.name}.md"
                out.write_text(doc, encoding="utf-8")
                saved = f"\n(saved to {out})"
            except OSError as exc:
                saved = f"\n(warning: could not save: {exc})"
        return doc + saved


SKILLS: list[Skill] = [RepoDocsSkill()]
