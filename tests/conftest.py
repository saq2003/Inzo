"""Shared fixtures: isolated settings/data dir and a fresh app per test."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import dependencies
from app.config import Settings
from app.main import create_app


@pytest.fixture()
def tmp_settings(tmp_path, monkeypatch):
    """Isolated settings pointing at a temp data dir; wiring reset after."""
    monkeypatch.setenv("INZO_DATA_DIR", str(tmp_path / "data"))
    dependencies.reset_wiring()
    settings = Settings.from_env()
    settings.ensure_data_dir()
    dependencies._singletons["settings"] = settings
    yield settings
    dependencies.reset_wiring()


@pytest.fixture()
def client(tmp_settings):
    """TestClient bound to a freshly wired app (isolated data dir)."""
    return TestClient(create_app())


@pytest.fixture()
def agent(tmp_settings):
    """Fully wired agent with isolated storage."""
    return dependencies.get_agent()


@pytest.fixture()
def memory(tmp_settings):
    """Isolated memory manager."""
    return dependencies.get_memory_manager()


@pytest.fixture()
def tool_registry(tmp_settings):
    """Isolated tool registry with builtin tools."""
    return dependencies.get_tool_registry()


@pytest.fixture()
def permissions(tmp_settings):
    """Isolated permission manager (default grants applied)."""
    return dependencies.get_permission_manager()
