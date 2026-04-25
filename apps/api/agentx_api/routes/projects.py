from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, constr

from agentx_api.auth import current_user_id
from agentx_api.config import config

router = APIRouter(tags=["projects"])


class Project(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: float
    updated_at: float


class StoredProject(Project):
    owner_id: str


class ProjectCreate(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=80)
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=80) | None = None
    description: str | None = None


class DeleteResponse(BaseModel):
    ok: bool = True


def _owner_dir(owner_id: str) -> Path:
    digest = hashlib.sha256((owner_id or "").encode("utf-8")).hexdigest()[:24]
    path = config.projects_dir / digest
    path.mkdir(parents=True, exist_ok=True)
    return path


def _project_path(project_id: str, *, owner_id: str) -> Path:
    return _owner_dir(owner_id) / f"{project_id}.json"


def _load_project(path: Path) -> StoredProject:
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return StoredProject(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Project data corrupted")


def _write_project(project: Project, *, owner_id: str) -> None:
    path = _project_path(project.id, owner_id=owner_id)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        payload = StoredProject(owner_id=owner_id, **project.model_dump())
        json.dump(payload.model_dump(), fh, indent=2)
    tmp.replace(path)


@router.get("/projects", response_model=List[Project])
def list_projects(http: Request) -> List[Project]:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    projects: list[Project] = []
    for path in _owner_dir(owner_id).glob("*.json"):
        try:
            stored = _load_project(path)
            if stored.owner_id != owner_id:
                continue
            projects.append(Project(**stored.model_dump(exclude={"owner_id"})))
        except Exception:
            continue
    return sorted(projects, key=lambda p: p.updated_at, reverse=True)


@router.post("/projects", response_model=Project)
def create_project(payload: ProjectCreate, http: Request) -> Project:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    now = time.time()
    project = Project(
        id=uuid.uuid4().hex,
        name=payload.name,
        description=(payload.description or "").strip(),
        created_at=now,
        updated_at=now,
    )
    _write_project(project, owner_id=owner_id)
    return project


@router.patch("/projects/{project_id}", response_model=Project)
def update_project(project_id: str, payload: ProjectUpdate, http: Request) -> Project:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    stored = _load_project(_project_path(project_id, owner_id=owner_id))
    if stored.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Project not found")
    project = Project(**stored.model_dump(exclude={"owner_id"}))
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description.strip()
    project.updated_at = time.time()
    _write_project(project, owner_id=owner_id)
    return project


@router.delete("/projects/{project_id}", response_model=DeleteResponse)
def delete_project(project_id: str, http: Request) -> DeleteResponse:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    path = _project_path(project_id, owner_id=owner_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    path.unlink()
    return DeleteResponse(ok=True)
