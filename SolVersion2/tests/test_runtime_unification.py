from __future__ import annotations

from pathlib import Path

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
from sol.tools.base import Tool
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
