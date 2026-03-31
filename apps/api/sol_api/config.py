from __future__ import annotations

import os
import json
import hashlib
from pathlib import Path

from sol_api.ollama import normalize_ollama_base_url


_LEGACY_DEFAULT_PASSWORD_SHA256 = "5d197aa5a9be2caa46430f0dae3501f0f616d753491b7640fbd8c57267883943"


class ApiConfig:
    """Centralized API configuration."""

    host: str
    port: int
    settings_path: Path
    threads_dir: Path
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
        self.host = os.getenv("SOL_API_HOST", "127.0.0.1")
        self.port = int(os.getenv("SOL_API_PORT", "8420"))
        data_dir = Path(os.getenv("SOL_API_DATA_DIR", Path(__file__).resolve().parent / "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = data_dir / "settings.json"
        self.threads_dir = data_dir / "threads"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.thread_title_max = int(os.getenv("SOL_THREAD_TITLE_MAX", "64"))
        self.auth_enabled = os.getenv("SOL_AUTH_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
        self.auth_session_ttl_s = max(300, int(os.getenv("SOL_AUTH_SESSION_TTL_S", "604800")))
        self.auth_users = self._load_auth_users()

        # Optional OpenAI wiring for /v1/chat. If unset, /v1/chat uses a local stub reply.
        self.openai_api_key = os.getenv("SOL_OPENAI_API_KEY") or None
        self.openai_model = os.getenv("SOL_OPENAI_MODEL", "gpt-4o-mini")
        self.openai_timeout_s = float(os.getenv("SOL_OPENAI_TIMEOUT_S", "20"))
        self.openai_base_url = os.getenv("SOL_OPENAI_BASE_URL", "https://api.openai.com")

        # Optional Ollama wiring for /v1/chat provider selection.
        self.ollama_base_url = normalize_ollama_base_url(os.getenv("SOL_OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
        self.ollama_timeout_s = float(os.getenv("SOL_OLLAMA_TIMEOUT_S", "5"))
        self.ollama_request_timeout_s = float(os.getenv("SOL_OLLAMA_REQUEST_TIMEOUT_S", "60"))

        # Cache TTL for model discovery (/v1/status fields).
        self.model_list_ttl_s = float(os.getenv("SOL_MODEL_LIST_TTL_S", "60"))

        # RAG (Long-term retrieval) + short-term context settings.
        self.rag_db_path = data_dir / "rag.sqlite3"
        self.rag_enabled = os.getenv("SOL_RAG_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
        self.rag_top_k = int(os.getenv("SOL_RAG_TOP_K", "5"))
        self.rag_chunk_chars = int(os.getenv("SOL_RAG_CHUNK_CHARS", "1200"))
        self.rag_chunk_overlap_chars = int(os.getenv("SOL_RAG_CHUNK_OVERLAP", "200"))
        self.short_term_max_messages = int(os.getenv("SOL_SHORT_TERM_MAX_MESSAGES", "12"))
        self.rag_ingest_threads = os.getenv("SOL_RAG_INGEST_THREADS", "true").strip().lower() in ("1", "true", "yes", "on")

        # Optional: restrict /v1/rag/gather file access to explicit roots (semicolon-separated).
        # If unset, defaults to the API data directory only.
        roots_raw = os.getenv("SOL_RAG_ALLOWED_ROOTS", "").strip()
        if roots_raw:
            self.rag_allowed_roots = [Path(p.strip()) for p in roots_raw.split(";") if p.strip()]
        else:
            self.rag_allowed_roots = [data_dir]

        # File-system access (DANGEROUS if misconfigured). Disabled by default.
        # If enabled, endpoints under /v1/fs/* can read/write files.
        self.fs_enabled = os.getenv("SOL_FS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
        self.fs_allow_all_paths = os.getenv("SOL_FS_ALLOW_ALL", "false").strip().lower() in ("1", "true", "yes", "on")
        fs_roots_raw = os.getenv("SOL_FS_ALLOWED_ROOTS", "").strip()
        if fs_roots_raw:
            self.fs_allowed_roots = [Path(p.strip()) for p in fs_roots_raw.split(";") if p.strip()]
        else:
            self.fs_allowed_roots = [data_dir]
        self.fs_write_enabled = os.getenv("SOL_FS_WRITE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
        self.fs_delete_enabled = os.getenv("SOL_FS_DELETE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
        deny_raw = os.getenv("SOL_FS_WRITE_DENY_DRIVES", "C").strip()
        if deny_raw:
            self.fs_write_deny_drives = [d.strip().upper().rstrip(":") for d in deny_raw.replace(",", ";").split(";") if d.strip()]
        else:
            self.fs_write_deny_drives = ["C"]
        self.fs_max_read_bytes = int(os.getenv("SOL_FS_MAX_READ_BYTES", "200000"))
        self.fs_max_write_bytes = int(os.getenv("SOL_FS_MAX_WRITE_BYTES", "200000"))

        # Web access (DANGEROUS if exposed publicly). Disabled by default.
        #
        # When enabled, the server can fetch URLs for the chat model (tool use).
        # For public deployments, prefer a strict allowlist and keep private-network blocking ON.
        self.web_enabled = os.getenv("SOL_WEB_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
        self.web_allow_all_hosts = os.getenv("SOL_WEB_ALLOW_ALL", "false").strip().lower() in ("1", "true", "yes", "on")
        allowed_hosts_raw = os.getenv("SOL_WEB_ALLOWED_HOSTS", "").strip()
        if allowed_hosts_raw:
            self.web_allowed_hosts = [h.strip() for h in allowed_hosts_raw.split(";") if h.strip()]
        else:
            # Safe-ish defaults: no general web browsing unless explicitly allowed.
            self.web_allowed_hosts = ["duckduckgo.com", "wikipedia.org"]
        self.web_block_private_networks = os.getenv("SOL_WEB_BLOCK_PRIVATE", "true").strip().lower() in ("1", "true", "yes", "on")
        self.web_timeout_s = float(os.getenv("SOL_WEB_TIMEOUT_S", "10"))
        self.web_max_bytes = int(os.getenv("SOL_WEB_MAX_BYTES", "400000"))
        self.web_user_agent = os.getenv("SOL_WEB_USER_AGENT", "SolWebAccess/0.1")
        self.web_max_redirects = int(os.getenv("SOL_WEB_MAX_REDIRECTS", "5"))
        self.web_max_search_results = int(os.getenv("SOL_WEB_MAX_SEARCH_RESULTS", "5"))

        # OpenAI tool loop safety.
        self.openai_tool_max_iters = int(os.getenv("SOL_OPENAI_TOOL_MAX_ITERS", "4"))

        # Limits for model-driven RAG writes (protect disk + prevent accidental dumps).
        self.rag_tool_max_chars = int(os.getenv("SOL_RAG_TOOL_MAX_CHARS", "8000"))

        # Ollama "tool calling" (best-effort text protocol) for local models.
        # Disabled by default because many models do not reliably follow tool schemas.
        self.ollama_tools_enabled = os.getenv("SOL_OLLAMA_TOOLS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
        self.ollama_tool_max_iters = int(os.getenv("SOL_OLLAMA_TOOL_MAX_ITERS", "4"))

    def _load_auth_users(self) -> dict[str, str]:
        raw_users = (os.getenv("SOL_AUTH_USERS_JSON") or "").strip()
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

        user = (os.getenv("SOL_AUTH_USER") or "nexus").strip().lower() or "nexus"
        password_sha256 = (os.getenv("SOL_AUTH_PASSWORD_SHA256") or "").strip().lower()
        password = os.getenv("SOL_AUTH_PASSWORD")
        if not password_sha256 and password:
            password_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return {user: password_sha256 or _LEGACY_DEFAULT_PASSWORD_SHA256}


config = ApiConfig()
