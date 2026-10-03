"""Plugin hot-reload via importlib (no registry mutation here).

``reload <dotted.module>`` re-imports and reloads a ``skills.*`` module
with :func:`importlib.reload` and reports its docstring plus the names
in its ``SKILLS`` list. ``list`` enumerates modules under ``skills/``
with their ``SKILLS`` counts using ``pkgutil`` (modules are imported
lazily, one at a time, failures reported as n/a).

This skill deliberately does NOT mutate any registry: reloading only
refreshes the module object in ``sys.modules``. Long-running daemons
pick up the new code the next time they call
``skills.discovery.build_skill_registry()`` (or an equivalent fresh
scan), because that builder imports modules anew instead of holding
stale references. ``skills.base`` and ``skills.registry`` are refused
because reloading them would fork class identity for every live skill.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from skills.base import Skill, SkillContext

_PROTECTED = ("skills.base", "skills.registry")


def _skill_names(module: ModuleType) -> list[str]:
    found = getattr(module, "SKILLS", None)
    if not isinstance(found, list):
        return []
    names: list[str] = []
    for skill in found:
        name = getattr(skill, "name", "")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _reload_module(dotted: str) -> str:
    if not dotted.startswith("skills."):
        return "refusing: only skills.* modules can be reloaded."
    if dotted in _PROTECTED:
        return (
            f"refusing: {dotted} is protected (reloading it would fork "
            "class identity for live skills)."
        )
    try:
        module = importlib.import_module(dotted)
    except ImportError as exc:
        return f"cannot import {dotted}: {exc}"
    try:
        reloaded = importlib.reload(module)
    except Exception as exc:
        return f"reload of {dotted} failed: {exc}"
    doc = (reloaded.__doc__ or "").strip().splitlines()
    first_line = doc[0].strip() if doc else "(no docstring)"
    names = _skill_names(reloaded)
    skills_part = ", ".join(names) if names else "no SKILLS"
    return (
        f"reloaded {dotted}\n"
        f"doc: {first_line}\n"
        f"SKILLS ({len(names)}): {skills_part}\n"
        "note: daemons pick this up on their next build_skill_registry() scan."
    )


def _list_plugins() -> str:
    import skills as skills_pkg

    lines = ["skill plugin modules:"]
    for mod_info in sorted(pkgutil.iter_modules(skills_pkg.__path__), key=lambda m: m.name):
        dotted = f"skills.{mod_info.name}"
        try:
            module = importlib.import_module(dotted)
        except Exception as exc:
            lines.append(f"- {dotted}: import failed ({exc})")
            continue
        names = _skill_names(module)
        detail = ", ".join(names) if names else "no SKILLS list"
        lines.append(f"- {dotted}: {len(names)} skill(s) [{detail}]")
    lines.append(
        "note: counts come from each module's SKILLS list; "
        "daemons re-discover via build_skill_registry()."
    )
    return "\n".join(lines)


class PluginHotreloadSkill(Skill):
    """Hot-reloads skill plugin modules via importlib."""

    name = "plugin_hotreload"
    description = (
        "Hot-reloads skill plugins: 'reload skills.<module>' refreshes the "
        "module in sys.modules; 'list' shows skills.* modules and SKILLS counts."
    )
    intents = ("plugin.reload", "plugin.list")
    required_capabilities = ("skills.execute", "system.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        message = context.message.strip()
        lowered = message.lower()
        if lowered == "list" or lowered.startswith("list"):
            return _list_plugins()
        if lowered.startswith("reload "):
            dotted = message.split(None, 1)[1].strip()
            return _reload_module(dotted)
        return "plugin_hotreload: 'reload skills.<module>' or 'list'."


SKILLS: list[Skill] = [PluginHotreloadSkill()]
