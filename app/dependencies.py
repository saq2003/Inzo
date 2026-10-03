"""Dependency wiring: builds and caches INZO singletons.

All components are constructed here with explicit dependencies, so the
agent, registries, memory, and workers stay consistent across the API.
``reset_wiring()`` exists for tests.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.logging_config import get_logger
from core.agent import Agent
from core.planner import Planner
from core.router import ModelRouter
from core.verifier import Verifier
from memory.manager import MemoryManager
from security.permissions import PermissionManager
from skills.builtin import builtin_skills
from skills.registry import SkillRegistry
from storage.sqlite_store import SQLiteDocumentStore
from tools.builtin import builtin_tools
from tools.registry import ToolRegistry
from voice.pipeline import VoicePipeline, VoicePipelineConfig
from workers.queue import InProcessQueue
from workers.scheduler import Scheduler

logger = get_logger(__name__)

_singletons: dict[str, Any] = {}

DEFAULT_CAPABILITIES = (
    "tools.execute",
    "tool.calculator",
    "tool.time",
    "tool.note",
    "tool.finance",
    "tool.read_file",
    "skills.execute",
    "memory.write",
    "memory.read",
)

DEFAULT_ACTORS = ("user", "inzo-agent")


def reset_wiring() -> None:
    """Drop all cached singletons (used by tests)."""
    _singletons.clear()


def get_settings() -> Settings:
    settings = _singletons.get("settings")
    if settings is None:
        settings = Settings.from_env()
        settings.ensure_data_dir()
        _singletons["settings"] = settings
    return settings


def get_permission_manager() -> PermissionManager:
    pm = _singletons.get("permissions")
    if pm is None:
        pm = PermissionManager()
        for actor in DEFAULT_ACTORS:
            for capability in DEFAULT_CAPABILITIES:
                pm.grant(actor, capability)
        _singletons["permissions"] = pm
    return pm


def get_memory_manager() -> MemoryManager:
    manager = _singletons.get("memory")
    if manager is None:
        settings = get_settings()
        store = SQLiteDocumentStore(settings.data_dir / "memory.db")
        manager = MemoryManager(store)
        _singletons["memory"] = manager
    return manager


def get_tool_registry() -> ToolRegistry:
    registry = _singletons.get("tools")
    if registry is None:
        registry = ToolRegistry(get_permission_manager())
        memory = get_memory_manager()

        async def _note_saver(text: str) -> str | None:
            return await memory.remember("user", text, durable=True, kind="note")

        for tool in builtin_tools(
            root=get_settings().data_dir, note_saver=_note_saver
        ):
            registry.register(tool)
        _singletons["tools"] = registry
    return registry


def get_skill_registry() -> SkillRegistry:
    registry = _singletons.get("skills")
    if registry is None:
        registry = SkillRegistry()
        for skill in builtin_skills():
            registry.register(skill)
        _singletons["skills"] = registry
    return registry


def get_model_router() -> ModelRouter:
    router = _singletons.get("router")
    if router is None:
        router = ModelRouter()
        settings = get_settings()
        if settings.llm_provider != "local-echo":
            # Named providers without credentials fail loudly (Rule 5).
            from core.router import UnconfiguredAdapter

            router.register(
                UnconfiguredAdapter(
                    settings.llm_provider,
                    "set the provider's API key in the environment",
                )
            )
            router.route_kind("chat", settings.llm_provider)
        _singletons["router"] = router
    return router


def get_agent() -> Agent:
    agent = _singletons.get("agent")
    if agent is None:
        agent = Agent(
            router=get_model_router(),
            planner=Planner(),
            verifier=Verifier(),
            tools=get_tool_registry(),
            skills=get_skill_registry(),
            memory=get_memory_manager(),
            permissions=get_permission_manager(),
        )
        _singletons["agent"] = agent
    return agent


def get_voice_pipeline() -> VoicePipeline:
    pipeline = _singletons.get("voice")
    if pipeline is None:
        settings = get_settings()
        pipeline = VoicePipeline(
            config=VoicePipelineConfig(
                confidence_threshold=settings.stt_confidence_threshold
            )
        )
        _singletons["voice"] = pipeline
    return pipeline


def get_task_queue() -> InProcessQueue:
    queue = _singletons.get("queue")
    if queue is None:
        queue = InProcessQueue()
        _singletons["queue"] = queue
    return queue


def get_scheduler() -> Scheduler:
    scheduler = _singletons.get("scheduler")
    if scheduler is None:
        scheduler = Scheduler()
        _singletons["scheduler"] = scheduler
    return scheduler
