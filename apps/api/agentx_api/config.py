from __future__ import annotations

import os
import json
import hashlib
from pathlib import Path

from agentx_api.ollama import normalize_ollama_base_url


_LEGACY_DEFAULT_PASSWORD_SHA256 = "5d197aa5a9be2caa46430f0dae3501f0f616d753491b7640fbd8c57267883943"
_TRUE_VALUES = ("1", "true", "yes", "on")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is not None:
        return value
    if name.startswith("AGENTX_"):
        suffix = name.removeprefix("AGENTX_")
        for legacy_name in (f"SOL_{suffix}", f"NEXAI_{suffix}"):
            legacy_value = os.getenv(legacy_name)
            if legacy_value is not None:
                return legacy_value
    return default


class ApiConfig:
    """Centralized API configuration."""

    host: str
    port: int
    settings_path: Path
    threads_dir: Path
    projects_dir: Path
    scripts_dir: Path
    openai_api_key: str | None
    openai_model: str
    openai_timeout_s: float
    openai_base_url: str
    ollama_base_url: str
    ollama_timeout_s: float
    model_list_ttl_s: float
    rag_db_path: Path
    rag_enabled: bool
    rag_top_k: int
    rag_chunk_chars: int
    rag_chunk_overlap_chars: int
    short_term_max_messages: int
    rag_ingest_threads: bool
    rag_allowed_roots: list[Path]
    fs_enabled: bool
    fs_allow_all_paths: bool
    fs_allowed_roots: list[Path]
    fs_write_enabled: bool
    fs_delete_enabled: bool
    fs_write_deny_drives: list[str]
    fs_max_read_bytes: int
    fs_max_write_bytes: int
    web_enabled: bool
    web_allow_all_hosts: bool
    web_allowed_hosts: list[str]
    web_block_private_networks: bool
    web_timeout_s: float
    web_max_bytes: int
    web_user_agent: str
    web_max_redirects: int
    web_max_search_results: int
    openai_tool_max_iters: int
    rag_tool_max_chars: int
    ollama_tools_enabled: bool
    ollama_tool_max_iters: int

    def __init__(self):
        self.host = _env("AGENTX_API_HOST", "127.0.0.1") or "127.0.0.1"
        self.port = int(_env("AGENTX_API_PORT", "8420") or "8420")
        self.log_level = (_env("AGENTX_LOG_LEVEL", "INFO") or "INFO").strip().upper()
        self.rate_limit_enabled = (_env("AGENTX_RATE_LIMIT_ENABLED", "false") or "false").strip().lower() in _TRUE_VALUES
        self.rate_limit_requests = int(_env("AGENTX_RATE_LIMIT_REQUESTS", "120") or "120")
        self.rate_limit_window_s = int(_env("AGENTX_RATE_LIMIT_WINDOW_S", "60") or "60")
        data_dir = Path(_env("AGENTX_API_DATA_DIR", str(Path(__file__).resolve().parent / "data")) or Path(__file__).resolve().parent / "data")
        data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = data_dir / "settings.json"
        self.threads_dir = data_dir / "threads"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir = data_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir = data_dir / "scripts"
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        self.thread_title_max = int(_env("AGENTX_THREAD_TITLE_MAX", "64") or "64")
        self.auth_enabled = self._load_auth_enabled()
        self.auth_session_ttl_s = max(300, int(_env("AGENTX_AUTH_SESSION_TTL_S", "604800") or "604800"))
        self.auth_users = self._load_auth_users()

        # Optional OpenAI wiring for /v1/chat. If unset, /v1/chat uses a local stub reply.
        self.openai_api_key = _env("AGENTX_OPENAI_API_KEY") or None
        self.openai_model = _env("AGENTX_OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
        self.openai_timeout_s = float(_env("AGENTX_OPENAI_TIMEOUT_S", "20") or "20")
        self.openai_base_url = _env("AGENTX_OPENAI_BASE_URL", "https://api.openai.com") or "https://api.openai.com"

        # Optional Ollama wiring for /v1/chat provider selection.
        self.ollama_base_url = normalize_ollama_base_url(_env("AGENTX_OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "http://127.0.0.1:11434")
        self.ollama_timeout_s = float(_env("AGENTX_OLLAMA_TIMEOUT_S", "5") or "5")
        self.ollama_request_timeout_s = float(_env("AGENTX_OLLAMA_REQUEST_TIMEOUT_S", "60") or "60")

        # Cache TTL for model discovery (/v1/status fields).
        self.model_list_ttl_s = float(_env("AGENTX_MODEL_LIST_TTL_S", "60") or "60")

        # RAG (Long-term retrieval) + short-term context settings.
        self.rag_db_path = data_dir / "rag.sqlite3"
        self.rag_enabled = (_env("AGENTX_RAG_ENABLED", "true") or "true").strip().lower() in ("1", "true", "yes", "on")
        self.rag_top_k = int(_env("AGENTX_RAG_TOP_K", "5") or "5")
        self.rag_chunk_chars = int(_env("AGENTX_RAG_CHUNK_CHARS", "1200") or "1200")
        self.rag_chunk_overlap_chars = int(_env("AGENTX_RAG_CHUNK_OVERLAP", "200") or "200")
        self.short_term_max_messages = int(_env("AGENTX_SHORT_TERM_MAX_MESSAGES", "12") or "12")
        self.rag_ingest_threads = (_env("AGENTX_RAG_INGEST_THREADS", "true") or "true").strip().lower() in ("1", "true", "yes", "on")

        # Optional: restrict /v1/rag/gather file access to explicit roots (semicolon-separated).
        # If unset, defaults to the API data directory only.
        roots_raw = (_env("AGENTX_RAG_ALLOWED_ROOTS", "") or "").strip()
        if roots_raw:
            self.rag_allowed_roots = [Path(p.strip()) for p in roots_raw.split(";") if p.strip()]
        else:
            self.rag_allowed_roots = [data_dir]

        # File-system access (DANGEROUS if misconfigured). Disabled by default.
        # If enabled, endpoints under /v1/fs/* can read/write files.
        self.fs_enabled = (_env("AGENTX_FS_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
        self.fs_allow_all_paths = (_env("AGENTX_FS_ALLOW_ALL", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
        fs_roots_raw = (_env("AGENTX_FS_ALLOWED_ROOTS", "") or "").strip()
        if fs_roots_raw:
            self.fs_allowed_roots = [Path(p.strip()) for p in fs_roots_raw.split(";") if p.strip()]
        else:
            self.fs_allowed_roots = [data_dir]
        self.fs_write_enabled = (_env("AGENTX_FS_WRITE_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
        self.fs_delete_enabled = (_env("AGENTX_FS_DELETE_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
        deny_raw = (_env("AGENTX_FS_WRITE_DENY_DRIVES", "C") or "C").strip()
        if deny_raw:
            self.fs_write_deny_drives = [d.strip().upper().rstrip(":") for d in deny_raw.replace(",", ";").split(";") if d.strip()]
        else:
            self.fs_write_deny_drives = ["C"]
        self.fs_max_read_bytes = int(_env("AGENTX_FS_MAX_READ_BYTES", "200000") or "200000")
        self.fs_max_write_bytes = int(_env("AGENTX_FS_MAX_WRITE_BYTES", "200000") or "200000")

        # Web access (DANGEROUS if exposed publicly). Disabled by default.
        #
        # When enabled, the server can fetch URLs for the chat model (tool use).
        # For public deployments, prefer a strict allowlist and keep private-network blocking ON.
        self.web_enabled = (_env("AGENTX_WEB_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
        self.web_allow_all_hosts = (_env("AGENTX_WEB_ALLOW_ALL", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
        allowed_hosts_raw = (_env("AGENTX_WEB_ALLOWED_HOSTS", "") or "").strip()
        if allowed_hosts_raw:
            self.web_allowed_hosts = [h.strip() for h in allowed_hosts_raw.split(";") if h.strip()]
        else:
            # Safe-ish defaults: no general web browsing unless explicitly allowed.
            self.web_allowed_hosts = ["duckduckgo.com", "wikipedia.org"]
        self.web_block_private_networks = (_env("AGENTX_WEB_BLOCK_PRIVATE", "true") or "true").strip().lower() in ("1", "true", "yes", "on")
        self.web_timeout_s = float(_env("AGENTX_WEB_TIMEOUT_S", "10") or "10")
        self.web_max_bytes = int(_env("AGENTX_WEB_MAX_BYTES", "400000") or "400000")
        self.web_user_agent = _env("AGENTX_WEB_USER_AGENT", "AgentXWebAccess/0.1") or "AgentXWebAccess/0.1"
        self.web_max_redirects = int(_env("AGENTX_WEB_MAX_REDIRECTS", "5") or "5")
        self.web_max_search_results = int(_env("AGENTX_WEB_MAX_SEARCH_RESULTS", "5") or "5")

        # OpenAI tool loop safety.
        self.openai_tool_max_iters = int(_env("AGENTX_OPENAI_TOOL_MAX_ITERS", "4") or "4")

        # Limits for model-driven RAG writes (protect disk + prevent accidental dumps).
        self.rag_tool_max_chars = int(_env("AGENTX_RAG_TOOL_MAX_CHARS", "8000") or "8000")

        # Ollama "tool calling" (best-effort text protocol) for local models.
        # Disabled by default because many models do not reliably follow tool schemas.
        self.ollama_tools_enabled = (_env("AGENTX_OLLAMA_TOOLS_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
        self.ollama_tool_max_iters = int(_env("AGENTX_OLLAMA_TOOL_MAX_ITERS", "4") or "4")

    def _load_auth_enabled(self) -> bool:
        raw_env = _env("AGENTX_AUTH_ENABLED")
        if raw_env is not None and raw_env.strip():
            return raw_env.strip().lower() in _TRUE_VALUES
        return False

    def _load_auth_users(self) -> dict[str, str]:
        raw_users = (_env("AGENTX_AUTH_USERS_JSON") or "").strip()
        if raw_users:
            try:
                parsed = json.loads(raw_users)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                out: dict[str, str] = {}
                for user, digest in parsed.items():
                    u = str(user or "").strip().lower()
                    d = str(digest or "").strip().lower()
                    if u and d:
                        out[u] = d
                if out:
                    return out

        user = (_env("AGENTX_AUTH_USER") or "agentx").strip().lower() or "agentx"
        password_sha256 = (_env("AGENTX_AUTH_PASSWORD_SHA256") or "").strip().lower()
        password = _env("AGENTX_AUTH_PASSWORD")
        if not password_sha256 and password:
            password_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return {user: password_sha256 or _LEGACY_DEFAULT_PASSWORD_SHA256}

    def runtime_diagnostics(self) -> dict:
        """Return startup/runtime configuration checks that are safe to expose locally."""
        warnings: list[str] = []
        errors: list[str] = []

        def _exists(path: Path, label: str) -> None:
            try:
                if not path.exists():
                    errors.append(f"{label} does not exist: {path}")
            except Exception as exc:
                errors.append(f"{label} is not accessible: {path} ({exc})")

        if self.port < 1 or self.port > 65535:
            errors.append(f"AGENTX_API_PORT must be between 1 and 65535, got {self.port}.")
        if self.auth_enabled and not self.auth_users:
            errors.append("Authentication is enabled but no users are configured.")
        if not self.auth_enabled:
            warnings.append("Authentication is disabled. Keep AgentX behind your LAN/firewall.")
        if self.fs_enabled and self.fs_allow_all_paths:
            warnings.append("Filesystem access is enabled with AGENTX_FS_ALLOW_ALL=true. This is powerful and risky.")
        if self.fs_write_enabled and not self.fs_enabled:
            warnings.append("Filesystem writes are enabled but filesystem access is disabled; write routes will still be blocked.")
        if self.fs_delete_enabled and not self.fs_write_enabled:
            warnings.append("Filesystem delete is enabled while filesystem write is disabled; verify this is intentional.")
        if self.web_enabled and self.web_allow_all_hosts:
            warnings.append("Web access is enabled for all hosts. Prefer AGENTX_WEB_ALLOWED_HOSTS for safer tool use.")
        if self.web_enabled and not self.web_block_private_networks:
            warnings.append("Private-network web blocking is disabled. This can expose internal services to model-driven requests.")
        if self.rate_limit_enabled and self.rate_limit_requests < 10:
            warnings.append("Rate limit is very low and may block normal UI polling.")

        for path, label in (
            (self.settings_path.parent, "settings directory"),
            (self.threads_dir, "threads directory"),
            (self.projects_dir, "projects directory"),
            (self.scripts_dir, "scripts directory"),
            (self.rag_db_path.parent, "RAG database directory"),
        ):
            _exists(path, label)

        return {
            "config": {
                "host": self.host,
                "port": self.port,
                "auth_enabled": self.auth_enabled,
                "fs_enabled": self.fs_enabled,
                "fs_allow_all_paths": self.fs_allow_all_paths,
                "fs_write_enabled": self.fs_write_enabled,
                "fs_delete_enabled": self.fs_delete_enabled,
                "web_enabled": self.web_enabled,
                "web_allow_all_hosts": self.web_allow_all_hosts,
                "web_block_private_networks": self.web_block_private_networks,
                "rate_limit_enabled": self.rate_limit_enabled,
                "rate_limit_requests": self.rate_limit_requests,
                "rate_limit_window_s": self.rate_limit_window_s,
                "ollama_base_url": self.ollama_base_url,
                "settings_path": str(self.settings_path),
            },
            "warnings": warnings,
            "errors": errors,
        }

    def assert_startup_safe(self) -> None:
        report = self.runtime_diagnostics()
        if report["errors"]:
            raise RuntimeError("AgentX runtime configuration failed validation: " + "; ".join(report["errors"]))


config = ApiConfig()
