from __future__ import annotations

import json
from typing import Any

from agentx.core.action_policy import ActionDecision, ActionSelectionPolicy
from agentx.core.response_sanitizer import finalize_response_text
from agentx.core.result_interpreter import ToolResultInterpreter
from agentx.core.types import VerificationLevel


class RuntimeOrchestrator:
    """Shared runtime path for chat, direct tool calls, and plan execution."""

    def __init__(self, *, agent) -> None:
        self.agent = agent
        self.action_policy = ActionSelectionPolicy(agent=agent)
        self.result_interpreter = ToolResultInterpreter()

    def run_chat(
        self,
        *,
        user_message: str,
        provider: str,
        model: str,
        thread_id: str | None = None,
        response_mode: str = "chat",
    ):
        from agentx.core.runtime_models import AgentResult, Plan

        user_text = (user_message or "").strip()
        if user_text:
            self.agent._memory_add_event(role="user", content=user_text, tags=["trusted:user"], meta={"thread_id": thread_id})

        working_memory = getattr(self.agent.ctx, "working_memory", None)

        retrieved = self.agent._memory_retrieve(user_text) if user_text else []
        context = self.agent._build_retrieval_context(retrieved)

        prov = (provider or "").strip().lower() or str(self.agent.ctx.cfg.llm.get("provider") or "stub").strip().lower()
        mdl = (model or "").strip() or "stub"

        resumed_from_pending = False
        pending = self.agent._pending_action()
        if pending is not None:
            if self.agent._is_pending_action_cancel(user_text):
                self.agent._clear_pending_action()
                msg = "Okay, I canceled that pending action."
                self.agent._memory_add_event(role="assistant", content=msg, tags=["trusted:assistant"], meta={"thread_id": thread_id, "pending_action_cancelled": True})
                if working_memory is not None:
                    working_memory.clear_unresolved()
                return AgentResult(ok=True, plan=Plan(steps=tuple()), text=finalize_response_text(msg, response_mode=response_mode), tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED, verification=None)
            continuation = self.agent._continue_pending_action(user_text, pending=pending)
            if continuation.get("kind") == "execute":
                assessment = continuation["assessment"]
                plan = continuation["plan"]
                decision = ActionDecision(
                    action="run_plan",
                    reason="Resuming pending tool action with supplied clarification.",
                    evidence=("pending_action",),
                    use_plan=True,
                )
                resumed_from_pending = True
                self.agent._clear_pending_action()
            elif continuation.get("kind") == "clarify":
                updated_pending = continuation["pending"]
                msg = str(continuation["prompt"])
                self.agent._set_pending_action(updated_pending)
                self.agent._memory_add_event(role="assistant", content=msg, tags=["trusted:assistant"], meta={"thread_id": thread_id, "pending_action_waiting": True})
                if working_memory is not None:
                    working_memory.note_unresolved(msg)
                return AgentResult(ok=False, plan=Plan(steps=tuple()), text=finalize_response_text(msg, response_mode=response_mode), tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED, verification=None)
            elif continuation.get("kind") == "meta_help":
                msg = str(continuation["message"])
                self.agent._set_pending_action(pending)
                self.agent._memory_add_event(role="assistant", content=msg, tags=["trusted:assistant"], meta={"thread_id": thread_id, "pending_action_help": True})
                if working_memory is not None:
                    working_memory.note_unresolved(msg)
                return AgentResult(ok=False, plan=Plan(steps=tuple()), text=finalize_response_text(msg, response_mode=response_mode), tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED, verification=None)
            elif continuation.get("kind") == "discard" or self.agent._should_discard_pending_action(user_text, pending=pending):
                self.agent._clear_pending_action()
                pending = None
                assessment = self.agent.assess_request(user_text)
                plan = self.agent.plan(user_message)
                decision = self.action_policy.choose_chat_action(
                    user_text=user_text,
                    retrieved=retrieved,
                    working_memory=working_memory,
                    explicit_plan=plan,
                    assessment=assessment,
                )
            else:
                msg = str(getattr(pending, "clarification_prompt", "") or self.agent._pending_action_clarification_prompt(pending))
                self.agent._memory_add_event(role="assistant", content=msg, tags=["trusted:assistant"], meta={"thread_id": thread_id, "pending_action_waiting": True})
                if working_memory is not None:
                    working_memory.note_unresolved(msg)
                return AgentResult(ok=False, plan=Plan(steps=tuple()), text=finalize_response_text(msg, response_mode=response_mode), tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED, verification=None)
        else:
            assessment = self.agent.assess_request(user_text)
            plan = self.agent.plan(user_message)
            decision = self.action_policy.choose_chat_action(
                user_text=user_text,
                retrieved=retrieved,
                working_memory=working_memory,
                explicit_plan=plan,
                assessment=assessment,
            )
        if working_memory is not None:
            working_memory.record_decision(action=decision.action, reason=decision.reason, evidence=list(decision.evidence))

        if decision.use_recent_result and working_memory is not None:
            summary = getattr(working_memory, "summary", "").strip()
            return AgentResult(ok=True, plan=Plan(steps=tuple()), text=summary, tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED)

        if working_memory is not None:
            working_memory.begin(goal=user_text)
            working_memory.record_decision(action=decision.action, reason=decision.reason, evidence=list(decision.evidence))
            working_memory.record_memories_used(
                [
                    {
                        "source_id": str(ch.source_id),
                        "trust": str(ch.trust),
                        "score": float(ch.score) if ch.score is not None else None,
                    }
                    for ch in retrieved[:8]
                ]
            )

        if decision.action == "web_verify" and not plan.steps:
            from agentx.core.runtime_models import Plan as RuntimePlan

            plan = RuntimePlan(steps=tuple(self.agent._plan_web_verify(user_text)))

        if decision.require_clarification:
            pending_action = self.agent._build_pending_action(
                assessment=assessment,
                user_text=user_text,
                thread_id=thread_id,
            )
            if pending_action is not None:
                self.agent._set_pending_action(pending_action)
                msg = self.agent._pending_action_clarification_prompt(pending_action)
            elif not resumed_from_pending:
                self.agent._clear_pending_action()
                if (
                    assessment.intent == "file_write"
                    and tuple(getattr(assessment, "missing_arguments", ()) or ()) == ("target path",)
                    and self.agent._artifact_context() is not None
                ):
                    msg = "What filename should I save this as?"
                elif assessment.intent == "file_write" and tuple(getattr(assessment, "missing_arguments", ()) or ()) in {("file content",), ("replacement content",)}:
                    msg = "What content should I write to the file?"
                else:
                    msg = f"This request requires a tool or approval path that is currently unavailable.\n\nDetails: {decision.reason}"
            self.agent._memory_add_event(role="assistant", content=msg, tags=["trusted:assistant"], meta={"thread_id": thread_id})
            if working_memory is not None:
                working_memory.note_unresolved(decision.reason)
            return AgentResult(ok=False, plan=Plan(steps=tuple()), text=finalize_response_text(msg, response_mode=response_mode), tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED, verification=None)

        if not plan.steps and decision.use_plan and assessment.requires_tools:
            allowed, why = self.agent._tool_authority_allowed_status(user_text)
            if not allowed:
                self.agent._audit_agent_info(summary="tool_required_but_blocked_by_policy", error=why, meta={"thread_id": thread_id, "user_text": user_text})
                msg = f"This request requires a tool that is currently blocked by policy.\n\nDetails: {why}"
                self.agent._memory_add_event(role="assistant", content=msg, tags=["trusted:assistant"], meta={"thread_id": thread_id})
                if working_memory is not None:
                    working_memory.note_unresolved(why)
                return AgentResult(ok=False, plan=Plan(steps=tuple()), text=finalize_response_text(msg, response_mode=response_mode), tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED, verification=None)

            forced_steps = self.agent._plan_for_tool_authority(user_text)
            if not forced_steps:
                why2 = "Tool authority was triggered but no executable plan could be constructed from the request."
                self.agent._audit_agent_info(summary="tool_required_but_blocked_by_policy", error=why2, meta={"thread_id": thread_id, "user_text": user_text})
                msg = f"This request requires a tool, but I couldn't construct a safe plan automatically.\n\nDetails: {why2}"
                self.agent._memory_add_event(role="assistant", content=msg, tags=["trusted:assistant"], meta={"thread_id": thread_id})
                if working_memory is not None:
                    working_memory.note_unresolved(why2)
                return AgentResult(ok=False, plan=Plan(steps=tuple()), text=finalize_response_text(msg, response_mode=response_mode), tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED, verification=None)

            plan = Plan(steps=tuple(forced_steps))
            self.agent._audit_agent_info(summary="tool_authority_enforced", error=None, meta={"thread_id": thread_id, "plan": self.agent._plan_to_dict(plan)})

        if assessment.requires_tools and not plan.steps and not decision.require_clarification:
            why = "This request depends on local tool execution, but no executable plan was produced."
            self.agent._audit_agent_info(summary="tool_required_without_plan", error=why, meta={"thread_id": thread_id, "user_text": user_text, "assessment": assessment.intent})
            msg = f"This request requires tool execution, but I couldn't build a grounded plan.\n\nDetails: {why}"
            self.agent._memory_add_event(role="assistant", content=msg, tags=["trusted:assistant"], meta={"thread_id": thread_id})
            if working_memory is not None:
                working_memory.note_unresolved(why)
            return AgentResult(ok=False, plan=Plan(steps=tuple()), text=finalize_response_text(msg, response_mode=response_mode), tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED, verification=None)

        if plan.steps:
            try:
                self.agent.validate(plan)
            except Exception as e:
                self.agent._audit_agent_info(summary="plan_validation_error", error=str(e), meta={"plan": self.agent._plan_to_dict(plan), "thread_id": thread_id})
                text = f"Plan error: {e}"
                self.agent._memory_add_event(role="assistant", content=text, tags=["trusted:assistant"], meta={"thread_id": thread_id})
                if working_memory is not None:
                    working_memory.note_unresolved(str(e))
                return AgentResult(ok=False, plan=plan, text=text, tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED)

            self.agent._active_topic = self.agent._topic_slug(user_text)
            try:
                tool_results = self.execute_plan(plan)
            finally:
                self.agent._active_topic = None

            ok = bool(tool_results) and all(r.ok for r in tool_results)
            self.agent._clear_pending_action()
            sources = tuple(self.agent._extract_sources(tool_results))
            if self.agent._plan_includes_web(plan):
                answer, verification_level, verification = self.agent._synthesize_with_sources(
                    user_text=user_text,
                    provider=prov,
                    model=mdl,
                    thread_id=thread_id,
                    memory_context=context,
                    tool_results=tool_results,
                    sources=list(sources),
                )
                answer = finalize_response_text(answer, response_mode=response_mode)
                self.agent._memory_add_event(role="assistant", content=answer, tags=["trusted:assistant"], meta={"thread_id": thread_id, "sources": list(sources)})
                if working_memory is not None:
                    working_memory.set_summary(answer)
                    working_memory.clear_unresolved()
                return AgentResult(ok=ok, plan=plan, text=answer, tool_results=tuple(tool_results), retrieved=tuple(retrieved), context=context, sources=sources, verification_level=verification_level, verification=verification)

            text = finalize_response_text(self.agent._format_tool_results(plan=plan, results=tool_results), response_mode=response_mode)
            self.agent._memory_add_event(role="assistant", content=text, tags=["trusted:assistant"], meta={"thread_id": thread_id, "tool_plan": True})
            if working_memory is not None:
                working_memory.set_summary(text)
                working_memory.clear_unresolved()
                return AgentResult(ok=ok, plan=plan, text=text, tool_results=tuple(tool_results), retrieved=tuple(retrieved), context=context, sources=sources, verification_level=VerificationLevel.UNVERIFIED, verification=None)

        if assessment.requires_tools:
            why = "Tool-required request reached response generation without any executed tool results."
            self.agent._audit_agent_info(summary="tool_required_without_execution", error=why, meta={"thread_id": thread_id, "user_text": user_text, "assessment": assessment.intent})
            msg = f"This request requires tool execution, but nothing was executed.\n\nDetails: {why}"
            self.agent._memory_add_event(role="assistant", content=msg, tags=["trusted:assistant"], meta={"thread_id": thread_id})
            if working_memory is not None:
                working_memory.note_unresolved(why)
            return AgentResult(ok=False, plan=Plan(steps=tuple()), text=finalize_response_text(msg, response_mode=response_mode), tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED, verification=None)

        assistant = self.agent._run_llm_chat_audited(
            user_text=user_text,
            provider=prov,
            model=mdl,
            thread_id=thread_id,
            retrieval_context=context,
            response_mode=response_mode,
        )
        if self.agent._contains_llm_capability_refusal(assistant):
            tools_exist = any(tt.name.startswith(("fs.", "web.")) for tt in self.agent.tools.list_tools())
            if tools_exist or (self.agent.ctx.cfg.agent.mode == "supervised"):
                self.agent._audit_agent_info(summary="llm_refusal_blocked", error=None, meta={"thread_id": thread_id, "llm_excerpt": assistant[:300]})
                assistant = (
                    "I can use the available tools in this environment, but I need a concrete target to act on.\n"
                    "For example: a file path to list/read/write, or a URL to fetch/crawl, or a specific time-sensitive question to verify."
                )
        assistant = finalize_response_text(assistant, response_mode=response_mode)
        self.agent._memory_add_event(role="assistant", content=assistant, tags=["trusted:assistant"], meta={"thread_id": thread_id, "provider": prov, "model": mdl})
        if working_memory is not None:
            working_memory.set_summary(assistant)
            working_memory.clear_unresolved()
        return AgentResult(ok=True, plan=Plan(steps=tuple()), text=assistant, tool_results=tuple(), retrieved=tuple(retrieved), context=context, sources=tuple(), verification_level=VerificationLevel.UNVERIFIED)

    def run_tool(self, *, tool_name: str, tool_args: dict[str, Any], reason: str):
        from agentx.core.runtime_models import AgentResult, Plan, PlanStep

        self.agent._memory_add_event(role="user", content=f"/tool {tool_name}", tags=["trusted:user"], meta={"args": tool_args})
        working_memory = getattr(self.agent.ctx, "working_memory", None)
        if working_memory is not None:
            working_memory.begin(goal=f"Run tool {tool_name}")
            working_memory.record_decision(action="run_tool", reason="Explicit tool execution requested by caller.", evidence=(tool_name,))
        plan = Plan(steps=(PlanStep(tool_name=tool_name, arguments=dict(tool_args or {}), reason=reason),))
        self.agent.validate(plan)
        results = self.execute_plan(plan)
        ok = bool(results and results[-1].ok)
        txt = json.dumps(results[-1].output, ensure_ascii=False, indent=2) if ok else f"[tool error] {results[-1].error}"
        if working_memory is not None:
            working_memory.set_summary(txt)
        res = AgentResult(ok=ok, plan=plan, text=txt, tool_results=tuple(results), retrieved=tuple(), context="", sources=tuple(), verification_level=VerificationLevel.UNVERIFIED)
        self.agent._memory_add_event(role="system", content="agent_result", tags=["trusted:user"], meta={"plan": self.agent._plan_to_dict(res.plan), "ok": res.ok, "tool_results": self.agent._tool_results_to_dict(res.tool_results)})
        return res

    def execute_plan(self, plan) -> list[Any]:
        working_memory = getattr(self.agent.ctx, "working_memory", None)
        if working_memory is not None:
            working_memory.set_plan(self.agent._plan_to_dict(plan).get("steps", []))
        results: list[Any] = []
        for idx, step in enumerate(plan.steps):
            if working_memory is not None:
                working_memory.set_subgoal(f"Execute {step.tool_name}")
            retry = self.action_policy.check_retry(step=step, working_memory=working_memory)
            if not retry.allowed:
                from agentx.core.runtime_models import ToolResult

                result = ToolResult(
                    tool=str(step.tool_name),
                    ok=False,
                    skipped=True,
                    output=None,
                    error=retry.reason,
                    duration_ms=0.0,
                    reason=str(step.reason),
                    args=dict(getattr(step, "arguments", {}) or {}),
                    result=None,
                    error_info=self.agent._tool_error_payload(code=retry.category or "execution", message=retry.reason),
                )
                results.append(result)
                if working_memory is not None:
                    working_memory.record_attempt(signature=self.action_policy.step_signature(step), tool=str(step.tool_name), reason=str(step.reason), status="failure", category=retry.category)
                    working_memory.note_unresolved(retry.reason)
                    working_memory.record_decision(action="block_retry", reason=retry.reason, evidence=(retry.category,))
                break
            result = self.agent._execute_step(step, prior_results=results)
            results.append(result)
            if working_memory is not None:
                interpretation = self.result_interpreter.interpret(tool_name=result.tool, ok=result.ok, output=result.output, error=result.error)
                summary = interpretation.summary
                working_memory.append_result(tool=result.tool, ok=result.ok, summary=summary, output=result.output if result.ok else None, error=result.error)
                working_memory.add_focus_resources(list(interpretation.focus_resources))
                working_memory.add_evidence_notes(list(interpretation.evidence_notes))
                status = "success" if result.ok else "failure"
                category = None if result.ok else self.action_policy.categorize_failure(result.error)
                working_memory.record_attempt(signature=self.action_policy.step_signature(step), tool=result.tool, reason=result.reason, status=status, category=category)
                if not result.ok and result.error:
                    working_memory.note_unresolved(result.error)
                    working_memory.record_decision(action="tool_failure", reason=result.error, evidence=(result.tool,))
            if not result.ok and not self.agent._should_continue_after_failure(plan=plan, failed_index=idx, failure=result):
                break
        return results
