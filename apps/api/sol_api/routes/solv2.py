from __future__ import annotations

import time
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi import Request
from pydantic import BaseModel, Field

from sol_api.auth import current_user_id
from sol_api.solv2_bridge import (
    SolV2Unavailable,
    get_agent_for_thread,
    get_handle,
    get_session_overrides_count,
    get_session_allowed_domains,
    session_allow_domain,
    session_clear,
    update_web_policy,
)
from sol_api.routes.threads import ensure_thread_owner

router = APIRouter(tags=["solv2"])


class CapabilitiesResponse(BaseModel):
    ok: bool = True
    ts: float
    mode: str
    supervised_only: bool
    allowed_roots: list[str]
    denied_substrings: list[str]
    denied_path_patterns: list[str]
    max_delete_count: int
    memory_enabled: bool
    memory_backend: str | None = None
    memory_db_path: str | None = None
    memory_events_path: str | None = None


@router.get("/capabilities", response_model=CapabilitiesResponse)
def capabilities() -> CapabilitiesResponse:
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    cfg = h.cfg
    return CapabilitiesResponse(
        ts=time.time(),
        mode=str(cfg.agent.mode),
        supervised_only=bool(getattr(cfg.agent, "refuse_unattended", True)),
        allowed_roots=[str(p) for p in (cfg.fs.allowed_roots or ())],
        denied_substrings=[str(s) for s in (cfg.fs.denied_substrings or ())],
        denied_path_patterns=[str(s) for s in (cfg.fs.denied_path_patterns or ())],
        max_delete_count=int(cfg.fs.max_delete_count),
        memory_enabled=bool(cfg.memory.enabled),
        memory_backend=str(cfg.memory.backend) if getattr(cfg, "memory", None) else None,
        memory_db_path=str(cfg.memory.db_path) if getattr(cfg, "memory", None) else None,
        memory_events_path=str(cfg.memory.events_path) if getattr(cfg, "memory", None) else None,
    )


class AuditTailResponse(BaseModel):
    ok: bool = True
    ts: float
    entries: list[dict[str, Any]]


@router.get("/audit", response_model=AuditTailResponse)
def audit(limit: int = Query(50, ge=1, le=500)) -> AuditTailResponse:
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        entries = h.ctx.audit.tail(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return AuditTailResponse(ts=time.time(), entries=entries)


class MemoryStatsResponse(BaseModel):
    ok: bool = True
    ts: float
    stats: dict[str, Any]


@router.get("/memory/stats", response_model=MemoryStatsResponse)
def memory_stats(reason: str = Query(..., min_length=1)) -> MemoryStatsResponse:
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        stats = h.agent.memory_stats(reason=reason)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return MemoryStatsResponse(ts=time.time(), stats=stats)


class MemoryPruneRequest(BaseModel):
    thread_id: str | None = None
    older_than_days: int = Field(..., ge=1, le=3650)
    reason: str = Field(..., min_length=1)
    dry_run: bool = True


class MemoryPruneResponse(BaseModel):
    ok: bool = True
    ts: float
    result: dict[str, Any]
    audit_tail: list[dict[str, Any]]


@router.post("/memory/prune", response_model=MemoryPruneResponse)
def memory_prune(body: MemoryPruneRequest, http: Request) -> MemoryPruneResponse:
    user_id = current_user_id(http)
    if body.thread_id and user_id:
        ensure_thread_owner(body.thread_id, owner_id=user_id)
    try:
        h, agent = get_agent_for_thread(body.thread_id, user=user_id)
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        result = agent.memory_prune(older_than_days=body.older_than_days, reason=body.reason, dry_run=bool(body.dry_run))
        tail = h.ctx.audit.tail(limit=50)
    except Exception as e:
        msg = str(e)
        if "Destructive action blocked" in msg:
            raise HTTPException(status_code=403, detail=msg)
        raise HTTPException(status_code=500, detail=msg)

    return MemoryPruneResponse(ts=time.time(), result=result, audit_tail=tail)

class IngestManifestSummary(BaseModel):
    id: str
    ts: float | None = None
    start_url: str | None = None
    pages_visited: int | None = None
    pages_ingested: int | None = None
    docs_ingested: int | None = None
    errors_count: int | None = None


class IngestManifestsResponse(BaseModel):
    ok: bool = True
    ts: float
    manifests: list[IngestManifestSummary]


def _manifests_dir(cfg) -> Path:
    return Path(cfg.paths.data_dir) / "ingest" / "manifests"


def _ingest_dir(cfg) -> Path:
    return Path(cfg.paths.data_dir) / "ingest"


def _iter_manifest_files(cfg) -> list[Path]:
    """Return all manifest JSON files from both legacy and new layouts.

    Legacy: data/ingest/manifests/<id>.json
    New:    data/ingest/<id>/manifest.json
    """

    out: list[Path] = []
    legacy = _manifests_dir(cfg)
    if legacy.exists():
        out.extend(sorted(legacy.glob("*.json")))

    base = _ingest_dir(cfg)
    if base.exists():
        for d in base.iterdir():
            if not d.is_dir():
                continue
            p = d / "manifest.json"
            if p.exists():
                out.append(p)
    return out


def _safe_manifest_id(value: str) -> str:
    v = (value or "").strip()
    if not v:
        raise HTTPException(status_code=400, detail="manifest id required")
    if not all(ch.isalnum() or ch in ("_", "-", ".") for ch in v):
        raise HTTPException(status_code=400, detail="invalid manifest id")
    return v


@router.get("/memory/ingest/manifests", response_model=IngestManifestsResponse)
def list_ingest_manifests(limit: int = Query(20, ge=1, le=100)) -> IngestManifestsResponse:
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    files = _iter_manifest_files(h.cfg)
    if not files:
        return IngestManifestsResponse(ts=time.time(), manifests=[])
    # Sort by embedded ts if present; fallback to mtime.
    def _sort_key(p: Path) -> float:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ts = data.get("ts")
            if isinstance(ts, (int, float)):
                return float(ts)
        except Exception:
            pass
        try:
            return float(p.stat().st_mtime)
        except Exception:
            return 0.0

    files = sorted(files, key=_sort_key, reverse=True)[: int(limit)]
    out: list[IngestManifestSummary] = []
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(
                IngestManifestSummary(
                    id=str(data.get("id") or (p.parent.name if p.name == "manifest.json" else p.stem)),
                    ts=float(data.get("ts")) if isinstance(data.get("ts"), (int, float)) else None,
                    start_url=str(data.get("start_url") or ""),
                    pages_visited=int(data.get("pages_visited") or len(data.get("pages") or []) or 0),
                    pages_ingested=int(data.get("pages_ingested") or len(data.get("pages") or []) or 0),
                    docs_ingested=int(data.get("docs_ingested") or 0),
                    errors_count=len(data.get("errors") or []) if isinstance(data.get("errors"), list) else 0,
                )
            )
        except Exception:
            # Skip malformed manifests; they can still be retrieved directly if needed.
            continue
    return IngestManifestsResponse(ts=time.time(), manifests=out)


class IngestManifestResponse(BaseModel):
    ok: bool = True
    ts: float
    manifest: dict[str, Any]


@router.get("/memory/ingest/manifests/{manifest_id}", response_model=IngestManifestResponse)
def get_ingest_manifest(manifest_id: str) -> IngestManifestResponse:
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    mid = _safe_manifest_id(manifest_id)
    # Try new layout first, then legacy.
    new_path = _ingest_dir(h.cfg) / mid / "manifest.json"
    legacy_path = _manifests_dir(h.cfg) / f"{mid}.json"
    path = new_path if new_path.exists() else legacy_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="manifest not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"manifest parse failed: {e}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="manifest is not an object")
    return IngestManifestResponse(ts=time.time(), manifest=data)


class ToolRunRequest(BaseModel):
    tool: str = Field(..., min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(..., min_length=1)
    thread_id: str | None = None


class ToolRunResponse(BaseModel):
    ok: bool
    ts: float
    output: Any = None
    error: str | None = None
    audit_tail: list[dict[str, Any]]


class ToolArgSchema(BaseModel):
    name: str
    type: str
    required: bool
    description: str


class ToolSchema(BaseModel):
    name: str
    description: str
    aliases: list[str] = Field(default_factory=list)
    args: list[ToolArgSchema] = Field(default_factory=list)


class ToolsSchemaResponse(BaseModel):
    ok: bool = True
    ts: float
    tools: list[ToolSchema]


class RuntimeStateResponse(BaseModel):
    ok: bool = True
    ts: float
    state: dict[str, Any]


@router.get("/tools/schema", response_model=ToolsSchemaResponse)
def tools_schema() -> ToolsSchemaResponse:
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        raw = h.tools.schema()
        tools = [ToolSchema.model_validate(t) for t in raw]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return ToolsSchemaResponse(ts=time.time(), tools=tools)


@router.post("/tool", response_model=ToolRunResponse)
def run_tool(body: ToolRunRequest, http: Request) -> ToolRunResponse:
    user_id = current_user_id(http)
    if body.thread_id and user_id:
        ensure_thread_owner(body.thread_id, owner_id=user_id)
    try:
        h, agent = get_agent_for_thread(body.thread_id, user=user_id)
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        res = agent.run_tool(tool_name=body.tool, tool_args=body.args, reason=body.reason)
        tail = h.ctx.audit.tail(limit=50)
        last_output = res.tool_results[-1].output if res.tool_results else None
        last_error = res.tool_results[-1].error if res.tool_results else None
        return ToolRunResponse(
            ok=bool(res.ok),
            ts=time.time(),
            output=last_output,
            error=last_error,
            audit_tail=tail,
        )
    except Exception as e:
        return ToolRunResponse(ok=False, ts=time.time(), output=None, error=str(e), audit_tail=h.ctx.audit.tail(limit=50))


@router.get("/runtime/state", response_model=RuntimeStateResponse)
def runtime_state(http: Request, thread_id: str | None = Query(None)) -> RuntimeStateResponse:
    user_id = current_user_id(http)
    if thread_id and user_id:
        ensure_thread_owner(thread_id, owner_id=user_id)
    try:
        _h, agent = get_agent_for_thread(thread_id, user=user_id)
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return RuntimeStateResponse(ts=time.time(), state=agent.runtime_state_snapshot())


class WebPolicyResponse(BaseModel):
    ok: bool = True
    ts: float
    allow_all_hosts: bool
    allowed_host_suffixes: list[str]
    allowed_suffixes: list[str] = Field(default_factory=list)
    allowed_domains: list[str]
    denied_domains: list[str]
    session_overrides_count: int
    session_allowed_domains: list[str] = Field(default_factory=list)
    effective_policy: dict[str, Any] = Field(default_factory=dict)


@router.get("/web/policy", response_model=WebPolicyResponse)
def get_web_policy(http: Request, thread_id: str | None = Query(None)) -> WebPolicyResponse:
    user_id = current_user_id(http)
    if thread_id and user_id:
        ensure_thread_owner(thread_id, owner_id=user_id)
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    cfg = h.cfg
    allow_all = bool(getattr(cfg.web, "policy_allow_all_hosts", False))
    allowed_suffixes = list(getattr(cfg.web, "policy_allowed_host_suffixes", ()) or ())
    allowed_domains = list(getattr(cfg.web, "policy_allowed_domains", ()) or ())
    denied_domains = list(getattr(cfg.web, "policy_denied_domains", ()) or ())
    session_allowed = list(get_session_allowed_domains(thread_id, user=user_id))
    effective_allowed_domains = sorted(set([d for d in allowed_domains if d] + [d for d in session_allowed if d]))
    effective = {
        "allow_all_hosts": allow_all,
        "allowed_suffixes": sorted(set([s for s in allowed_suffixes if s])),
        "allowed_domains": effective_allowed_domains,
        "denied_domains": sorted(set([d for d in denied_domains if d])),
        "session_allowed_domains": session_allowed,
    }
    return WebPolicyResponse(
        ts=time.time(),
        allow_all_hosts=allow_all,
        allowed_host_suffixes=allowed_suffixes,
        allowed_suffixes=allowed_suffixes,
        allowed_domains=allowed_domains,
        denied_domains=denied_domains,
        session_overrides_count=get_session_overrides_count(thread_id=thread_id, user=user_id),
        session_allowed_domains=session_allowed,
        effective_policy=effective,
    )


class WebPolicyUpdateRequest(BaseModel):
    allow_all_hosts: bool | None = None
    allowed_domains_add: list[str] = Field(default_factory=list)
    allowed_domains_remove: list[str] = Field(default_factory=list)
    allowed_host_suffixes_add: list[str] = Field(default_factory=list)
    allowed_host_suffixes_remove: list[str] = Field(default_factory=list)
    allowed_suffixes_add: list[str] = Field(default_factory=list)
    allowed_suffixes_remove: list[str] = Field(default_factory=list)
    denied_domains_add: list[str] = Field(default_factory=list)
    denied_domains_remove: list[str] = Field(default_factory=list)
    reason: str = Field(..., min_length=1)


class WebPolicyUpdateResponse(BaseModel):
    ok: bool = True
    ts: float
    result: dict[str, Any]
    audit_tail: list[dict[str, Any]]


@router.post("/web/policy/update", response_model=WebPolicyUpdateResponse)
def web_policy_update(body: WebPolicyUpdateRequest, http: Request) -> WebPolicyUpdateResponse:
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        result = update_web_policy(
            allow_all_hosts=body.allow_all_hosts,
            allowed_domains_add=[(x or "").strip().lower() for x in body.allowed_domains_add if (x or "").strip()],
            allowed_domains_remove=[(x or "").strip().lower() for x in body.allowed_domains_remove if (x or "").strip()],
            allowed_host_suffixes_add=[
                (x or "").strip().lower().lstrip(".")
                for x in (body.allowed_host_suffixes_add + body.allowed_suffixes_add)
                if (x or "").strip()
            ],
            allowed_host_suffixes_remove=[
                (x or "").strip().lower().lstrip(".")
                for x in (body.allowed_host_suffixes_remove + body.allowed_suffixes_remove)
                if (x or "").strip()
            ],
            denied_domains_add=[(x or "").strip().lower() for x in body.denied_domains_add if (x or "").strip()],
            denied_domains_remove=[(x or "").strip().lower() for x in body.denied_domains_remove if (x or "").strip()],
            reason=body.reason.strip(),
            client_host=(http.client.host if http.client else None),
        )
        tail = h.ctx.audit.tail(limit=50)
        return WebPolicyUpdateResponse(ts=time.time(), result=result, audit_tail=tail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/web/policy", response_model=WebPolicyUpdateResponse)
def web_policy_update_alias(body: WebPolicyUpdateRequest, http: Request) -> WebPolicyUpdateResponse:
    """Alias for POST /v1/web/policy/update (spec name)."""
    return web_policy_update(body, http)


class WebPolicySessionAllowRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class WebPolicySessionResponse(BaseModel):
    ok: bool = True
    ts: float
    audit_tail: list[dict[str, Any]]


@router.post("/web/policy/session_allow", response_model=WebPolicySessionResponse)
def web_policy_session_allow(body: WebPolicySessionAllowRequest, http: Request) -> WebPolicySessionResponse:
    user_id = current_user_id(http)
    if user_id:
        ensure_thread_owner(body.thread_id, owner_id=user_id)
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        session_allow_domain(thread_id=body.thread_id, domain=body.domain, reason=body.reason, client_host=(http.client.host if http.client else None), user=user_id)
        return WebPolicySessionResponse(ts=time.time(), audit_tail=h.ctx.audit.tail(limit=50))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class WebPolicySessionAllowManyRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    domains: list[str] = Field(default_factory=list, min_length=1)
    reason: str = Field(..., min_length=1)


@router.post("/web/policy/session", response_model=WebPolicySessionResponse)
def web_policy_session_allow_alias(body: WebPolicySessionAllowManyRequest, http: Request) -> WebPolicySessionResponse:
    user_id = current_user_id(http)
    if user_id:
        ensure_thread_owner(body.thread_id, owner_id=user_id)
    """Alias for session-only allow (spec name)."""
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        for d in body.domains or []:
            dom = (d or "").strip().lower()
            if not dom:
                continue
            session_allow_domain(thread_id=body.thread_id, domain=dom, reason=body.reason, client_host=(http.client.host if http.client else None), user=user_id)
        return WebPolicySessionResponse(ts=time.time(), audit_tail=h.ctx.audit.tail(limit=50))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class WebPolicySessionClearRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


@router.post("/web/policy/session_clear", response_model=WebPolicySessionResponse)
def web_policy_session_clear(body: WebPolicySessionClearRequest, http: Request) -> WebPolicySessionResponse:
    user_id = current_user_id(http)
    if user_id:
        ensure_thread_owner(body.thread_id, owner_id=user_id)
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        session_clear(thread_id=body.thread_id, reason=body.reason, client_host=(http.client.host if http.client else None), user=user_id)
        return WebPolicySessionResponse(ts=time.time(), audit_tail=h.ctx.audit.tail(limit=50))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
