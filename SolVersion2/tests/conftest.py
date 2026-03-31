from __future__ import annotations

from pathlib import Path


def write_test_config(root: Path) -> Path:
    cfg_dir = root / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir = root / "plugins"
    skills_dir = root / "skills"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    content = """
mode = "supervised"

[agent]
mode = "supervised"
max_steps = 8
refuse_unattended = true
auto_tools = true
auto_web_verify = false

[audit]
log_path = "logs/sol_audit.jsonl"

[paths]
data_dir = "data"
logs_dir = "logs"
runtime_dir = "data/runtime"
plugins_dir = "plugins"
skills_dir = "skills"
features_dir = "Server/data/features"

[memory]
enabled = false
backend = "sqlite_fts"
db_path = "data/rag.sqlite3"
events_path = "data/memory_events.jsonl"
chunk_chars = 1200
chunk_overlap_chars = 200
k_default = 8

[fs]
allowed_roots = ["F:/", "D:/", "E:/"]
deny_drive_letters = ["C"]
denied_substrings = ["windows", "system32", "appdata", ".ssh", ".gnupg"]
denied_path_patterns = []
max_read_bytes = 200000
max_write_bytes = 200000
max_delete_count = 10

[exec]
enabled = true
timeout_s = 30
allowed_commands = ["python"]
allow_shell = false
deny_extensions = [".exe", ".bat", ".cmd", ".ps1"]

[web]
enabled = false
allow_all_hosts = false
allowed_host_suffixes = []
block_private_networks = true
timeout_s = 10
max_bytes = 400000
user_agent = "SolVersion2/0.1"
max_redirects = 5
max_search_results = 5
allowed_domains = []

[web.policy]
allow_all_hosts = false
allowed_suffixes = []
allowed_domains = []
denied_domains = []

[tibia.sources]
enabled = false
default_delay_ms = 500
max_threads = 5
max_pages_per_thread = 5

[rag]
enabled = false
db_path = "data/rag.sqlite3"
top_k = 5
chunk_chars = 1200
chunk_overlap_chars = 200

[voice]
enabled = false
wake_word_enabled = false
wake_word = "sol"
mic_device = ""

[vision]
enabled = false
device_index = 0

[llm]
provider = "stub"
"""
    path = cfg_dir / "sol.toml"
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path
