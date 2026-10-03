"""Model routing tests: adapter selection, fallback, loud misconfiguration."""

from __future__ import annotations

import asyncio

import pytest

from core.protocols import LLMResponse
from core.router import EchoAdapter, ModelRouter, UnconfiguredAdapter


def test_default_route_is_local_echo():
    router = ModelRouter()
    adapter = router.route("chat")
    assert adapter.name == "local-echo"
    assert "local-echo" in router.list_adapters()


def test_echo_adapter_generates_deterministically():
    adapter = EchoAdapter()
    first = asyncio.run(adapter.generate("hello world"))
    second = asyncio.run(adapter.generate("hello world"))
    assert isinstance(first, LLMResponse)
    assert first.model == "local-echo"
    assert first.text == second.text


def test_route_kind_pins_adapter():
    router = ModelRouter()

    class Custom:
        name = "custom-local"

        async def generate(self, prompt, *, system=None, max_tokens=512, timeout_s=30.0):
            return LLMResponse(text="custom", model=self.name)

    router.register(Custom())  # type: ignore[arg-type]
    router.route_kind("summarize", "custom-local")
    assert router.route("summarize").name == "custom-local"
    assert router.route("chat").name == "local-echo"  # others unaffected


def test_route_kind_unknown_adapter_raises():
    router = ModelRouter()
    with pytest.raises(KeyError):
        router.route_kind("chat", "nope")


def test_unconfigured_adapter_fails_loudly():
    adapter = UnconfiguredAdapter("fancy-cloud", "set FANCY_KEY")
    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(adapter.generate("hi"))
