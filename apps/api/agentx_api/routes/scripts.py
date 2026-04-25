from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, constr

from agentx_api.auth import current_user_id
from agentx_api.config import config

router = APIRouter(tags=["scripts"])

MAX_SCRIPT_CONTENT_CHARS = 250_000


class ScriptRecord(BaseModel):
    id: str
    title: str
    language: str = "text"
    content: str
    model_provider: str | None = None
    model_name: str | None = None
    source_thread_id: str | None = None
    source_message_id: str | None = None
    created_at: float
    updated_at: float
    tags: list[str] = Field(default_factory=list)


class StoredScript(ScriptRecord):
    owner_id: str


class ScriptCreate(BaseModel):
    title: constr(strip_whitespace=True, min_length=1, max_length=140)
    language: str = "text"
    content: constr(min_length=1, max_length=MAX_SCRIPT_CONTENT_CHARS)
    model_provider: str | None = None
    model_name: str | None = None
    source_thread_id: str | None = None
    source_message_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class ScriptUpdate(BaseModel):
    title: constr(strip_whitespace=True, min_length=1, max_length=140) | None = None
    language: str | None = None
    content: constr(min_length=1, max_length=MAX_SCRIPT_CONTENT_CHARS) | None = None
    tags: list[str] | None = None


class DeleteResponse(BaseModel):
    ok: bool = True


def _owner_dir(owner_id: str) -> Path:
    digest = hashlib.sha256((owner_id or "").encode("utf-8")).hexdigest()[:24]
    path = config.scripts_dir / digest
    path.mkdir(parents=True, exist_ok=True)
    return path


def _script_path(script_id: str, *, owner_id: str) -> Path:
    return _owner_dir(owner_id) / f"{script_id}.json"


def _load_script(path: Path) -> StoredScript:
    if not path.exists():
        raise HTTPException(status_code=404, detail="Script not found")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return StoredScript(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Script data corrupted")


def _write_script(script: ScriptRecord, *, owner_id: str) -> None:
    path = _script_path(script.id, owner_id=owner_id)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        payload = StoredScript(owner_id=owner_id, **script.model_dump())
        json.dump(payload.model_dump(), fh, indent=2)
    tmp.replace(path)


def _clean_language(value: str | None) -> str:
    cleaned = (value or "text").strip().lower()
    return cleaned[:40] or "text"


def _clean_tags(tags: list[str] | None) -> list[str]:
    out: list[str] = []
    for tag in tags or []:
        t = str(tag or "").strip().lower()
        if t and t not in out:
            out.append(t[:40])
    return out[:12]


def _find_existing_by_source(owner_id: str, source_message_id: str | None) -> ScriptRecord | None:
    if not source_message_id:
        return None
    for path in _owner_dir(owner_id).glob("*.json"):
        try:
            stored = _load_script(path)
            if stored.owner_id == owner_id and stored.source_message_id == source_message_id:
                return ScriptRecord(**stored.model_dump(exclude={"owner_id"}))
        except Exception:
            continue
    return None


@router.get("/scripts", response_model=List[ScriptRecord])
def list_scripts(
    http: Request,
    query: str | None = Query(default=None),
    language: str | None = Query(default=None),
    model: str | None = Query(default=None),
    thread_id: str | None = Query(default=None),
) -> List[ScriptRecord]:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    q = (query or "").strip().lower()
    lang = (language or "").strip().lower()
    model_q = (model or "").strip().lower()
    scripts: list[ScriptRecord] = []
    for path in _owner_dir(owner_id).glob("*.json"):
        try:
            stored = _load_script(path)
            if stored.owner_id != owner_id:
                continue
            script = ScriptRecord(**stored.model_dump(exclude={"owner_id"}))
        except Exception:
            continue
        haystack = "\n".join([script.title, script.language, script.content, script.model_provider or "", script.model_name or ""]).lower()
        if q and q not in haystack:
            continue
        if lang and script.language.lower() != lang:
            continue
        if model_q and model_q not in f"{script.model_provider or ''}:{script.model_name or ''}".lower():
            continue
        if thread_id and script.source_thread_id != thread_id:
            continue
        scripts.append(script)
    return sorted(scripts, key=lambda item: item.updated_at, reverse=True)


@router.post("/scripts", response_model=ScriptRecord)
def create_script(payload: ScriptCreate, http: Request) -> ScriptRecord:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    now = time.time()
    existing = _find_existing_by_source(owner_id, payload.source_message_id)
    script = existing or ScriptRecord(
        id=uuid.uuid4().hex,
        title=payload.title,
        language=_clean_language(payload.language),
        content=payload.content,
        model_provider=(payload.model_provider or "").strip() or None,
        model_name=(payload.model_name or "").strip() or None,
        source_thread_id=(payload.source_thread_id or "").strip() or None,
        source_message_id=(payload.source_message_id or "").strip() or None,
        created_at=now,
        updated_at=now,
        tags=_clean_tags(payload.tags),
    )
    if existing:
        script.title = payload.title
        script.language = _clean_language(payload.language)
        script.content = payload.content
        script.model_provider = (payload.model_provider or "").strip() or script.model_provider
        script.model_name = (payload.model_name or "").strip() or script.model_name
        script.source_thread_id = (payload.source_thread_id or "").strip() or script.source_thread_id
        script.tags = _clean_tags(payload.tags) or script.tags
        script.updated_at = now
    _write_script(script, owner_id=owner_id)
    return script


@router.get("/scripts/{script_id}", response_model=ScriptRecord)
def get_script(script_id: str, http: Request) -> ScriptRecord:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    stored = _load_script(_script_path(script_id, owner_id=owner_id))
    if stored.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Script not found")
    return ScriptRecord(**stored.model_dump(exclude={"owner_id"}))


@router.patch("/scripts/{script_id}", response_model=ScriptRecord)
def update_script(script_id: str, payload: ScriptUpdate, http: Request) -> ScriptRecord:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    stored = _load_script(_script_path(script_id, owner_id=owner_id))
    if stored.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Script not found")
    script = ScriptRecord(**stored.model_dump(exclude={"owner_id"}))
    if payload.title is not None:
        script.title = payload.title
    if payload.language is not None:
        script.language = _clean_language(payload.language)
    if payload.content is not None:
        script.content = payload.content
    if payload.tags is not None:
        script.tags = _clean_tags(payload.tags)
    script.updated_at = time.time()
    _write_script(script, owner_id=owner_id)
    return script


@router.delete("/scripts/{script_id}", response_model=DeleteResponse)
def delete_script(script_id: str, http: Request) -> DeleteResponse:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    path = _script_path(script_id, owner_id=owner_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Script not found")
    path.unlink()
    return DeleteResponse(ok=True)
