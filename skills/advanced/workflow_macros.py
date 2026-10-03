"""Workflow macros: named multi-skill routines defined in YAML or JSON.

A macro is ``{"name": str, "steps": [{"skill": str, "message": str}]}``.
Definitions are written with a minimal from-scratch YAML-subset parser
(nested maps, block lists via ``- ``, scalars, ``#`` comments) with a
``json.loads`` fallback, then executed step by step: each step builds a
fresh sub-``SkillContext`` and calls the target skill's ``handle``.

The skill registry is imported lazily *inside* ``handle`` (never at
module import time) to avoid import-time coupling between skill groups.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from skills.base import Skill, SkillContext, SkillError, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE_FILE = "macros.db"
_INDEX_KEY = "macro:index"
_RUNS_KEY = "macro:runs"
_MAX_RUNS_KEPT = 50
_MAX_STEPS = 20
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ---------------------------------------------------------------------------
# Minimal YAML-subset parser (~60 lines, documented).
#
# Supported: nested mappings via indentation, block sequences via "- " items,
# plain/quoted scalars (int/float/bool/null auto-typed), "#" comments.
# NOT supported: flow syntax ([], {}), anchors/aliases, multi-line "|"/">"
# literals, tabs for indentation, "#" inside quoted scalars. Anything fancier
# should be supplied as JSON instead (the define path falls back to it).
# ---------------------------------------------------------------------------


def _scalar(raw: str) -> Any:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    lowered = text.lower()
    if lowered in ("null", "~", ""):
        return None
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _strip_comment(line: str) -> str:
    # A "#" starts a comment only at line start or after whitespace, so
    # "key: a#b" keeps its value while "key: v # note" drops the note.
    return re.sub(r"(^|\s)#.*$", "", line).rstrip()


def _parse_block(items: list[tuple[int, str]], i: int, indent: int) -> tuple[Any, int]:
    if items[i][1] == "-" or items[i][1].startswith("- "):
        result_list: list[Any] = []
        while (
            i < len(items)
            and items[i][0] == indent
            and (items[i][1] == "-" or items[i][1].startswith("- "))
        ):
            content = items[i][1][1:].strip() if items[i][1].startswith("- ") else ""
            i += 1
            if not content:
                if i < len(items) and items[i][0] > indent:
                    nested, i = _parse_block(items, i, items[i][0])
                    result_list.append(nested)
                else:
                    result_list.append(None)
            elif ":" in content:
                # "- key: value" starts a mapping item; deeper lines extend it.
                key, _, val = content.partition(":")
                item_map: dict[str, Any] = {key.strip(): _scalar(val)}
                if i < len(items) and items[i][0] > indent:
                    nested, i = _parse_block(items, i, items[i][0])
                    if isinstance(nested, dict):
                        item_map.update(nested)
                result_list.append(item_map)
            else:
                result_list.append(_scalar(content))
        return result_list, i
    result_map: dict[str, Any] = {}
    while i < len(items) and items[i][0] == indent and not items[i][1].startswith("-"):
        key, _, val = items[i][1].partition(":")
        key, val = key.strip(), val.strip()
        i += 1
        if not val:
            if i < len(items) and items[i][0] > indent:
                nested, i = _parse_block(items, i, items[i][0])
                result_map[key] = nested
            else:
                result_map[key] = None
        else:
            result_map[key] = _scalar(val)
    return result_map, i


def parse_yaml_subset(text: str) -> Any:
    """Parse the supported YAML subset; raises ``ValueError`` on bad input."""
    items: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        if "\t" in line:
            raise ValueError("tabs are not allowed for indentation")
        indent = len(line) - len(line.lstrip(" "))
        items.append((indent, line.strip()))
    if not items:
        return {}
    value, _ = _parse_block(items, 0, items[0][0])
    return value


# ---------------------------------------------------------------------------
# Macro storage + registry loading
# ---------------------------------------------------------------------------


def _store(data_dir: Path) -> SQLiteKVStore:
    return SQLiteKVStore(data_dir / _STORE_FILE)


def _macro_names(store: SQLiteKVStore) -> list[str]:
    raw = store.get(_INDEX_KEY)
    if not raw:
        return []
    return cast("list[str]", json.loads(raw))


def _load_registry() -> Any:
    """Build a skill registry lazily (inside handle, never at import time).

    Prefers ``skills.discovery.build_skill_registry`` when that module
    exists; otherwise falls back to scanning the ``skills`` package for
    modules exposing a ``SKILLS`` list. Lazy so this module never couples
    to other skill groups at import time.
    """
    from skills.registry import SkillRegistry

    try:
        from skills.discovery import build_skill_registry

        registry = build_skill_registry()
        if isinstance(registry, SkillRegistry):
            return registry
    except ImportError:
        pass
    import importlib
    import pkgutil
    from types import ModuleType

    import skills as skills_pkg

    def _try_import(dotted: str) -> ModuleType | None:
        try:
            return importlib.import_module(dotted)
        except Exception:
            return None

    registry = SkillRegistry()
    seen: set[str] = set()
    for mod_info in sorted(pkgutil.iter_modules(skills_pkg.__path__), key=lambda m: m.name):
        if mod_info.name in ("base", "registry", "discovery"):
            continue
        module = _try_import(f"skills.{mod_info.name}")
        if module is None:
            continue
        found = getattr(module, "SKILLS", None)
        if not isinstance(found, list):
            continue
        for skill in found:
            name = getattr(skill, "name", "")
            if name and name not in seen:
                seen.add(name)
                try:
                    registry.register(skill)
                except ValueError:
                    continue
    # Also scan this group (skills.advanced.*) for SKILLS lists.
    try:
        import skills.advanced as advanced_pkg

        for mod_info in sorted(pkgutil.iter_modules(advanced_pkg.__path__), key=lambda m: m.name):
            module = _try_import(f"skills.advanced.{mod_info.name}")
            if module is None:
                continue
            found = getattr(module, "SKILLS", None)
            if not isinstance(found, list):
                continue
            for skill in found:
                name = getattr(skill, "name", "")
                if name and name not in seen:
                    seen.add(name)
                    try:
                        registry.register(skill)
                    except ValueError:
                        continue
    except ImportError:
        pass
    return registry


def _parse_definition(body: str) -> dict[str, Any]:
    """Parse a macro body as YAML-subset, falling back to JSON."""
    data: Any = None
    try:
        data = parse_yaml_subset(body)
    except ValueError:
        data = None
    if not isinstance(data, dict) or "steps" not in data:
        try:
            data = cast("dict[str, Any]", json.loads(body))
        except (json.JSONDecodeError, ValueError) as exc:
            raise SkillError(
                "macro body must be the YAML subset (nested maps, '- ' lists) or JSON"
            ) from exc
    if not isinstance(data, dict):
        raise SkillError("macro body must be a mapping with a 'steps' list")
    return data


def _validate_steps(data: dict[str, Any]) -> list[dict[str, str]]:
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise SkillError("macro needs a non-empty 'steps' list")
    if len(raw_steps) > _MAX_STEPS:
        raise SkillError(f"macro limited to {_MAX_STEPS} steps")
    steps: list[dict[str, str]] = []
    for i, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            raise SkillError(f"step {i} must be a mapping with 'skill' and 'message'")
        skill_name = step.get("skill")
        message = step.get("message")
        if not isinstance(skill_name, str) or not skill_name:
            raise SkillError(f"step {i} needs a 'skill' name")
        if not isinstance(message, str):
            raise SkillError(f"step {i} needs a 'message' string")
        if skill_name == "workflow_macros":
            raise SkillError("macros cannot invoke themselves (cycle guard)")
        steps.append({"skill": skill_name, "message": message})
    return steps


class WorkflowMacrosSkill(Skill):
    """Defines, lists, and runs multi-skill workflow macros."""

    name = "workflow_macros"
    description = (
        "Workflow macros: 'define <name>' + YAML/JSON steps, "
        "'run <name>' executes each step's skill in order, 'list' shows macros."
    )
    intents = ("macro.define", "macro.run", "macro.list")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        message = context.message.strip()
        lowered = message.lower()
        if lowered == "list" or lowered.startswith("list"):
            return self._list(data_dir)
        if lowered.startswith("run "):
            name = message.split(None, 1)[1].strip()
            return await self._run(context, data_dir, name)
        if lowered.startswith("define "):
            first, _, body = message.partition("\n")
            name = first.split(None, 1)[1].strip()
            return self._define(data_dir, name, body)
        return (
            "workflow_macros: 'define <name>\\n<yaml>' to define, "
            "'run <name>' to execute, 'list' to show macros."
        )

    def _define(self, data_dir: Path, name: str, body: str) -> str:
        if not _NAME_RE.match(name):
            return "macro name must match [A-Za-z0-9_-]{1,64}"
        if not body.strip():
            return "usage: define <name>\\n<yaml or json with a 'steps' list>"
        try:
            data = _parse_definition(body)
            steps = _validate_steps(data)
        except SkillError as exc:
            return f"invalid macro: {exc}"
        store = _store(data_dir)
        store.put(f"macro:{name}", json.dumps({"name": name, "steps": steps}))
        names = _macro_names(store)
        if name not in names:
            names.append(name)
            store.put(_INDEX_KEY, json.dumps(sorted(names)))
        return f"macro '{name}' defined with {len(steps)} steps."

    def _list(self, data_dir: Path) -> str:
        store = _store(data_dir)
        names = _macro_names(store)
        if not names:
            return "no macros defined — use 'define <name>'."
        lines = [f"macros ({len(names)}):"]
        for name in names:
            raw = store.get(f"macro:{name}")
            if not raw:
                continue
            macro = cast("dict[str, Any]", json.loads(raw))
            steps = cast("list[dict[str, str]]", macro.get("steps", []))
            step_names = ", ".join(s["skill"] for s in steps)
            lines.append(f"- {name}: {len(steps)} steps [{step_names}]")
        return "\n".join(lines)

    async def _run(self, context: SkillContext, data_dir: Path, name: str) -> str:
        store = _store(data_dir)
        raw = store.get(f"macro:{name}")
        if not raw:
            return f"unknown macro '{name}' — use 'list' to see defined macros."
        macro = cast("dict[str, Any]", json.loads(raw))
        steps = cast("list[dict[str, str]]", macro.get("steps", []))
        registry = _load_registry()
        outputs: list[dict[str, str]] = []
        for step in steps:
            try:
                skill = registry.get(step["skill"])
            except Exception as exc:
                outputs.append({"skill": step["skill"], "output": f"error: unknown skill ({exc})"})
                break
            sub = replace(context, message=step["message"])
            try:
                output = await skill.handle(sub)
            except Exception as exc:
                output = f"error: {exc}"
                outputs.append({"skill": step["skill"], "output": output})
                break
            outputs.append({"skill": step["skill"], "output": output})
        self._log_run(store, name, outputs)
        lines = [f"macro '{name}' ran {len(outputs)}/{len(steps)} steps:"]
        for i, out in enumerate(outputs, 1):
            snippet = out["output"].replace("\n", " ")[:200]
            lines.append(f"{i}. [{out['skill']}] {snippet}")
        return "\n".join(lines)

    def _log_run(self, store: SQLiteKVStore, name: str, outputs: list[dict[str, str]]) -> None:
        raw = store.get(_RUNS_KEY)
        runs: list[dict[str, Any]] = cast("list[dict[str, Any]]", json.loads(raw)) if raw else []
        runs.append(
            {
                "macro": name,
                "at": datetime.now(UTC).isoformat(),
                "outputs": outputs,
            }
        )
        store.put(_RUNS_KEY, json.dumps(runs[-_MAX_RUNS_KEPT:]))


SKILLS: list[Skill] = [WorkflowMacrosSkill()]
