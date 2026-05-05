from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agentx_api.validation_runner import ValidationError, discover_workspaces, preset_summary, read_history, read_patch_candidate_history, run_validation, validate_patch_candidate

router = APIRouter(tags=["validation"])


class ValidationCommandIn(BaseModel):
    name: str | None = None
    argv: list[str] | str
    cwd: str = "."
    timeout_s: int | None = None
    required: bool = True


class ValidationRunIn(BaseModel):
    workspace_path: str = Field(..., min_length=1)
    preset: str = "agentx_full"
    commands: list[ValidationCommandIn] | None = None


class PatchCandidateIn(BaseModel):
    workspace_path: str = Field(..., min_length=1)
    preset: str = "agentx_full"
    patch_text: str = Field(..., min_length=1)
    keep_worktree: bool = False
    repair_of_candidate_id: str | None = None


@router.get("/validation/presets")
def validation_presets() -> dict[str, Any]:
    return {"ok": True, "presets": preset_summary()}


@router.get("/validation/workspaces")
def validation_workspaces() -> dict[str, Any]:
    return {"ok": True, "workspaces": discover_workspaces()}


@router.post("/validation/run")
def validation_run(body: ValidationRunIn) -> dict[str, Any]:
    try:
        command_payload = [c.model_dump() for c in body.commands] if body.commands else None
        result = run_validation(body.workspace_path, body.preset, command_payload)
        return {"ok": result.ok, **asdict(result)}
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/validation/patch-candidate")
def validation_patch_candidate(body: PatchCandidateIn) -> dict[str, Any]:
    try:
        result = validate_patch_candidate(body.workspace_path, body.preset, body.patch_text, body.keep_worktree, body.repair_of_candidate_id)
        return {"ok": result.ok, **asdict(result)}
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/validation/history")
def validation_history(limit: int = Query(25, ge=1, le=100)) -> dict[str, Any]:
    return {"ok": True, "runs": read_history(limit=limit)}


@router.get("/validation/patch-candidates/history")
def validation_patch_candidate_history(limit: int = Query(25, ge=1, le=100)) -> dict[str, Any]:
    return {"ok": True, "candidates": read_patch_candidate_history(limit=limit)}
