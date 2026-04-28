from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agentx.config import AgentXConfig
from agentx.core.audit import AuditLog
from agentx.core.journal import Journal
from agentx.core.runtime_models import ArtifactContext, PendingAction
from agentx.install.local_profile import LocalProfile


ConfirmFn = Callable[[str], bool]


@dataclass
class AgentXContext:
    cfg: AgentXConfig
    journal: Journal
    audit: AuditLog
    confirm: ConfirmFn
    web_session_thread_id: str | None = None
    web_session_user: str | None = None
    local_profile: LocalProfile | None = None
    default_memory_namespace: str = "user.local-user"
    web_session_allowed_domains: frozenset[str] = frozenset()
    # Optional runtime backrefs for orchestration tools (e.g., selfcheck).
    # Tools must remain safe even when these are absent.
    tool_registry: Any | None = None
    agent: Any | None = None
    runtime: Any | None = None
    plugin_manager: Any | None = None
    skill_manager: Any | None = None
    hint_store: Any | None = None
    job_store: Any | None = None
    working_memory_manager: Any | None = None
    working_memory: Any | None = None
    request_unsafe_enabled: bool | None = None
    request_agent_mode: str | None = None
    request_artifact_context: ArtifactContext | None = None
    pending_action: PendingAction | None = None
