from __future__ import annotations

from pathlib import Path
import pytest

from sol.config import load_config
from sol.core.action_policy import ActionSelectionPolicy
from sol.core.agent import Agent
from sol.core.audit import AuditLog
from sol.core.context import SolContext
from sol.core.memory_policy import MemoryPromotionPolicy
from sol.core.journal import Journal
from sol.core.runtime_models import Plan, PlanStep
from sol.core.working_memory import WorkingMemoryManager
from sol.jobs.runner import JobRunner
from sol.jobs.storage import JobStore
from sol.plugins.manager import PluginManager
from sol.runtime.paths import build_runtime_paths, ensure_runtime_dirs
from sol.skills.manager import SkillManager
from sol.core.unsafe_mode import disable as disable_unsafe
from sol.core.unsafe_mode import enable as enable_unsafe
from sol.tools.base import Tool
from sol.tools.fs import FsDeleteTool, FsGrepTool, FsReadTool, FsWriteTool
from sol.tools.registry import ToolRegistry

from conftest import write_test_config


class EchoTool(Tool):
    name = "debug.echo"
    description = "Echoes text"

    def run(self, ctx, args: dict):
        return {"echo": "ok"}


class FailTool(Tool):
    name = "debug.fail"
    description = "Fails"

    def run(self, ctx, args: dict):
        raise RuntimeError("validation blocked")


class WebFetchLikeTool(Tool):
    name = "web.fetch"
    description = "Fetches web text"
    safety_flags = ("network",)

    def run(self, ctx, args: dict):
        return {"url": "https://example.com", "text": "x" * 200}


def _build_agent(tmp_path: Path) -> tuple[Agent, ToolRegistry, object, object]:
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
    registry.register(EchoTool())
    registry.register(FailTool())
    registry.register(WebFetchLikeTool())
    agent = Agent.create(ctx=ctx, tools=registry)
    return agent, registry, cfg, runtime_paths


def _prepare_fs_write_agent(tmp_path: Path) -> tuple[Agent, Path]:
    agent, registry, _cfg, _runtime_paths = _build_agent(tmp_path)
    work_dir = agent.ctx.cfg.paths.working_dir.resolve(strict=False)
    work_dir.mkdir(parents=True, exist_ok=True)
    object.__setattr__(agent.ctx.cfg.fs, "allowed_roots", (work_dir, agent.ctx.cfg.paths.app_root.resolve(strict=False)))
    object.__setattr__(agent.ctx.cfg.fs, "deny_drive_letters", tuple())
    object.__setattr__(agent.ctx.cfg.fs, "denied_substrings", tuple())
    registry.register(FsWriteTool())
    registry.register(FsReadTool())
    registry.register(FsDeleteTool())
    registry.register(FsGrepTool())
    return agent, work_dir


def test_run_tool_and_execute_share_working_memory(tmp_path: Path) -> None:
    agent, _registry, _cfg, _runtime_paths = _build_agent(tmp_path)

    run_tool_result = agent.run_tool(tool_name="debug.echo", tool_args={}, reason="Test tool path")
    assert run_tool_result.ok is True
    assert agent.ctx.working_memory.goal == "Run tool debug.echo"
    assert agent.ctx.working_memory.recent_tool_outputs[-1]["tool"] == "debug.echo"

    plan = Plan(steps=(PlanStep(tool_name="debug.echo", arguments={}, reason="Test execute path"),))
    execute_results = agent.execute(plan)
    assert execute_results[-1].ok is True
    assert agent.ctx.working_memory.active_plan[-1]["tool"] == "debug.echo"
    assert agent.ctx.working_memory.recent_tool_outputs[-1]["tool"] == "debug.echo"


def test_execute_uses_explicit_memory_promotion_policy(tmp_path: Path, monkeypatch) -> None:
    agent, _registry, _cfg, _runtime_paths = _build_agent(tmp_path)
    captured: list[str] = []

    def _capture(*, tool, args, output):
        captured.append(tool.name)

    monkeypatch.setattr(agent.memory_policy, "promote_tool_result", _capture)
    plan = Plan(steps=(PlanStep(tool_name="debug.echo", arguments={}, reason="Test promotion"),))
    results = agent.execute(plan)
    assert results[-1].ok is True
    assert captured == ["debug.echo"]


def test_job_runner_binds_per_job_working_memory(tmp_path: Path) -> None:
    agent, registry, cfg, runtime_paths = _build_agent(tmp_path)
    store = JobStore(cfg=cfg, runtime_paths=runtime_paths)
    runner = JobRunner(
        agent=agent,
        store=store,
        plugin_manager=PluginManager(cfg=cfg, runtime_paths=runtime_paths),
        skill_manager=SkillManager(cfg=cfg, runtime_paths=runtime_paths),
        hint_store=None,
    )

    job = runner.create_job(goal="Run a debug job")
    runner._bind_working_memory(job)
    assert agent.ctx.working_memory.job_id == job.job_id
    assert agent.ctx.working_memory.scope_id.endswith(job.job_id)
    assert registry.get_tool("debug.echo") is not None


def test_action_policy_reuses_recent_result(tmp_path: Path) -> None:
    agent, _registry, _cfg, _runtime_paths = _build_agent(tmp_path)
    wm = agent.ctx.working_memory
    wm.begin(goal="What is in the repo?")
    wm.set_summary("I already checked the repo and found the answer.")
    wm.append_result(tool="fs.list", ok=True, summary="repo files listed", output={"path": "F:/repo"})
    decision = ActionSelectionPolicy(agent=agent).choose_chat_action(
        user_text="What is in the repo?",
        retrieved=[],
        working_memory=wm,
        explicit_plan=Plan(steps=tuple()),
    )
    assert decision.use_recent_result is True
    assert decision.action == "reuse_recent_result"


def test_execute_plan_blocks_repeated_hard_failure(tmp_path: Path) -> None:
    agent, _registry, _cfg, _runtime_paths = _build_agent(tmp_path)
    plan = Plan(steps=(PlanStep(tool_name="debug.fail", arguments={}, reason="Repeat hard failure"),))
    first = agent.execute(plan)
    second = agent.execute(plan)
    assert first[0].ok is False
    assert second[0].skipped is True
    assert "already failed" in str(second[0].error).lower()


def test_memory_promotion_policy_filters_transient_noise(tmp_path: Path, monkeypatch) -> None:
    agent, registry, _cfg, _runtime_paths = _build_agent(tmp_path)
    object.__setattr__(agent.ctx.cfg.memory, "enabled", True)
    policy = MemoryPromotionPolicy(agent=agent)
    captured: list[str] = []
    monkeypatch.setattr(agent, "_post_tool_memory_legacy", lambda *, tool, args, output: captured.append(tool.name))

    policy.promote_tool_result(tool=registry.get_tool("debug.echo"), args={}, output={"echo": "ok"})
    policy.promote_tool_result(tool=registry.get_tool("web.fetch"), args={}, output={"url": "https://example.com", "text": "short"})
    policy.promote_tool_result(tool=registry.get_tool("web.fetch"), args={}, output={"url": "https://example.com", "text": "x" * 200})

    assert captured == ["web.fetch"]


@pytest.mark.parametrize(
    ("prompt", "expected_name", "expected_content"),
    [
        ("create a file named demo.txt with content hello", "demo.txt", "hello"),
        ('create a new file called pythoncode.py with content print("hello")', "pythoncode.py", 'print("hello")'),
        ('create TimeZone.py and put this in it: print("hello")', "TimeZone.py", 'print("hello")'),
        ("create a file named notes.md", "notes.md", ""),
    ],
)
def test_chat_honors_requested_filename_for_create_prompts(tmp_path: Path, prompt: str, expected_name: str, expected_content: str) -> None:
    agent, work_dir = _prepare_fs_write_agent(tmp_path)

    result = agent.chat(
        user_message=prompt,
        provider="stub",
        model="stub",
        thread_id="thread-1",
    )

    created = work_dir / expected_name
    assert created.exists()
    assert created.read_text(encoding="utf-8") == expected_content
    assert not (work_dir / "named").exists()
    assert result.ok is True
    assert result.tool_results
    assert result.tool_results[0].tool == "fs.write_text"
    assert result.tool_results[0].output["path"] == str(created)
    assert "Tool execution results:" in result.text


def test_chat_edit_replaces_existing_file_contents(tmp_path: Path) -> None:
    agent, work_dir = _prepare_fs_write_agent(tmp_path)
    target = work_dir / "demo.txt"
    target.write_text("old value", encoding="utf-8")
    enable_unsafe("thread-1", reason="Allow overwrite in test", user="tester", cfg=agent.ctx.cfg)
    try:
        result = agent.chat(
            user_message="edit demo.txt and replace its contents with hello again",
            provider="stub",
            model="stub",
            thread_id="thread-1",
        )
    finally:
        disable_unsafe("thread-1", reason="Reset test state", user="tester", cfg=agent.ctx.cfg)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello again"
    assert result.ok is True
    assert result.tool_results
    assert result.tool_results[0].tool == "fs.write_text"
    assert result.tool_results[0].output["path"] == str(target)


def test_chat_canvas_artifact_with_filename_writes_file(tmp_path: Path) -> None:
    agent, work_dir = _prepare_fs_write_agent(tmp_path)
    agent.ctx.request_active_artifact = {
        "type": "code",
        "language": "python",
        "content": 'print("hello from canvas")\n',
        "source": "canvas",
        "is_dirty": True,
        "title": "Canvas Draft",
    }

    result = agent.chat(
        user_message="save this code as demo.py",
        provider="stub",
        model="stub",
        thread_id="thread-1",
    )

    target = work_dir / "demo.py"
    assert result.ok is True
    assert target.exists()
    assert target.read_text(encoding="utf-8") == 'print("hello from canvas")\n'
    assert result.tool_results
    assert result.tool_results[0].tool == "fs.write_text"
    assert result.tool_results[0].args["path"] == str(target)


def test_chat_canvas_artifact_without_filename_requests_only_filename(tmp_path: Path) -> None:
    agent, _work_dir = _prepare_fs_write_agent(tmp_path)
    agent.ctx.request_active_artifact = {
        "type": "code",
        "language": "python",
        "content": 'print("hello from canvas")\n',
        "source": "canvas",
    }

    result = agent.chat(
        user_message="save what's in canvas",
        provider="stub",
        model="stub",
        thread_id="thread-1",
    )

    assert result.ok is False
    assert result.tool_results == tuple()
    assert result.text == "What filename should I save this as?"


def test_chat_save_code_without_canvas_keeps_missing_content_failure(tmp_path: Path) -> None:
    agent, _work_dir = _prepare_fs_write_agent(tmp_path)

    result = agent.chat(
        user_message="save this code",
        provider="stub",
        model="stub",
        thread_id="thread-1",
    )

    assert result.ok is False
    assert result.tool_results == tuple()
    assert "Missing required arguments: target path, file content" in result.text


def test_posix_absolute_write_prompt_is_tool_addressable(tmp_path: Path) -> None:
    agent, work_dir = _prepare_fs_write_agent(tmp_path)
    prompt = "create a file at /home/nexus/demo.txt with content hello"

    assert agent._extract_write_path(prompt) == "/home/nexus/demo.txt"
    assert agent._extract_path(prompt) == "/home/nexus/demo.txt"
    assert agent._request_is_tool_addressable(prompt) is True
    forced = agent._plan_for_tool_authority(prompt)
    assert forced
    assert forced[0].tool_name == "fs.write_text"
    assert forced[0].arguments["path"].endswith(str(Path("home") / "nexus" / "demo.txt"))
    assert not (work_dir / "at").exists()


def test_request_assessment_distinguishes_modes_and_tool_requirements(tmp_path: Path) -> None:
    agent, work_dir = _prepare_fs_write_agent(tmp_path)
    (work_dir / "demo.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "planner_runtime.py").write_text("DELETE_TOOL = 'fs.delete'\n", encoding="utf-8")

    discuss = agent.assess_request("How should we structure deletes?")
    inspect = agent.assess_request("Inspect the repo and tell me where delete is implemented")
    execute = agent.assess_request("delete demo.txt")
    transform = agent.assess_request('create a file named demo.txt with content hello')
    plan = agent.assess_request("Design a safer orchestrator")

    assert discuss.mode in {"discuss", "plan"}
    assert discuss.requires_tools is False
    assert inspect.mode == "inspect"
    assert inspect.requires_tools is True
    assert inspect.intent == "repo_inspect"
    assert execute.mode == "execute"
    assert execute.requires_tools is True
    assert transform.mode == "transform"
    assert transform.requires_tools is True
    assert plan.mode == "plan"
    assert plan.requires_tools is False


def test_chat_read_uses_structured_tool_result_and_blocks_fake_fallback(tmp_path: Path, monkeypatch) -> None:
    agent, work_dir = _prepare_fs_write_agent(tmp_path)
    target = work_dir / "demo.txt"
    target.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(agent, "_run_llm_chat_audited", lambda **_: "I can't access your files.")
    result = agent.chat(user_message="read demo.txt", provider="stub", model="stub", thread_id="thread-1")

    assert result.ok is True
    assert result.tool_results
    tool_result = result.tool_results[0]
    assert tool_result.tool == "fs.read_text"
    assert tool_result.args["path"] == str(target)
    assert tool_result.result["content"] == "hello"
    assert tool_result.error_info is None
    assert "I can't access your files" not in result.text
    assert "Read:" in result.text
    assert "hello" in result.text


def test_chat_package_json_question_uses_file_read_tool(tmp_path: Path) -> None:
    agent, work_dir = _prepare_fs_write_agent(tmp_path)
    target = work_dir / "package.json"
    target.write_text('{"name":"demo"}', encoding="utf-8")

    result = agent.chat(user_message="what is in package.json?", provider="stub", model="stub", thread_id="thread-1")

    assert result.ok is True
    assert result.tool_results
    tool_result = result.tool_results[0]
    assert tool_result.tool == "fs.read_text"
    assert tool_result.args["path"] == str(target)
    assert tool_result.result["content"] == '{"name":"demo"}'
    assert "fs.read_text: OK" in result.text


def test_chat_missing_read_target_returns_grounded_failure_without_llm_guess(tmp_path: Path, monkeypatch) -> None:
    agent, _work_dir = _prepare_fs_write_agent(tmp_path)
    monkeypatch.setattr(agent, "_run_llm_chat_audited", lambda **_: "Invented answer")

    result = agent.chat(user_message="show the file I just created", provider="stub", model="stub", thread_id="thread-1")

    assert result.ok is False
    assert result.tool_results == tuple()
    assert "could not be determined" in result.text.lower() or "missing required arguments" in result.text.lower()
    assert "Invented answer" not in result.text


def test_chat_missing_file_read_returns_structured_not_found(tmp_path: Path) -> None:
    agent, _work_dir = _prepare_fs_write_agent(tmp_path)

    result = agent.chat(user_message="read missing.txt", provider="stub", model="stub", thread_id="thread-1")

    assert result.ok is False
    assert result.tool_results
    tool_result = result.tool_results[0]
    assert tool_result.tool == "fs.read_text"
    assert tool_result.error_info is not None
    assert tool_result.error_info.code == "not_found"
    assert "File not found." in result.text
    assert "fs.read_text: FAILED" in result.text


def test_execute_delete_failure_returns_structured_error(tmp_path: Path) -> None:
    agent, work_dir = _prepare_fs_write_agent(tmp_path)
    enable_unsafe("thread-1", reason="Allow delete in test", user="tester", cfg=agent.ctx.cfg)
    try:
        result = agent.chat(user_message="delete demo.txt", provider="stub", model="stub", thread_id="thread-1")
    finally:
        disable_unsafe("thread-1", reason="Reset delete test state", user="tester", cfg=agent.ctx.cfg)

    assert result.ok is False
    assert result.tool_results
    tool_result = result.tool_results[0]
    assert tool_result.tool == "fs.delete"
    assert tool_result.error_info is not None
    assert tool_result.error_info.code == "not_found"
    assert not (work_dir / "demo.txt").exists()
    assert "deleted" not in result.text.lower()


def test_chat_repo_lookup_reads_ranked_files_and_explains_from_code(tmp_path: Path) -> None:
    agent, _work_dir = _prepare_fs_write_agent(tmp_path)
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

    result = agent.chat(
        user_message="where is delete implemented and how does it work",
        provider="stub",
        model="stub",
        thread_id="thread-1",
    )

    assert result.ok is True
    assert len(result.tool_results) >= 2
    grep_result = result.tool_results[0]
    assert grep_result.tool == "fs.grep"
    assert grep_result.args["query"] == "fs.delete"
    hits = grep_result.result["hits"]
    assert isinstance(hits, list) and hits
    hit_paths = {hit["path"] for hit in hits}
    assert str(primary_repo_file) in hit_paths
    assert str(secondary_repo_file) in hit_paths
    read_results = [tool_result for tool_result in result.tool_results if tool_result.tool == "fs.read_text" and tool_result.ok]
    assert read_results
    assert read_results[0].args["path"] == str(primary_repo_file)
    assert "Repo search:" in result.text
    assert "Grounded repo analysis:" in result.text
    assert 'DELETE_TOOL = "fs.delete"' in result.text
    assert "def perform_delete(target: str)" in result.text
