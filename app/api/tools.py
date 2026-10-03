"""Tool endpoints: catalog and permission-checked execution."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import dependencies
from app.schemas import (
    ToolExecuteRequest,
    ToolExecuteResponse,
    ToolInfo,
    ToolParameterSchema,
)
from security.permissions import PermissionDenied
from tools.registry import UnknownToolError

router = APIRouter()


@router.get("/api/tools", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    """List the registered tool catalog."""
    registry = dependencies.get_tool_registry()
    return [
        ToolInfo(
            name=d.name,
            description=d.description,
            parameters=[
                ToolParameterSchema(
                    name=p.name,
                    type=p.type,
                    description=p.description,
                    required=p.required,
                )
                for p in d.parameters
            ],
            required_capabilities=list(d.required_capabilities),
        )
        for d in registry.definitions()
    ]


@router.post("/api/tools/{name}/execute", response_model=ToolExecuteResponse)
async def execute_tool(name: str, request: ToolExecuteRequest) -> ToolExecuteResponse:
    """Execute a tool with permission checks (Rule 13) and timeout (Rule 9)."""
    registry = dependencies.get_tool_registry()
    try:
        result = await registry.execute(
            name, actor=request.actor or "user", args=request.args
        )
    except UnknownToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ToolExecuteResponse(ok=result.ok, output=result.output, error=result.error)
