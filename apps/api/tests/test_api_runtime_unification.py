from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace
from pathlib import Path, PurePosixPath

from fastapi.testclient import TestClient

from sol_api.app import create_app
from sol_api.auth import session_store
from sol_api.config import config
from sol_api.rag.session import session_tracker
import sol_api.routes.settings as settings_route
from sol_api.routes.settings import SettingsModel
from sol.config import load_config
from sol.core.agent import Agent
from sol.core.audit import AuditLog
from sol.core.context import SolContext
from sol.core.journal import Journal
from sol.core.unsafe_mode import disable as disable_unsafe
from sol.core.unsafe_mode import enable as enable_unsafe
from sol.core.working_memory import WorkingMemoryManager
from sol.runtime.paths import build_runtime_paths, ensure_runtime_dirs
from sol.tools.fs import FsDeleteTool, FsGrepTool, FsListTool, FsReadTool, FsWriteTool
from sol.tools.registry import ToolRegistry
from conftest import write_test_config


def _auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post("/v1/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _build_live_agent(tmp_path: Path) -> tuple[Agent, Path]:
    write_test_config(tmp_path)
    cfg = load_config(str(tmp_path / "config" / "sol.toml"))
    runtime_paths = build_runtime_paths(cfg)
    ensure_runtime_dirs(runtime_paths)
    wm = WorkingMemoryManager()
    ctx = SolContext(
        cfg=cfg,
        journal=Journal(cfg),
        audit=AuditLog(cfg.audit.log_path),
        confirm=lambda prompt: True,
        web_session_user="tester",
        web_session_thread_id="thread-1",
        working_memory_manager=wm,
        working_memory=wm.for_scope(user_id="tester", thread_id="thread-1"),
    )
    registry = ToolRegistry()
    registry.register(FsWriteTool())
    registry.register(FsReadTool())
    registry.register(FsDeleteTool())
    registry.register(FsListTool())
    registry.register(FsGrepTool())
    agent = Agent.create(ctx=ctx, tools=registry)
    work_dir = agent.ctx.cfg.paths.working_dir.resolve(strict=False)
    work_dir.mkdir(parents=True, exist_ok=True)
    object.__setattr__(agent.ctx.cfg.fs, "allowed_roots", (work_dir, work_dir / "_posix_root", agent.ctx.cfg.paths.app_root.resolve(strict=False)))
    object.__setattr__(agent.ctx.cfg.fs, "deny_drive_letters", tuple())
    object.__setattr__(agent.ctx.cfg.fs, "denied_substrings", tuple())
    posix_root = work_dir / "_posix_root"
    posix_root.mkdir(parents=True, exist_ok=True)
    original_resolve = agent._resolve_fs_path

    def _resolve_for_test(raw: str) -> str:
        value = (raw or "").strip()
        if value.startswith("/"):
            rel = PurePosixPath(value).relative_to(PurePosixPath("/"))
            return str((posix_root.joinpath(*rel.parts)).resolve(strict=False))
        return original_resolve(value)

    agent._resolve_fs_path = _resolve_for_test  # type: ignore[method-assign]
    return agent, work_dir


def test_chat_prefers_solv2_runtime_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    monkeypatch.setattr(config, "auth_enabled", True)
    monkeypatch.setattr(config, "auth_users", {"alice": hashlib.sha256(b"alice-pass").hexdigest()})
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    captured: dict[str, object] = {}

    class _FakeAgent:
        def chat(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text="ok", retrieved=tuple(), sources=tuple(), verification_level=None, verification=None, tool_results=tuple())

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="llama3.2"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), _FakeAgent()))

    client = TestClient(create_app())
    headers = _auth_headers(client)
    response = client.post("/v1/chat", json={"message": "hello", "thread_id": None}, headers=headers)
    assert response.status_code == 200, response.text
    assert captured["user_message"] == "hello"
    assert captured["provider"] == "ollama"
    assert captured["model"] == "llama3.2"


def test_runtime_state_exposes_working_memory_snapshot(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    monkeypatch.setattr(config, "auth_enabled", True)
    monkeypatch.setattr(config, "auth_users", {"alice": hashlib.sha256(b"alice-pass").hexdigest()})
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    class _FakeHandle:
        pass

    class _FakeAgent:
        def runtime_state_snapshot(self):
            return {
                "mode": "supervised",
                "thread_id": "thread-1",
                "user_id": "alice",
                "working_memory": {
                    "goal": "Inspect repo",
                    "current_subgoal": "Execute fs.list",
                    "recent_tool_outputs": [{"tool": "fs.list", "ok": True}],
                    "decisions": [{"action": "run_plan", "reason": "tool-addressable"}],
                },
            }

    monkeypatch.setattr("sol_api.routes.solv2.get_agent_for_thread", lambda thread_id, user=None: (_FakeHandle(), _FakeAgent()))

    client = TestClient(create_app())
    headers = _auth_headers(client)
    response = client.get("/v1/runtime/state", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()["state"]
    assert payload["working_memory"]["goal"] == "Inspect repo"
    assert payload["working_memory"]["decisions"][0]["action"] == "run_plan"


def test_chat_live_route_honors_requested_paths_and_avoids_helper_words(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "auth_enabled", False)
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    agent, work_dir = _build_live_agent(tmp_path)

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="stub", chatModel="stub"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), agent))

    client = TestClient(create_app())

    cases = [
        ("create a file named demo.txt with content hello", work_dir / "demo.txt", "hello"),
        ('create a new file called pythoncode.py with content print("hello")', work_dir / "pythoncode.py", 'print("hello")'),
        ("create a file at /home/nexus/demo.txt with content hello", work_dir / "_posix_root" / "home" / "nexus" / "demo.txt", "hello"),
        ("create /home/nexus/demo2.txt with content hello", work_dir / "_posix_root" / "home" / "nexus" / "demo2.txt", "hello"),
    ]

    for prompt, expected_path, expected_content in cases:
        response = client.post("/v1/chat", json={"message": prompt, "thread_id": None})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "fs.write_text: OK" in payload["content"]
        assert expected_path.exists()
        assert expected_path.read_text(encoding="utf-8") == expected_content

    target = work_dir / "demo.txt"
    target.write_text("before", encoding="utf-8")
    enable_unsafe("thread-1", reason="Allow overwrite in API test", user="tester", cfg=agent.ctx.cfg)
    try:
        response = client.post("/v1/chat", json={"message": "edit demo.txt and replace its contents with hello again", "thread_id": None})
    finally:
        disable_unsafe("thread-1", reason="Reset API test state", user="tester", cfg=agent.ctx.cfg)
    assert response.status_code == 200, response.text
    assert target.read_text(encoding="utf-8") == "hello again"

    assert not (work_dir / "named").exists()
    assert not (work_dir / "at").exists()


def test_chat_live_route_reads_files_via_tools_and_supports_followups(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "auth_enabled", False)
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    agent, work_dir = _build_live_agent(tmp_path)

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="stub", chatModel="stub"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), agent))

    client = TestClient(create_app())

    created = client.post("/v1/chat", json={"message": "create a file named demo.txt with content hello", "thread_id": None})
    assert created.status_code == 200, created.text
    assert (work_dir / "demo.txt").exists()

    posix_created = client.post("/v1/chat", json={"message": "create a file at /home/nexus/demo.txt with content hello", "thread_id": None})
    assert posix_created.status_code == 200, posix_created.text

    read_prompts = [
        "read demo.txt",
        "show me the contents of demo.txt",
        "what is in demo.txt",
        "what is the contents of the file named demo.txt",
        "cat demo.txt",
        "summarize demo.txt",
        "show the file I just created",
        "what is the contents of the file named demo",
    ]
    for prompt in read_prompts:
        response = client.post("/v1/chat", json={"message": prompt, "thread_id": None})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "fs.read_text: OK" in payload["content"]
        assert "hello" in payload["content"]

    posix_read = client.post("/v1/chat", json={"message": "open /home/nexus/demo.txt", "thread_id": None})
    assert posix_read.status_code == 200, posix_read.text
    assert "fs.read_text: OK" in posix_read.json()["content"]
    assert "hello" in posix_read.json()["content"]

    package_file = work_dir / "package.json"
    package_file.write_text('{"name":"demo"}', encoding="utf-8")
    package_read = client.post("/v1/chat", json={"message": "what is in package.json?", "thread_id": None})
    assert package_read.status_code == 200, package_read.text
    assert "fs.read_text: OK" in package_read.json()["content"]
    assert '{"name":"demo"}' in package_read.json()["content"]
    assert not (work_dir / "named").exists()
    assert not (work_dir / "at").exists()


def test_chat_live_route_delete_uses_fs_delete_when_allowed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "auth_enabled", False)
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    agent, work_dir = _build_live_agent(tmp_path)

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="stub", chatModel="stub"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), agent))

    client = TestClient(create_app())
    created = client.post("/v1/chat", json={"message": "create a file named demo.txt with content hello", "thread_id": None})
    assert created.status_code == 200, created.text
    target = work_dir / "demo.txt"
    assert target.exists()

    enable_unsafe("thread-1", reason="Allow delete in API test", user="tester", cfg=agent.ctx.cfg)
    try:
        deleted = client.post("/v1/chat", json={"message": "delete demo.txt", "thread_id": None})
        assert deleted.status_code == 200, deleted.text
        assert "fs.delete: OK" in deleted.json()["content"]
        assert not target.exists()

        recreated = client.post("/v1/chat", json={"message": "create a file named demo.txt with content hello", "thread_id": None})
        assert recreated.status_code == 200, recreated.text
        assert target.exists()

        deleted_followup = client.post("/v1/chat", json={"message": "delete it", "thread_id": None})
        assert deleted_followup.status_code == 200, deleted_followup.text
        assert "fs.delete: OK" in deleted_followup.json()["content"]
        assert not target.exists()
    finally:
        disable_unsafe("thread-1", reason="Reset API delete test state", user="tester", cfg=agent.ctx.cfg)


def test_chat_live_route_clarifies_when_read_target_is_unknown_and_does_not_hallucinate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "auth_enabled", False)
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    agent, _work_dir = _build_live_agent(tmp_path)

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="stub", chatModel="stub"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), agent))

    client = TestClient(create_app())
    response = client.post("/v1/chat", json={"message": "show the file I just created", "thread_id": None})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "fs.read_text: OK" not in payload["content"]
    assert ("could not be determined" in payload["content"].lower()) or ("missing required arguments" in payload["content"].lower())
    assert "hello" not in payload["content"].lower()
    assert "Sol says:" not in payload["content"]


def test_chat_live_route_missing_file_read_returns_grounded_not_found(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "auth_enabled", False)
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    agent, _work_dir = _build_live_agent(tmp_path)

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="stub", chatModel="stub"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), agent))

    client = TestClient(create_app())
    response = client.post("/v1/chat", json={"message": "read missing.txt", "thread_id": None})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "fs.read_text: FAILED" in payload["content"]
    assert "File not found." in payload["content"]
    assert "Sol says:" not in payload["content"]


def test_chat_live_route_repo_inspection_reads_ranked_files_and_explains(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "auth_enabled", False)
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    agent, _work_dir = _build_live_agent(tmp_path)
    primary_repo_file = tmp_path / "delete_runtime.py"
    primary_repo_file.write_text(
        'DELETE_TOOL = "fs.delete"\n\n'
        "def perform_delete(target: str) -> dict[str, str]:\n"
        '    return {"tool": DELETE_TOOL, "target": target}\n',
        encoding="utf-8",
    )
    secondary_repo_file = tmp_path / "planner_runtime.py"
    secondary_repo_file.write_text(
        "def explain_delete() -> str:\n"
        '    return "fs.delete is delegated through perform_delete"\n',
        encoding="utf-8",
    )

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="stub", chatModel="stub"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), agent))

    client = TestClient(create_app())
    response = client.post("/v1/chat", json={"message": "where is delete implemented and how does it work", "thread_id": None})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "fs.grep: OK" in payload["content"]
    assert "fs.read_text: OK" in payload["content"]
    assert str(primary_repo_file) in payload["content"]
    assert str(secondary_repo_file) in payload["content"]
    assert "Grounded repo analysis:" in payload["content"]
    assert 'DELETE_TOOL = "fs.delete"' in payload["content"]
    assert "def perform_delete(target: str)" in payload["content"]
    assert "Sol says:" not in payload["content"]


def test_chat_live_route_design_request_does_not_trigger_filesystem_tools(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "auth_enabled", False)
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    agent, work_dir = _build_live_agent(tmp_path)

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="stub", chatModel="stub"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), agent))

    client = TestClient(create_app())
    prompt = "I need you to design a tool that will allow you to read the contents of files located on the system"
    response = client.post("/v1/chat", json={"message": prompt, "thread_id": None})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "fs.list" not in payload["content"]
    assert "fs.read_text" not in payload["content"]
    assert "fs.write_text" not in payload["content"]
    assert "Could not determine a path to list" not in payload["content"]
    assert "Sol says:" in payload["content"]
    assert not (work_dir / "named").exists()
    assert not (work_dir / "at").exists()
    assert sorted(item.name for item in work_dir.iterdir()) == ["_posix_root"]


def test_chat_live_route_list_files_still_triggers_filesystem_tool(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "auth_enabled", False)
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    agent, work_dir = _build_live_agent(tmp_path)
    target_dir = work_dir / "_posix_root" / "home" / "nexus"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "alpha.txt").write_text("alpha", encoding="utf-8")

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="stub", chatModel="stub"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), agent))

    client = TestClient(create_app())
    response = client.post("/v1/chat", json={"message": "list files in /home/nexus", "thread_id": None})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "fs.list: OK" in payload["content"]
    assert "alpha.txt" in payload["content"]
