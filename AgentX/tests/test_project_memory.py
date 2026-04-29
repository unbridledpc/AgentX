from __future__ import annotations

from pathlib import Path

from agentx.config import load_config
from agentx.core.memory import Memory
from agentx.core.project_memory import Durability, MemoryKind, MemoryScope, ProjectMemoryStore
from agentx.core.reflection import TaskReflection, infer_modules, render_reflection, save_reflection_to_memory


def _write_config(root: Path) -> Path:
    cfg_dir = root / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg_dir / "agentx.toml"
    cfg.write_text(
        f'''
mode = "supervised"

[agent]
mode = "supervised"
max_steps = 8
refuse_unattended = true
auto_tools = true
auto_web_verify = false

[audit]
log_path = "logs/agentx_audit.jsonl"

[paths]
data_dir = "data"
logs_dir = "logs"
runtime_dir = "data/runtime"
plugins_dir = "plugins"
skills_dir = "skills"
features_dir = "Server/data/features"

[memory]
enabled = true
backend = "sqlite_fts"
db_path = "data/rag.sqlite3"
events_path = "data/memory_events.jsonl"
chunk_chars = 1200
chunk_overlap_chars = 200
k_default = 8

[fs]
allowed_roots = ["{root.as_posix()}"]
deny_drive_letters = []
denied_substrings = []
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
user_agent = "AgentX/0.1"
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
enabled = true
db_path = "data/rag.sqlite3"
top_k = 5
chunk_chars = 1200
chunk_overlap_chars = 200

[voice]
enabled = false
wake_word_enabled = false
wake_word = "agentx"
mic_device = ""

[vision]
enabled = false
device_index = 0

[llm]
provider = "stub"
'''.strip()
        + "\n",
        encoding="utf-8",
    )
    return cfg


def test_project_memory_add_retrieve_and_context_stack(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config(str(_write_config(tmp_path)))
    memory = Memory(cfg)
    ok, err = memory.ensure_writable()
    assert ok, err

    entry = memory.add_project_memory(
        title="Draft Workspace promotion rule",
        summary="Draft Workspace notes can be promoted into scoped project memory after user approval.",
        scope="module",
        kind="module_note",
        durability="high",
        module="draft_workspace",
        affected_files=["AgentX/core/project_memory.py"],
        tags=["drafts"],
    )
    assert entry.scope is MemoryScope.MODULE
    assert entry.kind is MemoryKind.MODULE_NOTE
    assert entry.durability is Durability.HIGH

    hits = memory.retrieve_project_memory("promoted scoped project memory", module="draft_workspace")
    assert hits
    assert hits[0].entry.entry_id == entry.entry_id

    stack = memory.project_context_stack(task="promote draft notes", module="draft_workspace", files=["AgentX/core/project_memory.py"])
    assert stack["module"]
    assert stack["module"][0]["entry"]["module"] == "draft_workspace"

    stats = memory.stats()
    assert stats["project_memory"]["entry_count"] == 1


def test_raw_ingest_distills_and_lists_project_memory(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config(str(_write_config(tmp_path)))
    store = ProjectMemoryStore(cfg)
    entry = store.ingest_raw(
        source_id="task-log:123",
        text="""
        DEBUG: this line should not be kept
        Decision: use scoped memory layers instead of one flat RAG dump.
        Affected module: knowledge_base.
        """,
        meta={"module": "knowledge_base", "affected_files": ["AgentX/core/memory.py"]},
    )
    assert entry.module == "knowledge_base"
    assert "DEBUG" not in entry.summary
    entries = store.list_entries(module="knowledge_base")
    assert len(entries) == 1


def test_task_reflection_saves_task_and_module_entries(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config(str(_write_config(tmp_path)))
    store = ProjectMemoryStore(cfg)
    reflection = TaskReflection(
        task_id="job-1",
        goal="Add Phase 1 project memory",
        summary="Added scoped project memory entries and context-stack retrieval.",
        changed=["Implemented ProjectMemoryStore"],
        affected_files=["AgentX/core/project_memory.py", "AgentX/core/memory.py"],
        affected_modules=infer_modules(["AgentX/core/project_memory.py", "AgentX/core/memory.py"]),
        decisions=["Use existing SQLite FTS store with project-memory metadata."],
        durable_knowledge=["Project memory entries are stored as structured metadata and searchable FTS content."],
        docs_update_needed=True,
        changelog_update_needed=True,
    )
    text = render_reflection(reflection)
    assert "Durable knowledge" in text
    entries = save_reflection_to_memory(store, reflection)
    assert len(entries) >= 2
    hits = store.retrieve("SQLite FTS project-memory metadata", scopes=["decision", "task", "module"])
    assert hits
