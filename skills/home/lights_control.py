"""Light control skill (hardware-gated, real validation + scenes).

The ``LightHub`` Protocol is the plug-in point: a real implementation talks
to the home's light hub (Zigbee/bridge API, ...). The bundled ``StubHub``
raises ``NotConfigured`` so the skill fails honestly instead of faking
device state. Scene definitions, brightness validation (0-100), and the
light registry (``data_dir/"home.db"``) are fully real and local.
"""

from __future__ import annotations

import json
from typing import Protocol, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

REGISTRY_KEY = "lights:registry"

SCENES: dict[str, dict[str, tuple[bool, int]]] = {
    "movie": {"living_room": (True, 20)},
    "work": {"living_room": (True, 100)},
    "night": {"bedroom": (True, 10)},
}


class NotConfigured(Exception):
    """Raised by stub adapters when no real hardware backend is plugged in."""


class LightHub(Protocol):
    """Plug-in point: real light-hub implementation.

    Implementations live outside INZO (they need a hub/device library);
    attach one with ``LightsControlSkill.set_hub``.
    """

    def set_light(self, light_id: str, on: bool, brightness: int) -> None:
        """Set power and brightness (0-100) for one registered light."""
        ...


class StubHub:
    """Ships with the skill; always fails honestly."""

    def set_light(self, light_id: str, on: bool, brightness: int) -> None:
        raise NotConfigured(
            "no light hub configured — plug a LightHub implementation "
            "via LightsControlSkill.set_hub before controlling lights"
        )


class LightsControlSkill(Skill):
    """Validated light commands and scenes against a local light registry."""

    name = "lights_control"
    description = (
        "Controls smart lights via scenes and validated commands. "
        "Needs a LightHub adapter; without one it reports not-configured."
    )
    intents = ("lights.set", "lights.scene")
    required_capabilities = ("skills.execute", "memory.write", "hardware.access")
    background = True
    local_only = False
    adapter_note = (
        "Requires a real light hub. Implement the LightHub Protocol "
        "(set_light) and attach it via LightsControlSkill.set_hub; "
        "the bundled StubHub raises NotConfigured."
    )

    def __init__(self) -> None:
        self._hub: LightHub = StubHub()

    def set_hub(self, hub: LightHub) -> None:
        """Attach a real light-hub implementation."""
        self._hub = hub

    # -- registry ---------------------------------------------------------
    def _registry(self, context: SkillContext) -> dict[str, str]:
        store = SQLiteKVStore(require_data_dir(context) / "home.db")
        raw = store.get(REGISTRY_KEY)
        if not raw:
            return {}
        data = cast("dict[str, str]", json.loads(raw))
        return dict(data)

    def _save_registry(self, context: SkillContext, registry: dict[str, str]) -> None:
        store = SQLiteKVStore(require_data_dir(context) / "home.db")
        store.put(REGISTRY_KEY, json.dumps(registry))

    # -- command application ----------------------------------------------
    def _apply(self, light_id: str, on: bool, brightness: int) -> str:
        if not 0 <= brightness <= 100:
            return f"rejected: brightness {brightness} out of range 0-100"
        try:
            self._hub.set_light(light_id, on, brightness)
        except NotConfigured as exc:
            return f"not configured: {exc}"
        return f"{light_id}: {'on' if on else 'off'} brightness={brightness}"

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip().lower()
        registry = self._registry(context)

        if text.startswith("add light"):
            parts = context.message.strip().split()
            if len(parts) < 4:
                return "usage: add light <id> <display name>"
            light_id, name = parts[2], " ".join(parts[3:])
            registry[light_id] = name
            self._save_registry(context, registry)
            return f"registered light {light_id!r} ({name})"

        for scene_name, scene in SCENES.items():
            if text in (scene_name, f"scene {scene_name}", f"lights {scene_name}"):
                results: list[str] = []
                for light_id, (on, brightness) in scene.items():
                    if light_id not in registry:
                        results.append(f"{light_id}: unknown light (register it first)")
                        continue
                    results.append(self._apply(light_id, on, brightness))
                return f"scene {scene_name!r}:\n" + "\n".join(results)

        if text.startswith("set "):
            # "set <id> on|off [brightness <n>]"
            parts = text.split()
            if len(parts) < 3:
                return "usage: set <light_id> on|off [brightness <0-100>]"
            light_id = parts[1]
            if light_id not in registry:
                return f"unknown light {light_id!r} (registered: {sorted(registry)})"
            state = parts[2]
            if state not in ("on", "off"):
                return "usage: set <light_id> on|off [brightness <0-100>]"
            brightness = 100
            if "brightness" in parts:
                try:
                    brightness = int(parts[parts.index("brightness") + 1])
                except (IndexError, ValueError) as exc:
                    return f"invalid brightness: {exc}"
            return self._apply(light_id, state == "on", brightness)

        if text in ("list", "lights"):
            if not registry:
                return "no lights registered — 'add light <id> <name>' first"
            return "lights: " + ", ".join(f"{lid} ({nm})" for lid, nm in registry.items())

        scenes = ", ".join(sorted(SCENES))
        return (
            f"lights: scenes [{scenes}], commands 'set <id> on|off [brightness N]', "
            "'add light <id> <name>', 'list'. hub: "
            f"{'configured' if not isinstance(self._hub, StubHub) else 'NOT configured'}"
        )


SKILLS: list[Skill] = [LightsControlSkill()]
