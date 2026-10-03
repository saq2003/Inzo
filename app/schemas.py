"""Pydantic request/response schemas for the INZO API (all endpoints)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Health / status
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: str = "INZO"
    version: str = "0.1.0"


class StatusResponse(BaseModel):
    app: str
    version: str
    env: str
    uptime_seconds: float
    llm_provider: str
    tools: int
    skills: int
    memory_items: int
    background_tasks: int


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    actor: str = Field(default="user", max_length=64)
    session_id: str | None = Field(default=None, max_length=64)


class ToolCallRecord(BaseModel):
    tool: str
    ok: bool
    output: str
    error: str | None = None


class ChatResponse(BaseModel):
    reply: str
    intent: str
    plan_steps: list[str]
    tool_calls: list[ToolCallRecord]
    verified: bool
    issues: list[str] = []


# --------------------------------------------------------------------------- #
# Voice
# --------------------------------------------------------------------------- #
class VoiceProcessRequest(BaseModel):
    """Submit audio (base64 PCM) or a pre-transcribed text for pipeline testing."""

    audio_base64: str | None = None
    transcript: str | None = None
    confidence: float | None = None
    actor: str = Field(default="user", max_length=64)


class VoiceProcessResponse(BaseModel):
    transcript: str
    confidence: float
    needs_repetition: bool
    reply: str
    audio_base64: str = ""


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #
class MemoryStoreRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    kind: Literal["fact", "note", "conversation"] = "note"
    tags: list[str] = Field(default_factory=list)


class MemoryStoreResponse(BaseModel):
    id: str
    kind: str


class MemoryRecallRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=50)


class MemoryHit(BaseModel):
    id: str
    text: str
    score: float
    source: str


class MemoryRecallResponse(BaseModel):
    hits: list[MemoryHit]


class MemoryStatsResponse(BaseModel):
    short_term_items: int
    long_term_items: int
    vector_items: int


# --------------------------------------------------------------------------- #
# Tasks (background)
# --------------------------------------------------------------------------- #
class TaskSubmitRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: Literal["index_documents", "consolidate_memory", "research"] = "index_documents"
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskInfo(BaseModel):
    id: str
    name: str
    status: str
    result: str | None = None
    error: str | None = None


# --------------------------------------------------------------------------- #
# Skills
# --------------------------------------------------------------------------- #
class SkillInfo(BaseModel):
    name: str
    description: str
    intents: list[str]
    enabled: bool


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
class ToolParameterSchema(BaseModel):
    name: str
    type: str
    description: str
    required: bool


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: list[ToolParameterSchema]
    required_capabilities: list[str]


class ToolExecuteRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default="user", max_length=64)


class ToolExecuteResponse(BaseModel):
    ok: bool
    output: str
    error: str | None = None


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
class SettingsView(BaseModel):
    app_name: str
    env: str
    log_level: str
    data_dir: str
    host: str
    port: int
    llm_provider: str
    stt_confidence_threshold: float


class SettingsUpdate(BaseModel):
    """Only non-secret, runtime-safe settings may be changed via the API."""

    log_level: str | None = Field(default=None, max_length=16)
    stt_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
