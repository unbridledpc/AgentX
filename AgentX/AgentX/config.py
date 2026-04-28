from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None:
        return value
    if name.startswith("AGENTX_"):
        suffix = name.removeprefix("AGENTX_")
        for legacy_name in (f"SOL_{suffix}", f"NEXAI_{suffix}"):
            legacy_value = os.environ.get(legacy_name)
            if legacy_value is not None:
                return legacy_value
    return default


@dataclass(frozen=True)
class PathsConfig:
    app_root: Path
    runtime_root: Path
    config_dir: Path
    data_dir: Path
    logs_dir: Path
    runtime_dir: Path
    run_dir: Path
    cache_dir: Path
    temp_dir: Path
    audit_dir: Path
    memory_dir: Path
    working_dir: Path
    plugins_dir: Path
    skills_dir: Path
    user_plugins_dir: Path
    user_skills_dir: Path
    features_dir: Path
    api_dir: Path
    web_dir: Path
    web_dist_dir: Path
    agentxweb_dir: Path | None = None
    desktop_dir: Path | None = None


@dataclass(frozen=True)
class AgentConfig:
    mode: str
    max_steps: int
    refuse_unattended: bool
    auto_tools: bool
    auto_web_verify: bool


@dataclass(frozen=True)
class AuditConfig:
    log_path: Path


@dataclass(frozen=True)
class FsConfig:
    allowed_roots: tuple[Path, ...]
    deny_drive_letters: tuple[str, ...]
    denied_substrings: tuple[str, ...]
    denied_path_patterns: tuple[str, ...]
    max_read_bytes: int
    max_write_bytes: int
    max_delete_count: int


@dataclass(frozen=True)
class ExecConfig:
    enabled: bool
    timeout_s: float
    allowed_commands: tuple[str, ...]
    allow_shell: bool
    deny_extensions: tuple[str, ...]


@dataclass(frozen=True)
class WebConfig:
    enabled: bool
    # Network allowlist for search-provider endpoints only (DDG/SearxNG/Bing).
    # Fetch/crawl target allow/deny is enforced by `policy_*` below.
    allow_all_hosts: bool
    allowed_host_suffixes: tuple[str, ...]
    block_private_networks: bool
    timeout_s: float
    max_bytes: int
    user_agent: str
    max_redirects: int
    max_search_results: int
    search_providers: tuple[str, ...]
    search_timeout_s: float
    search_k_per_provider: int
    search_max_total_results: int
    search_searxng_base_url: str
    search_searxng_categories: str
    search_bing_api_key: str
    search_bing_endpoint: str
    # Persistent fetch/crawl policy (allowlist-first).
    policy_allow_all_hosts: bool
    policy_allowed_host_suffixes: tuple[str, ...]
    policy_allowed_domains: tuple[str, ...]
    policy_denied_domains: tuple[str, ...]
    allowed_domains: tuple[str, ...]
    crawl_max_pages_default: int
    crawl_delay_ms_default: int
    # URL ingestion defaults (used by web.ingest_url GitHub/repo-aware mode).
    ingest_include_globs: tuple[str, ...]
    ingest_exclude_globs: tuple[str, ...]
    ingest_max_files: int
    ingest_max_files_repo: int
    ingest_max_depth_repo: int
    ingest_max_dirs_repo: int
    ingest_prefer_docs: bool
    github_token_env: str = ""


@dataclass(frozen=True)
class TibiaSourcesConfig:
    enabled: bool
    default_delay_ms: int
    max_threads: int
    max_pages_per_thread: int
    domains: dict[str, str]
    domain_enabled: dict[str, bool]


@dataclass(frozen=True)
class TibiaConfig:
    sources: TibiaSourcesConfig


@dataclass(frozen=True)
class RagConfig:
    enabled: bool
    db_path: Path
    top_k: int
    chunk_chars: int
    chunk_overlap_chars: int


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool
    backend: str
    db_path: Path
    events_path: Path
    chunk_chars: int
    chunk_overlap_chars: int
    k_default: int


@dataclass(frozen=True)
class VoiceConfig:
    enabled: bool
    wake_word_enabled: bool
    wake_word: str
    mic_device: str


@dataclass(frozen=True)
class VisionConfig:
    enabled: bool
    device_index: int


@dataclass(frozen=True)
class AgentXConfig:
    mode: str
    agent: AgentConfig
    audit: AuditConfig
    paths: PathsConfig
    fs: FsConfig
    exec: ExecConfig
    web: WebConfig
    tibia: TibiaConfig
    rag: RagConfig
    memory: MemoryConfig
    voice: VoiceConfig
    vision: VisionConfig
    llm: dict[str, Any]
    root_dir: Path


def _as_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    return default


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _as_str(v: Any, default: str) -> str:
    if isinstance(v, str):
        return v
    return default


def _as_list_str(v: Any) -> list[str]:
    if isinstance(v, list):
        out: list[str] = []
        for x in v:
            if isinstance(x, str) and x.strip():
                out.append(x.strip())
        return out
    return []


def _infer_app_root_from_paths(paths_d: dict[str, Any], *, fallback: Path) -> Path:
    candidates = [
        _as_str(paths_d.get("api_dir"), ""),
        _as_str(paths_d.get("web_dir"), ""),
        _as_str(paths_d.get("web_dist_dir"), ""),
        _as_str(paths_d.get("plugins_dir"), ""),
        _as_str(paths_d.get("skills_dir"), ""),
        _as_str(paths_d.get("features_dir"), ""),
        _as_str(paths_d.get("desktop_dir"), ""),
        _as_str(paths_d.get("agentxweb_dir"), ""),
    ]
    for raw in candidates:
        if not raw.strip():
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            continue
        parts = candidate.resolve(strict=False).parts
        for anchor in ("apps", "AgentXWeb", "AgentX"):
            if anchor in parts:
                idx = parts.index(anchor)
                if idx > 0:
                    return Path(*parts[:idx]).resolve(strict=False)
    return fallback.resolve(strict=False)


def load_config(path: str) -> AgentXConfig:
    cfg_path = Path(path).expanduser()
    app_root_env = (_env("AGENTX_APP_ROOT") or "").strip()
    app_root = Path(app_root_env).expanduser().resolve() if app_root_env else None
    runtime_root_env = (_env("AGENTX_RUNTIME_ROOT") or "").strip()
    runtime_root = Path(runtime_root_env).expanduser().resolve() if runtime_root_env else None
    working_dir_env = (_env("AGENTX_WORKING_DIR") or "").strip()
    if cfg_path.is_absolute():
        raw_path = cfg_path
    else:
        base = (runtime_root / "config") if runtime_root is not None else Path(os.getcwd()).resolve()
        raw_path = (base / cfg_path).resolve()
    if not raw_path.exists() and raw_path.name == "agentx.toml":
        legacy_path = raw_path.with_name("sol.toml")
        if legacy_path.exists():
            raw_path = legacy_path

    data: dict[str, Any] = {}
    if raw_path.exists():
        data = tomllib.loads(raw_path.read_text(encoding="utf-8"))
    paths_d = data.get("paths") if isinstance(data.get("paths"), dict) else {}

    if app_root is None:
        fallback_app_root = Path(__file__).resolve().parents[2]
        if raw_path.name in {"agentx.toml", "sol.toml"} and raw_path.parent.name == "config":
            fallback_app_root = raw_path.parent.parent.resolve()
        app_root = _infer_app_root_from_paths(paths_d, fallback=fallback_app_root)
    if runtime_root is None:
        if raw_path.name in {"agentx.toml", "sol.toml"} and raw_path.parent.name == "config":
            runtime_root = raw_path.parent.parent.resolve()
        else:
            runtime_root = Path(os.getcwd()).resolve()
    config_dir = raw_path.parent.resolve()
    root_dir = app_root

    # Agent mode (preferred) with backward-compatible fallback to legacy root `mode`.
    agent_d = data.get("agent") if isinstance(data.get("agent"), dict) else {}
    agent_mode = _as_str(agent_d.get("mode"), "").strip().lower()
    legacy_mode = _as_str(data.get("mode"), "supervised").strip().lower()
    mode = agent_mode or legacy_mode
    if mode not in ("supervised", "unattended"):
        mode = "supervised"
    agent_cfg = AgentConfig(
        mode=mode,
        max_steps=max(1, min(_as_int(agent_d.get("max_steps"), 3), 20)),
        refuse_unattended=_as_bool(agent_d.get("refuse_unattended"), True),
        auto_tools=_as_bool(agent_d.get("auto_tools"), True),
        auto_web_verify=_as_bool(agent_d.get("auto_web_verify"), True),
    )

    data_dir_raw = Path(_as_str(paths_d.get("data_dir"), "data"))
    logs_dir_raw = Path(_as_str(paths_d.get("logs_dir"), "logs"))
    runtime_dir_raw = Path(_as_str(paths_d.get("runtime_dir"), "runtime"))
    run_dir_raw = Path(_as_str(paths_d.get("run_dir"), "run"))
    cache_dir_raw = Path(_as_str(paths_d.get("cache_dir"), "cache"))
    temp_dir_raw = Path(_as_str(paths_d.get("temp_dir"), "tmp"))
    audit_dir_raw = Path(_as_str(paths_d.get("audit_dir"), "audit"))
    memory_dir_raw = Path(_as_str(paths_d.get("memory_dir"), "memory"))
    working_dir_raw = Path(_as_str(paths_d.get("working_dir"), working_dir_env or "work"))

    def _resolve_runtime_path(value: Path) -> Path:
        return value if value.is_absolute() else (runtime_root / value)

    def _resolve_app_path(value: Path) -> Path:
        return value if value.is_absolute() else (app_root / value)

    data_dir = _resolve_runtime_path(data_dir_raw)
    logs_dir = _resolve_runtime_path(logs_dir_raw)
    runtime_dir = _resolve_runtime_path(runtime_dir_raw)
    run_dir = _resolve_runtime_path(run_dir_raw)
    cache_dir = _resolve_runtime_path(cache_dir_raw)
    temp_dir = _resolve_runtime_path(temp_dir_raw)
    audit_dir = _resolve_runtime_path(audit_dir_raw)
    memory_dir = _resolve_runtime_path(memory_dir_raw)
    working_dir = _resolve_runtime_path(working_dir_raw)

    plugins_dir_raw = Path(_as_str(paths_d.get("plugins_dir"), "AgentX/plugins"))
    skills_dir_raw = Path(_as_str(paths_d.get("skills_dir"), "AgentX/skills"))
    user_plugins_dir_raw = Path(_as_str(paths_d.get("user_plugins_dir"), "extensions/plugins"))
    user_skills_dir_raw = Path(_as_str(paths_d.get("user_skills_dir"), "extensions/skills"))
    features_dir_raw = Path(_as_str(paths_d.get("features_dir"), "AgentX/Server/data/features"))
    api_dir_raw = Path(_as_str(paths_d.get("api_dir"), "apps/api"))
    web_dir_raw = Path(_as_str(paths_d.get("web_dir"), "AgentXWeb"))
    web_dist_dir_raw = Path(_as_str(paths_d.get("web_dist_dir"), "AgentXWeb/dist"))

    plugins_dir = _resolve_app_path(plugins_dir_raw)
    skills_dir = _resolve_app_path(skills_dir_raw)
    user_plugins_dir = _resolve_runtime_path(user_plugins_dir_raw)
    user_skills_dir = _resolve_runtime_path(user_skills_dir_raw)
    features_dir = _resolve_app_path(features_dir_raw)
    api_dir = _resolve_app_path(api_dir_raw)
    web_dir = _resolve_app_path(web_dir_raw)
    web_dist_dir = _resolve_app_path(web_dist_dir_raw)
    agentxweb_dir_raw_s = _as_str(paths_d.get("agentxweb_dir"), "").strip()
    desktop_dir_raw_s = _as_str(paths_d.get("desktop_dir"), "").strip()
    agentxweb_dir: Path | None = None
    desktop_dir: Path | None = None
    if agentxweb_dir_raw_s:
        agentxweb_dir_raw = Path(agentxweb_dir_raw_s)
        agentxweb_dir = _resolve_app_path(agentxweb_dir_raw).resolve()
    if desktop_dir_raw_s:
        desktop_dir_raw = Path(desktop_dir_raw_s)
        desktop_dir = _resolve_app_path(desktop_dir_raw).resolve()
    audit_d = data.get("audit") if isinstance(data.get("audit"), dict) else {}
    audit_path_raw = Path(_as_str(audit_d.get("log_path"), str(audit_dir / "agentx_audit.jsonl")))
    audit_path = audit_path_raw if audit_path_raw.is_absolute() else _resolve_runtime_path(audit_path_raw)

    fs_d = data.get("fs") if isinstance(data.get("fs"), dict) else {}
    allowed_roots = tuple(Path(p) for p in _as_list_str(fs_d.get("allowed_roots")))
    deny_drive_letters = tuple(s.strip().upper().rstrip(":") for s in _as_list_str(fs_d.get("deny_drive_letters")))
    denied_substrings = tuple(s.strip().lower() for s in _as_list_str(fs_d.get("denied_substrings")))
    denied_path_patterns = tuple(s.strip() for s in _as_list_str(fs_d.get("denied_path_patterns")))
    for pat in denied_path_patterns:
        try:
            re.compile(pat)
        except re.error as e:
            raise ValueError(f"Invalid fs.denied_path_patterns regex {pat!r}: {e}") from e
    max_read_bytes = _as_int(fs_d.get("max_read_bytes"), 200_000)
    max_write_bytes = _as_int(fs_d.get("max_write_bytes"), 200_000)
    max_delete_count = _as_int(fs_d.get("max_delete_count"), 10)

    exec_d = data.get("exec") if isinstance(data.get("exec"), dict) else {}
    exec_cfg = ExecConfig(
        enabled=_as_bool(exec_d.get("enabled"), True),
        timeout_s=_as_float(exec_d.get("timeout_s"), 30.0),
        allowed_commands=tuple(s.strip().lower() for s in _as_list_str(exec_d.get("allowed_commands"))),
        allow_shell=_as_bool(exec_d.get("allow_shell"), False),
        deny_extensions=tuple(s.strip().lower() for s in _as_list_str(exec_d.get("deny_extensions"))),
    )

    web_d = data.get("web") if isinstance(data.get("web"), dict) else {}
    allowed_domains = tuple(s.strip().lower().rstrip(".") for s in _as_list_str(web_d.get("allowed_domains")))
    search_d = web_d.get("search") if isinstance(web_d.get("search"), dict) else {}
    search_providers = tuple(s.strip().lower() for s in _as_list_str(search_d.get("providers"))) or ("duckduckgo",)
    search_timeout_s = _as_float(search_d.get("timeout_s"), _as_float(web_d.get("timeout_s"), 10.0))
    search_k_per_provider = _as_int(search_d.get("k_per_provider"), 8)
    search_max_total = _as_int(search_d.get("max_total_results"), _as_int(web_d.get("max_search_results"), 5))
    searxng_d = search_d.get("searxng") if isinstance(search_d.get("searxng"), dict) else {}
    bing_d = search_d.get("bing") if isinstance(search_d.get("bing"), dict) else {}

    policy_d = web_d.get("policy") if isinstance(web_d.get("policy"), dict) else {}
    github_d = web_d.get("github") if isinstance(web_d.get("github"), dict) else {}
    github_token_env = _as_str(github_d.get("token_env"), "").strip()
    policy_allow_all = _as_bool(policy_d.get("allow_all_hosts"), False)
    # Backward compatible: policy.allowed_host_suffixes (old) == policy.allowed_suffixes (new).
    policy_allowed_suffixes = tuple(
        s.strip().lower().rstrip(".")
        for s in _as_list_str(policy_d.get("allowed_suffixes") if "allowed_suffixes" in policy_d else policy_d.get("allowed_host_suffixes"))
    )
    policy_allowed_domains = tuple(s.strip().lower().rstrip(".") for s in _as_list_str(policy_d.get("allowed_domains")))
    policy_denied_domains = tuple(s.strip().lower().rstrip(".") for s in _as_list_str(policy_d.get("denied_domains")))
    ingest_d = web_d.get("ingest") if isinstance(web_d.get("ingest"), dict) else {}
    ingest_include_globs = tuple(s.strip() for s in _as_list_str(ingest_d.get("include_globs")))
    _default_ingest_exclude_globs = (
        "**/.git/**",
        "**/node_modules/**",
        "**/vendor/**",
        "**/dist/**",
        "**/build/**",
        "**/*.min.*",
        "**/*.map",
        "**/*.png",
        "**/*.jpg",
        "**/*.jpeg",
        "**/*.gif",
        "**/*.svg",
        "**/*.pdf",
        "**/*.zip",
    )
    if "exclude_globs" in ingest_d:
        ingest_exclude_globs = tuple(s.strip() for s in _as_list_str(ingest_d.get("exclude_globs")))
    else:
        ingest_exclude_globs = _default_ingest_exclude_globs
    ingest_max_files = max(1, min(_as_int(ingest_d.get("max_files"), 80), 500))
    ingest_max_files_repo = max(1, min(_as_int(ingest_d.get("max_files_repo"), 50), 500))
    ingest_max_depth_repo = max(0, min(_as_int(ingest_d.get("max_depth_repo"), 3), 10))
    ingest_max_dirs_repo = max(1, min(_as_int(ingest_d.get("max_dirs_repo"), 200), 10_000))
    ingest_prefer_docs = _as_bool(ingest_d.get("prefer_docs"), True)

    web_cfg = WebConfig(
        enabled=_as_bool(web_d.get("enabled"), False),
        allow_all_hosts=_as_bool(web_d.get("allow_all_hosts"), False),
        allowed_host_suffixes=tuple(s.strip().lower().rstrip(".") for s in _as_list_str(web_d.get("allowed_host_suffixes"))),
        block_private_networks=_as_bool(web_d.get("block_private_networks"), True),
        timeout_s=_as_float(web_d.get("timeout_s"), 10.0),
        max_bytes=_as_int(web_d.get("max_bytes"), 400_000),
        user_agent=_as_str(web_d.get("user_agent"), "AgentX/0.1"),
        max_redirects=_as_int(web_d.get("max_redirects"), 5),
        max_search_results=_as_int(web_d.get("max_search_results"), 5),
        search_providers=search_providers,
        search_timeout_s=search_timeout_s,
        search_k_per_provider=max(1, min(search_k_per_provider, 50)),
        search_max_total_results=max(1, min(search_max_total, 50)),
        search_searxng_base_url=_as_str(search_d.get("searxng_base_url"), _as_str(searxng_d.get("base_url"), "")).strip(),
        search_searxng_categories=_as_str(searxng_d.get("categories"), "general").strip() or "general",
        search_bing_api_key=_as_str(search_d.get("bing_api_key"), _as_str(bing_d.get("api_key"), "")).strip(),
        search_bing_endpoint=_as_str(search_d.get("bing_endpoint"), _as_str(bing_d.get("endpoint"), "")).strip(),
        policy_allow_all_hosts=policy_allow_all,
        policy_allowed_host_suffixes=policy_allowed_suffixes,
        policy_allowed_domains=policy_allowed_domains,
        policy_denied_domains=policy_denied_domains,
        allowed_domains=allowed_domains,
        crawl_max_pages_default=max(1, min(_as_int(web_d.get("crawl_max_pages_default"), 50), 200)),
        crawl_delay_ms_default=max(0, min(_as_int(web_d.get("crawl_delay_ms_default"), 500), 5000)),
        ingest_include_globs=ingest_include_globs,
        ingest_exclude_globs=ingest_exclude_globs,
        ingest_max_files=ingest_max_files,
        ingest_max_files_repo=ingest_max_files_repo,
        ingest_max_depth_repo=ingest_max_depth_repo,
        ingest_max_dirs_repo=ingest_max_dirs_repo,
        ingest_prefer_docs=ingest_prefer_docs,
        github_token_env=github_token_env,
    )

    tibia_d = data.get("tibia") if isinstance(data.get("tibia"), dict) else {}
    tibia_sources_d = tibia_d.get("sources") if isinstance(tibia_d.get("sources"), dict) else {}
    tibia_sources_domains_d = tibia_sources_d.get("domains") if isinstance(tibia_sources_d.get("domains"), dict) else {}
    tibia_sources_enabled_d = tibia_sources_d.get("domain_enabled") if isinstance(tibia_sources_d.get("domain_enabled"), dict) else {}

    tibia_domains: dict[str, str] = {}
    for k, v in tibia_sources_domains_d.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if not isinstance(v, str) or not v.strip():
            continue
        tibia_domains[k.strip().lower()] = v.strip().lower().rstrip(".")
    if not tibia_domains:
        tibia_domains = {"otland": "otland.net", "tibiaking": "tibiaking.com"}

    tibia_domain_enabled: dict[str, bool] = {}
    for k, v in tibia_sources_enabled_d.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if isinstance(v, bool):
            tibia_domain_enabled[k.strip().lower()] = bool(v)
    for k in tibia_domains.keys():
        tibia_domain_enabled.setdefault(k, True)

    tibia_cfg = TibiaConfig(
        sources=TibiaSourcesConfig(
            enabled=_as_bool(tibia_sources_d.get("enabled"), True),
            default_delay_ms=max(0, min(_as_int(tibia_sources_d.get("default_delay_ms"), 500), 5000)),
            max_threads=max(1, min(_as_int(tibia_sources_d.get("max_threads"), 5), 20)),
            max_pages_per_thread=max(1, min(_as_int(tibia_sources_d.get("max_pages_per_thread"), 5), 20)),
            domains=tibia_domains,
            domain_enabled=tibia_domain_enabled,
        )
    )

    rag_d = data.get("rag") if isinstance(data.get("rag"), dict) else {}
    rag_db_raw = Path(_as_str(rag_d.get("db_path"), str(memory_dir / "rag.sqlite3")))
    rag_db = rag_db_raw if rag_db_raw.is_absolute() else _resolve_runtime_path(rag_db_raw)
    rag_cfg = RagConfig(
        enabled=_as_bool(rag_d.get("enabled"), True),
        db_path=rag_db,
        top_k=_as_int(rag_d.get("top_k"), 5),
        chunk_chars=_as_int(rag_d.get("chunk_chars"), 1200),
        chunk_overlap_chars=_as_int(rag_d.get("chunk_overlap_chars"), 200),
    )

    # Memory config (preferred). Backward-compatible defaults reuse [rag] settings.
    memory_d = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    mem_enabled = _as_bool(memory_d.get("enabled"), True)
    mem_backend = _as_str(memory_d.get("backend"), "sqlite_fts").strip().lower() or "sqlite_fts"
    mem_db_raw = Path(_as_str(memory_d.get("db_path"), str(rag_cfg.db_path)))
    mem_db = mem_db_raw if mem_db_raw.is_absolute() else _resolve_runtime_path(mem_db_raw)
    mem_events_raw = Path(_as_str(memory_d.get("events_path"), str(memory_dir / "memory_events.jsonl")))
    mem_events = mem_events_raw if mem_events_raw.is_absolute() else _resolve_runtime_path(mem_events_raw)
    mem_chunk_chars = _as_int(memory_d.get("chunk_chars"), rag_cfg.chunk_chars)
    mem_chunk_overlap = _as_int(memory_d.get("chunk_overlap_chars"), rag_cfg.chunk_overlap_chars)
    mem_k_default = _as_int(memory_d.get("k_default"), 8)
    memory_cfg = MemoryConfig(
        enabled=mem_enabled,
        backend=mem_backend,
        db_path=mem_db,
        events_path=mem_events,
        chunk_chars=mem_chunk_chars,
        chunk_overlap_chars=mem_chunk_overlap,
        k_default=max(1, min(mem_k_default, 50)),
    )

    voice_d = data.get("voice") if isinstance(data.get("voice"), dict) else {}
    voice_cfg = VoiceConfig(
        enabled=_as_bool(voice_d.get("enabled"), False),
        wake_word_enabled=_as_bool(voice_d.get("wake_word_enabled"), False),
        wake_word=_as_str(voice_d.get("wake_word"), "agentx"),
        mic_device=_as_str(voice_d.get("mic_device"), ""),
    )

    vision_d = data.get("vision") if isinstance(data.get("vision"), dict) else {}
    vision_cfg = VisionConfig(
        enabled=_as_bool(vision_d.get("enabled"), False),
        device_index=_as_int(vision_d.get("device_index"), 0),
    )

    llm_d = data.get("llm") if isinstance(data.get("llm"), dict) else {}

    return AgentXConfig(
        mode=mode,
        agent=agent_cfg,
        audit=AuditConfig(log_path=audit_path.resolve()),
        paths=PathsConfig(
            app_root=app_root.resolve(),
            runtime_root=runtime_root.resolve(),
            config_dir=config_dir.resolve(),
            data_dir=data_dir.resolve(),
            logs_dir=logs_dir.resolve(),
            runtime_dir=runtime_dir.resolve(),
            run_dir=run_dir.resolve(),
            cache_dir=cache_dir.resolve(),
            temp_dir=temp_dir.resolve(),
            audit_dir=audit_dir.resolve(),
            memory_dir=memory_dir.resolve(),
            working_dir=working_dir.resolve(),
            plugins_dir=plugins_dir.resolve(),
            skills_dir=skills_dir.resolve(),
            user_plugins_dir=user_plugins_dir.resolve(),
            user_skills_dir=user_skills_dir.resolve(),
            features_dir=features_dir.resolve(),
            api_dir=api_dir.resolve(),
            web_dir=web_dir.resolve(),
            web_dist_dir=web_dist_dir.resolve(),
            agentxweb_dir=agentxweb_dir,
            desktop_dir=desktop_dir,
        ),
        fs=FsConfig(
            allowed_roots=tuple((Path(p).resolve() if Path(p).is_absolute() else (root_dir / p).resolve()) for p in allowed_roots)
            if allowed_roots
            else tuple(),
            deny_drive_letters=deny_drive_letters,
            denied_substrings=denied_substrings,
            denied_path_patterns=denied_path_patterns,
            max_read_bytes=max_read_bytes,
            max_write_bytes=max_write_bytes,
            max_delete_count=max_delete_count,
        ),
        exec=exec_cfg,
        web=web_cfg,
        tibia=tibia_cfg,
        rag=rag_cfg,
        memory=memory_cfg,
        voice=voice_cfg,
        vision=vision_cfg,
        llm=llm_d,
        root_dir=root_dir,
    )
