from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import List, Literal

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field, constr

from sol_api.auth import current_user_id
from sol_api.config import config
from sol_api.rag.session import session_tracker

router = APIRouter(tags=["threads"])


class ThreadSummary(BaseModel):
    id: str
    title: str
    updated_at: float


class ThreadCreate(BaseModel):
    title: str | None = None


class MessagePayload(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class TitlePayload(BaseModel):
    title: constr(strip_whitespace=True, min_length=1, max_length=config.thread_title_max)


class Message(BaseModel):
    id: str
    role: str
    content: str
    ts: float


class Thread(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    messages: List[Message] = Field(default_factory=list)


class StoredThread(Thread):
    owner_id: str


class DeleteResponse(BaseModel):
    ok: bool = True


def _owner_dir(owner_id: str) -> Path:
    digest = hashlib.sha256((owner_id or "").encode("utf-8")).hexdigest()[:24]
    path = config.threads_dir / digest
    path.mkdir(parents=True, exist_ok=True)
    return path


def _thread_path(thread_id: str, *, owner_id: str) -> Path:
    return _owner_dir(owner_id) / f"{thread_id}.json"


def _legacy_thread_path(thread_id: str) -> Path:
    return config.threads_dir / f"{thread_id}.json"


def _load_stored_thread(path: Path) -> StoredThread:
    if not path.exists():
        raise HTTPException(status_code=404, detail="Thread not found")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return StoredThread(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Thread data corrupted")

 
def _write_thread(thread: Thread, *, owner_id: str) -> None:
    path = _thread_path(thread.id, owner_id=owner_id)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        payload = StoredThread(owner_id=owner_id, **thread.model_dump())
        json.dump(payload.model_dump(), fh, indent=2)
    tmp.replace(path)


def _legacy_migration_allowed(owner_id: str) -> bool:
    return len(getattr(config, "auth_users", {}) or {}) == 1 and owner_id in getattr(config, "auth_users", {})


def _maybe_migrate_legacy_thread(thread_id: str, *, owner_id: str) -> None:
    target = _thread_path(thread_id, owner_id=owner_id)
    if target.exists() or not _legacy_migration_allowed(owner_id):
        return
    legacy = _legacy_thread_path(thread_id)
    if not legacy.exists():
        return
    try:
        with legacy.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        thread = Thread(**data)
    except Exception:
        return
    _write_thread(thread, owner_id=owner_id)
    try:
        legacy.unlink()
    except Exception:
        pass


def _read_thread(thread_id: str, *, owner_id: str | None = None) -> Thread:
    if owner_id is None:
        path = _legacy_thread_path(thread_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Thread not found")
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return Thread(**data)
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Thread data corrupted")
    _maybe_migrate_legacy_thread(thread_id, owner_id=owner_id)
    path = _thread_path(thread_id, owner_id=owner_id)
    stored = _load_stored_thread(path)
    if stored.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Thread not found")
    return Thread(**stored.model_dump(exclude={"owner_id"}))


def ensure_thread_owner(thread_id: str, *, owner_id: str) -> Thread:
    return _read_thread(thread_id, owner_id=owner_id)


@router.get("/threads", response_model=List[ThreadSummary])
def list_threads(http: Request) -> List[ThreadSummary]:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if _legacy_migration_allowed(owner_id):
        for path in config.threads_dir.glob("*.json"):
            _maybe_migrate_legacy_thread(path.stem, owner_id=owner_id)
    summaries: List[ThreadSummary] = []
    for path in _owner_dir(owner_id).glob("*.json"):
        try:
            thread = _load_stored_thread(path)
            if thread.owner_id != owner_id:
                continue
            summaries.append(ThreadSummary(id=thread.id, title=thread.title, updated_at=thread.updated_at))
        except Exception:
            continue
    return sorted(summaries, key=lambda t: t.updated_at, reverse=True)


@router.post("/threads", response_model=Thread)
def create_thread(body: ThreadCreate, http: Request) -> Thread:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    now = time.time()
    thread = Thread(
        id=uuid.uuid4().hex,
        title=body.title or "New thread",
        created_at=now,
        updated_at=now,
        messages=[],
    )
    _write_thread(thread, owner_id=owner_id)
    return thread


@router.get("/threads/{thread_id}", response_model=Thread)
def get_thread(thread_id: str, http: Request) -> Thread:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return _read_thread(thread_id, owner_id=owner_id)


@router.post("/threads/{thread_id}/messages", response_model=Thread)
def append_message(thread_id: str, payload: MessagePayload, http: Request) -> Thread:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    session_tracker.set_active_thread(owner_id, thread_id)

    thread = _read_thread(thread_id, owner_id=owner_id)
    now = time.time()
    message = Message(id=uuid.uuid4().hex, role=payload.role, content=payload.content, ts=now)
    thread.messages.append(message)
    thread.updated_at = now
    _write_thread(thread, owner_id=owner_id)
    return thread


@router.post("/threads/{thread_id}/title", response_model=Thread)
def update_thread_title(thread_id: str, http: Request, payload: TitlePayload = Body(...)) -> Thread:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    thread = _read_thread(thread_id, owner_id=owner_id)
    if payload.title == thread.title:
        return thread
    thread.title = payload.title
    thread.updated_at = time.time()
    _write_thread(thread, owner_id=owner_id)
    return thread


@router.delete("/threads/{thread_id}", response_model=DeleteResponse)
def delete_thread(thread_id: str, http: Request) -> DeleteResponse:
    owner_id = current_user_id(http)
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    _maybe_migrate_legacy_thread(thread_id, owner_id=owner_id)
    path = _thread_path(thread_id, owner_id=owner_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Thread not found")
    try:
        path.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete thread: {e}")
    return DeleteResponse(ok=True)
