from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from typing import Any

from agentx.core.agent import Agent, AgentPolicyError, Plan
from agentx.core.audit import AuditEvent
from agentx.learning.hints import ReflectionHint
from agentx.plugins.manager import PluginManager
from agentx.skills.manager import SkillManager

from .models import FailureCategory, Job, JobBudgets, JobFailureReflection, JobStatus, JobStepRecord, PendingApproval, RetryDecision
from .planner import JobPlanner
from .storage import JobStore


class JobRunner:
    def __init__(
        self,
        *,
        agent: Agent,
        store: JobStore,
        plugin_manager: PluginManager | None,
        skill_manager: SkillManager | None,
        hint_store,
    ) -> None:
        self.agent = agent
        self.store = store
        self.plugin_manager = plugin_manager
        self.skill_manager = skill_manager
        self.hint_store = hint_store
        self.planner = JobPlanner(agent=agent)

    def create_job(
        self,
        *,
        goal: str,
        skill_id: str | None = None,
        max_steps: int = 10,
        max_failures: int = 3,
        max_runtime_s: int = 900,
        metadata: dict[str, Any] | None = None,
    ) -> Job:
        job = Job.create(
            goal=goal,
            budgets=JobBudgets(max_steps=max_steps, max_failures=max_failures, max_runtime_s=max_runtime_s),
            skill_id=skill_id,
            metadata=metadata,
        )
        self._audit_job(job=job, summary="job_created", success=True, error=None)
        return self.store.save(job)

    def run_to_terminal(self, job_id: str) -> Job:
        job = self.store.load(job_id)
        self._bind_working_memory(job)
        if job.status == JobStatus.CANCELLED:
            return job
        started_at = time.time()
        job.status = JobStatus.RUNNING
        self.store.save(job)
        self._audit_job(job=job, summary="job_started", success=True, error=None)

        while True:
            if job.cancellation_requested:
                job.status = JobStatus.CANCELLED
                job.result_summary = "Job was cancelled."
                self._audit_job(job=job, summary="job_cancelled", success=False, error="Cancellation requested.")
                return self.store.save(job)

            elapsed = time.time() - started_at
            if elapsed > job.budgets.max_runtime_s:
                job.status = JobStatus.FAILED
                job.last_error = "Runtime budget exceeded."
                job.result_summary = job.last_error
                self._audit_job(job=job, summary="job_runtime_budget_exceeded", success=False, error=job.last_error)
                return self.store.save(job)
            if job.steps_taken >= job.budgets.max_steps:
                job.status = JobStatus.BLOCKED
                job.last_error = "Step budget exceeded."
                job.result_summary = job.last_error
                self._audit_job(job=job, summary="job_step_budget_exceeded", success=False, error=job.last_error)
                return self.store.save(job)
            if job.failures >= job.budgets.max_failures:
                job.status = JobStatus.FAILED
                job.last_error = "Failure budget exceeded."
                job.result_summary = job.last_error
                self._audit_job(job=job, summary="job_failure_budget_exceeded", success=False, error=job.last_error)
                return self.store.save(job)

            skill = self.skill_manager.get_skill(job.skill_id) if self.skill_manager and job.skill_id else None
            hint_tools = [r.tool_name for r in job.reflections if r.tool_name]
            hints = self.hint_store.query(goal=job.goal, tool_names=hint_tools, limit=5) if self.hint_store else []
            decision = self.planner.plan_next(job=job, skill=skill, hints=hints)
            job.summary = decision.summary or job.summary
            if getattr(self.agent.ctx, "working_memory", None) is not None:
                self.agent.ctx.working_memory.begin(goal=job.goal, constraints=[f"max_steps={job.budgets.max_steps}", f"max_failures={job.budgets.max_failures}"])
                self.agent.ctx.working_memory.set_summary(job.summary)
                self.agent.ctx.working_memory.set_plan(self._plan_to_dict(decision.plan).get("steps", []))

            if decision.status == "complete":
                job.status = JobStatus.COMPLETED
                job.result_summary = decision.summary or "Planner marked the job complete."
                self._audit_job(job=job, summary="job_completed", success=True, error=None)
                return self.store.save(job)
            if decision.status == "blocked" or not decision.plan.steps:
                job.status = JobStatus.BLOCKED
                job.last_error = decision.summary or "Planner could not safely continue."
                job.result_summary = job.last_error
                self._audit_job(job=job, summary="job_blocked", success=False, error=job.last_error)
                return self.store.save(job)

            fingerprint = self._plan_fingerprint(decision.plan)
            approval = self._approval_required(decision.plan)
            if approval and fingerprint not in job.approved_plan_fingerprints:
                job.status = JobStatus.BLOCKED
                job.pending_approval = PendingApproval(
                    fingerprint=fingerprint,
                    requested_at=time.time(),
                    reason="approval_required",
                    summary=approval,
                    tool_names=tuple(step.tool_name for step in decision.plan.steps),
                )
                job.last_error = approval
                job.result_summary = approval
                self._audit_job(job=job, summary="job_waiting_for_approval", success=False, error=approval)
                return self.store.save(job)
            job.pending_approval = None

            iter_started = time.time()
            try:
                results = self.agent.execute(decision.plan)
            except Exception as e:
                reflection = self._reflect_failure(job=job, plan=decision.plan, error=str(e), tool_name=None)
                job.reflections.append(reflection)
                job.failures += 1
                job.last_error = str(e)
                promoted = self._promote_hint(reflection)
                if promoted:
                    job.metadata["last_promoted_hint"] = promoted.hint_id
                if reflection.retry_decision == RetryDecision.STOP:
                    job.status = JobStatus.FAILED
                    job.result_summary = reflection.summary
                    self._audit_job(job=job, summary="job_failed", success=False, error=str(e))
                    return self.store.save(job)
                self._audit_job(job=job, summary="job_retrying_after_failure", success=False, error=str(e))
                self.store.save(job)
                continue

            iter_finished = time.time()
            step_record = JobStepRecord(
                iteration=job.steps_taken + 1,
                started_at=iter_started,
                finished_at=iter_finished,
                plan=self._plan_to_dict(decision.plan),
                tool_results=[asdict(r) for r in results],
                summary=decision.summary,
                ok=all(r.ok for r in results),
            )
            job.iterations.append(step_record)
            job.steps_taken += len(decision.plan.steps)
            self.store.save(job)

            if not all(r.ok for r in results):
                failed = next((r for r in results if not r.ok), None)
                reflection = self._reflect_failure(
                    job=job,
                    plan=decision.plan,
                    error=(failed.error if failed else "Unknown execution error"),
                    tool_name=(failed.tool if failed else None),
                )
                job.reflections.append(reflection)
                job.failures += 1
                job.last_error = reflection.error or reflection.summary
                promoted = self._promote_hint(reflection)
                if promoted:
                    job.metadata["last_promoted_hint"] = promoted.hint_id
                if reflection.retry_decision == RetryDecision.STOP or job.failures >= job.budgets.max_failures:
                    job.status = JobStatus.FAILED
                    job.result_summary = reflection.summary
                    self._audit_job(job=job, summary="job_failed", success=False, error=job.last_error)
                    return self.store.save(job)
                self._audit_job(job=job, summary="job_retrying_after_reflection", success=False, error=job.last_error)
                self.store.save(job)
                continue

            assessment = self.planner.assess_progress(job=job, last_text=self._tool_results_text(results))
            if assessment == "continue":
                job.summary = decision.summary or job.summary
                self._audit_job(job=job, summary="job_continuing", success=True, error=None)
                self.store.save(job)
                continue
            if assessment == "blocked":
                job.status = JobStatus.BLOCKED
                job.result_summary = "Planner could not continue safely after the last successful step."
                self._audit_job(job=job, summary="job_blocked_after_success", success=False, error=job.result_summary)
                return self.store.save(job)
            job.status = JobStatus.COMPLETED
            job.result_summary = decision.summary or "Job completed successfully."
            self._audit_job(job=job, summary="job_completed", success=True, error=None)
            return self.store.save(job)

    def approve_pending(self, job_id: str, *, approved: bool, note: str = "") -> Job:
        job = self.store.load(job_id)
        if not job.pending_approval:
            return job
        if approved:
            if job.pending_approval.fingerprint not in job.approved_plan_fingerprints:
                job.approved_plan_fingerprints.append(job.pending_approval.fingerprint)
            job.pending_approval = None
            job.status = JobStatus.PENDING
            job.last_error = None
            job.result_summary = note or "Plan approved; ready to resume."
            self._audit_job(job=job, summary="job_approval_granted", success=True, error=None)
        else:
            job.status = JobStatus.CANCELLED
            job.result_summary = note or "Job approval was denied."
            self._audit_job(job=job, summary="job_approval_denied", success=False, error=job.result_summary)
        return self.store.save(job)

    def _bind_working_memory(self, job: Job) -> None:
        manager = getattr(self.agent.ctx, "working_memory_manager", None)
        if manager is None:
            return
        user_id = getattr(self.agent.ctx, "web_session_user", None)
        if not user_id:
            user_id = getattr(getattr(self.agent.ctx, "local_profile", None), "profile_id", None)
        self.agent.ctx.working_memory = manager.for_scope(user_id=user_id, job_id=job.job_id)

    def cancel(self, job_id: str, *, reason: str = "") -> Job:
        job = self.store.load(job_id)
        job.cancellation_requested = True
        job.last_error = reason or "Cancellation requested."
        self._audit_job(job=job, summary="job_cancellation_requested", success=False, error=job.last_error)
        return self.store.save(job)

    def _reflect_failure(self, *, job: Job, plan: Plan, error: str | None, tool_name: str | None) -> JobFailureReflection:
        msg = str(error or "").strip()
        low = msg.lower()
        if "approval" in low or "confirm" in low:
            category = FailureCategory.APPROVAL
            retry = RetryDecision.STOP
            strategy = "Wait for explicit human approval before retrying."
            confidence = 0.95
        elif "policy" in low or "unsafe" in low or "blocked" in low:
            category = FailureCategory.POLICY
            retry = RetryDecision.STOP
            strategy = "Do not retry automatically; the plan is blocked by policy or unsafe-mode requirements."
            confidence = 0.95
        elif "timeout" in low or "tempor" in low or "network" in low or "http 5" in low:
            category = FailureCategory.TRANSIENT
            retry = RetryDecision.RETRY
            strategy = "Retry the same step once with the same validated arguments; treat the failure as transient."
            confidence = 0.75
        elif "missing required argument" in low or "unknown arguments" in low or "expected" in low:
            category = FailureCategory.VALIDATION
            retry = RetryDecision.STOP
            strategy = "Inspect the tool schema before retrying; do not guess missing arguments."
            confidence = 0.85
        elif msg:
            category = FailureCategory.EXECUTION
            retry = RetryDecision.RETRY_WITH_HINT
            strategy = "Retry once using the reflected lesson and avoid repeating the same assumption."
            confidence = 0.7
        else:
            category = FailureCategory.UNKNOWN
            retry = RetryDecision.STOP
            strategy = "Stop and require inspection because the failure could not be classified safely."
            confidence = 0.5

        signature_src = json.dumps(
            {
                "tool_name": tool_name,
                "category": category.value,
                "error": msg[:200],
                "plan_tools": [step.tool_name for step in plan.steps],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        signature = hashlib.sha256(signature_src.encode("utf-8")).hexdigest()[:24]
        return JobFailureReflection(
            category=category,
            summary=f"{category.value}: {msg or 'unknown failure'}",
            strategy=strategy,
            retry_decision=retry,
            confidence=confidence,
            reusable=category in {FailureCategory.VALIDATION, FailureCategory.EXECUTION, FailureCategory.TRANSIENT, FailureCategory.POLICY},
            failure_signature=signature,
            tool_name=tool_name,
            error=msg or None,
        )

    def _promote_hint(self, reflection: JobFailureReflection):
        if not self.hint_store:
            return None
        return self.hint_store.consider_reflection(
            ReflectionHint(
                failure_signature=reflection.failure_signature,
                category=reflection.category.value,
                strategy=reflection.strategy,
                confidence=reflection.confidence,
                reusable=reflection.reusable,
                tool_name=reflection.tool_name,
            )
        )

    def _approval_required(self, plan: Plan) -> str | None:
        high_risk_tools: list[str] = []
        for step in plan.steps:
            tool = self.agent.tools.get_tool(step.tool_name)
            meta = self.agent.tools.get_metadata(step.tool_name)
            if tool is None:
                continue
            if bool(getattr(tool, "destructive", False)) or bool(getattr(tool, "requires_confirmation", False)):
                high_risk_tools.append(tool.name)
                continue
            if str(meta.get("risk_level") or "medium").lower() in {"high", "critical"}:
                high_risk_tools.append(tool.name)
        if high_risk_tools:
            joined = ", ".join(sorted(set(high_risk_tools)))
            return f"Approval required before executing high-risk plan: {joined}"
        return None

    @staticmethod
    def _plan_fingerprint(plan: Plan) -> str:
        payload = {"steps": [{"tool": s.tool_name, "arguments": s.arguments, "reason": s.reason} for s in plan.steps]}
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]

    def _audit_job(self, *, job: Job, summary: str, success: bool, error: str | None) -> None:
        ok, err = self.agent.ctx.audit.ensure_writable()
        if not ok:
            raise AgentPolicyError(f"Audit log is not writable; refusing job transition: {err}")
        a_ok, a_err = self.agent.ctx.audit.append(
            AuditEvent(
                ts=time.time(),
                mode=str(self.agent.ctx.cfg.agent.mode),
                event="agent_info",
                tool="job",
                args={
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "steps_taken": job.steps_taken,
                    "failures": job.failures,
                    "skill_id": job.skill_id,
                },
                reason="job_runner",
                duration_ms=None,
                success=success,
                summary=summary,
                error=error,
                invocation_id=None,
            )
        )
        if not a_ok:
            raise AgentPolicyError(f"Failed to append job audit event: {a_err}")

    @staticmethod
    def _plan_to_dict(plan: Plan) -> dict[str, Any]:
        return {
            "steps": [
                {"tool_name": step.tool_name, "arguments": step.arguments, "reason": step.reason}
                for step in plan.steps
            ]
        }

    @staticmethod
    def _tool_results_text(results: list[Any]) -> str:
        parts = []
        for r in results:
            parts.append(f"{r.tool}: ok={r.ok} skipped={r.skipped} error={r.error} output={str(r.output)[:300]}")
        return "\n".join(parts)
