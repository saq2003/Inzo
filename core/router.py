"""Model router: selects an LLM adapter per task kind (Rule 3, Rule 4).

Providers are registered by name; nothing about a specific vendor is
hard-coded. The default ``local-echo`` adapter is deterministic, offline,
and free (Rule 15).
"""

from __future__ import annotations

import asyncio
import time

from app.logging_config import get_logger
from core.protocols import LLMAdapter, LLMResponse

logger = get_logger(__name__)


class EchoAdapter:
    """Deterministic local adapter: no network, no key, no cost.

    Used for development and as the safe fallback. Real adapters
    (local transformers runtimes, hosted APIs) register themselves here.
    """

    name = "local-echo"

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        timeout_s: float = 30.0,
    ) -> LLMResponse:
        started = time.monotonic()

        async def _work() -> str:
            await asyncio.sleep(0)  # stay on the event loop; real adapters do I/O
            snippet = prompt.strip().replace("\n", " ")[:400]
            return f"[local-echo] processed request: {snippet}"

        text = await asyncio.wait_for(_work(), timeout=timeout_s)
        return LLMResponse(
            text=text[:max_tokens],
            model=self.name,
            latency_s=time.monotonic() - started,
        )


class UnconfiguredAdapter:
    """Placeholder for a named provider that has no credentials configured.

    Registering a provider name without secrets keeps the router honest:
    it fails loudly instead of silently falling back (Rule 5).
    """

    def __init__(self, name: str, hint: str) -> None:
        self.name = name
        self._hint = hint

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
        timeout_s: float = 30.0,
    ) -> LLMResponse:
        raise RuntimeError(f"LLM provider '{self.name}' is not configured: {self._hint}")


class ModelRouter:
    """Maps task kinds to registered adapters."""

    def __init__(self, default: str = "local-echo") -> None:
        self._adapters: dict[str, LLMAdapter] = {}
        self._routes: dict[str, str] = {}
        self._default = default
        self.register(EchoAdapter())

    def register(self, adapter: LLMAdapter) -> None:
        """Register an adapter under its ``name``."""
        self._adapters[adapter.name] = adapter
        logger.info("llm adapter registered", extra={"adapter": adapter.name})

    def route_kind(self, kind: str, adapter_name: str) -> None:
        """Pin a task kind (e.g. ``"chat"``) to a registered adapter."""
        if adapter_name not in self._adapters:
            raise KeyError(f"unknown adapter: {adapter_name}")
        self._routes[kind] = adapter_name

    def route(self, kind: str) -> LLMAdapter:
        """Return the adapter for ``kind``; fall back to the default."""
        name = self._routes.get(kind, self._default)
        adapter = self._adapters.get(name)
        if adapter is None:
            logger.warning("adapter missing, using default", extra={"wanted": name})
            adapter = self._adapters[self._default]
        return adapter

    def list_adapters(self) -> list[str]:
        """Return registered adapter names."""
        return sorted(self._adapters)
