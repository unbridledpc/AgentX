from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionDecision:
    action: str
    reason: str
    evidence: tuple[str, ...] = tuple()
    use_plan: bool = False
    use_recent_result: bool = False
    use_llm: bool = False
    use_retrieval_context: bool = False
    require_clarification: bool = False
    stop_after_tools: bool = False


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    reason: str
    category: str


class ActionSelectionPolicy:
    def __init__(self, *, agent) -> None:
        self.agent = agent

    def choose_chat_action(
        self,
        *,
        user_text: str,
        retrieved: list[Any],
        working_memory,
        explicit_plan,
        assessment=None,
    ) -> ActionDecision:
        text = (user_text or "").strip()
        if not text:
            return ActionDecision(action="direct_answer", reason="No user text provided.", use_llm=True)

        if assessment is not None and tuple(getattr(assessment, "missing_arguments", ()) or ()):
            return ActionDecision(
                action="clarify_or_block",
                reason="Missing required arguments: " + ", ".join(str(x) for x in assessment.missing_arguments),
                evidence=tuple(getattr(assessment, "evidence", ()) or ()),
                require_clarification=True,
            )

        if self._can_reuse_recent_answer(text=text, working_memory=working_memory):
            return ActionDecision(
                action="reuse_recent_result",
                reason="Recent working-memory result already matches this request.",
                evidence=("working_memory.summary",),
                use_recent_result=True,
            )

        if explicit_plan.steps:
            return ActionDecision(
                action="run_plan",
                reason="Existing planner produced executable tool steps.",
                evidence=("plan.steps",),
                use_plan=True,
            )

        if assessment is not None and str(getattr(assessment, "mode", "") or "") == "plan":
            return ActionDecision(
                action="design_response",
                reason="Request is asking to design or define a tool/skill, not execute one.",
                evidence=tuple(getattr(assessment, "evidence", ()) or ("tool_design_request",)),
                use_llm=True,
                use_retrieval_context=bool(retrieved),
            )

        if self.agent._is_time_sensitive_query(text) and bool(self.agent.ctx.cfg.agent.auto_web_verify) and bool(self.agent.ctx.cfg.web.enabled):
            return ActionDecision(
                action="web_verify",
                reason="Request appears freshness-sensitive and web verification is enabled.",
                evidence=("time_sensitive_query", "web.enabled", "agent.auto_web_verify"),
                use_plan=True,
            )

        if assessment is not None and bool(getattr(assessment, "requires_tools", False)):
            allowed, why = self.agent._tool_authority_allowed_status(text)
            if allowed:
                return ActionDecision(
                    action="run_plan",
                    reason="Request is tool-addressable and allowed by policy.",
                    evidence=tuple(getattr(assessment, "evidence", ()) or ("tool_authority",)),
                    use_plan=True,
                )
            return ActionDecision(
                action="clarify_or_block",
                reason=why,
                evidence=tuple(getattr(assessment, "evidence", ()) or ("tool_authority_blocked",)),
                require_clarification=True,
            )

        if self.agent._request_is_tool_addressable(text):
            allowed, why = self.agent._tool_authority_allowed_status(text)
            if allowed:
                return ActionDecision(
                    action="run_plan",
                    reason="Request is tool-addressable and allowed by policy.",
                    evidence=("tool_authority",),
                    use_plan=True,
                )
            return ActionDecision(
                action="clarify_or_block",
                reason=why,
                evidence=("tool_authority_blocked",),
                require_clarification=True,
            )

        if retrieved and not self.agent._is_time_sensitive_query(text):
            return ActionDecision(
                action="answer_with_memory",
                reason="Trusted retrieved context is already available for a non-freshness-sensitive question.",
                evidence=("retrieved_context",),
                use_llm=True,
                use_retrieval_context=True,
            )

        return ActionDecision(
            action="direct_answer",
            reason="No stronger evidence or tool requirement was detected.",
            evidence=("default_llm",),
            use_llm=True,
            use_retrieval_context=bool(retrieved),
        )

    def check_retry(self, *, step, working_memory) -> RetryDecision:
        if working_memory is None:
            return RetryDecision(allowed=True, reason="No working memory available.", category="unknown")

        signature = self.step_signature(step)
        prior = [item for item in (working_memory.failures or []) if item.get("signature") == signature]
        if not prior:
            return RetryDecision(allowed=True, reason="No prior failure for this exact action.", category="new")

        latest = prior[-1]
        category = str(latest.get("category") or "execution").strip().lower() or "execution"
        if category == "transient" and len(prior) < 2:
            return RetryDecision(allowed=True, reason="One retry allowed for transient failure.", category=category)
        if category in {"policy", "validation", "approval_denied"}:
            return RetryDecision(allowed=False, reason="Same action already failed with a hard non-retryable category.", category=category)
        if len(prior) >= 2:
            return RetryDecision(allowed=False, reason="Same action already failed repeatedly without changed conditions.", category=category)
        return RetryDecision(allowed=False, reason="Same action already failed once and there is no new evidence to retry.", category=category)

    @staticmethod
    def categorize_failure(error: str | None) -> str:
        low = str(error or "").strip().lower()
        if not low:
            return "execution"
        if "timeout" in low or "tempor" in low or "network" in low or "http 5" in low:
            return "transient"
        if "policy" in low or "unsafe" in low or "blocked" in low:
            return "policy"
        if "missing required argument" in low or "unknown arguments" in low or "expected" in low:
            return "validation"
        if "denied" in low or "approval" in low or "confirm" in low:
            return "approval_denied"
        return "execution"

    @staticmethod
    def step_signature(step) -> str:
        tool = str(getattr(step, "tool_name", "") or "").strip().lower()
        reason = str(getattr(step, "reason", "") or "").strip().lower()
        args = getattr(step, "arguments", {}) or {}
        normalized = []
        for key in sorted(args.keys()):
            value = args[key]
            normalized.append(f"{key}={ActionSelectionPolicy._stable_value(value)}")
        return f"{tool}|{reason}|{'|'.join(normalized)}"

    @staticmethod
    def _stable_value(value: Any) -> str:
        if isinstance(value, dict):
            inner = ",".join(f"{k}:{ActionSelectionPolicy._stable_value(value[k])}" for k in sorted(value.keys()))
            return "{" + inner + "}"
        if isinstance(value, list):
            return "[" + ",".join(ActionSelectionPolicy._stable_value(v) for v in value) + "]"
        return str(value)

    @staticmethod
    def _normalize_text(text: str) -> str:
        out = re.sub(r"\s+", " ", (text or "").strip().lower())
        return out

    def _can_reuse_recent_answer(self, *, text: str, working_memory) -> bool:
        if working_memory is None:
            return False
        if self._normalize_text(text) != self._normalize_text(getattr(working_memory, "goal", "")):
            return False
        if getattr(working_memory, "unresolved_items", None):
            return False
        if not getattr(working_memory, "summary", "").strip():
            return False
        results = list(getattr(working_memory, "recent_tool_outputs", []) or [])
        if not results:
            return False
        return bool(results[-1].get("ok"))
