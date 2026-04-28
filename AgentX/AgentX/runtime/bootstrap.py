from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agentx.config import AgentXConfig, load_config
from agentx.core.agent import Agent
from agentx.core.audit import AuditLog
from agentx.core.context import AgentXContext
from agentx.core.journal import Journal
from agentx.install.local_profile import resolve_local_profile
from agentx.learning.hints import HintStore
from agentx.jobs.storage import JobStore
from agentx.plugins.manager import PluginManager
from agentx.runtime.paths import RuntimePaths, build_runtime_paths, ensure_runtime_dirs
from agentx.skills.manager import SkillManager
from agentx.tools.registry import ToolRegistry, build_default_registry
from agentx.core.working_memory import WorkingMemoryManager


@dataclass(frozen=True)
class RuntimeServices:
    cfg: AgentXConfig
    ctx: AgentXContext
    tools: ToolRegistry
    agent: Agent
    runtime_paths: RuntimePaths
    plugin_manager: PluginManager
    skill_manager: SkillManager
    hint_store: HintStore
    job_store: JobStore


def build_runtime_services(*, cfg: AgentXConfig, confirm: Callable[[str], bool]) -> RuntimeServices:
    cfg.paths.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.logs_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.config_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.run_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.temp_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.audit_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.memory_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.working_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.plugins_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.skills_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.user_plugins_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.user_skills_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.features_dir.mkdir(parents=True, exist_ok=True)

    runtime_paths = build_runtime_paths(cfg)
    ensure_runtime_dirs(runtime_paths)

    audit = AuditLog(cfg.audit.log_path)
    local_profile = resolve_local_profile(cfg.paths.runtime_root)
    ctx = AgentXContext(
        cfg=cfg,
        journal=Journal(cfg),
        audit=audit,
        confirm=confirm,
        web_session_user=local_profile.profile_id,
        local_profile=local_profile,
        default_memory_namespace=local_profile.memory_namespace,
    )

    tools = build_default_registry()
    plugin_manager = PluginManager(cfg=cfg, runtime_paths=runtime_paths)
    plugin_manager.register_enabled_tools(tools)

    skill_manager = SkillManager(cfg=cfg, runtime_paths=runtime_paths)
    hint_store = HintStore(cfg=cfg, runtime_paths=runtime_paths)
    job_store = JobStore(cfg=cfg, runtime_paths=runtime_paths)
    working_memory_manager = WorkingMemoryManager()

    ctx.runtime = runtime_paths
    ctx.plugin_manager = plugin_manager
    ctx.skill_manager = skill_manager
    ctx.hint_store = hint_store
    ctx.job_store = job_store
    ctx.tool_registry = tools
    ctx.working_memory_manager = working_memory_manager
    ctx.working_memory = working_memory_manager.for_scope(user_id=ctx.web_session_user, thread_id=None)

    agent = Agent.create(ctx=ctx, tools=tools)
    ctx.agent = agent

    return RuntimeServices(
        cfg=cfg,
        ctx=ctx,
        tools=tools,
        agent=agent,
        runtime_paths=runtime_paths,
        plugin_manager=plugin_manager,
        skill_manager=skill_manager,
        hint_store=hint_store,
        job_store=job_store,
    )


def build_runtime_services_from_config(*, config_path: str, confirm: Callable[[str], bool]) -> RuntimeServices:
    cfg = load_config(config_path)
    return build_runtime_services(cfg=cfg, confirm=confirm)
