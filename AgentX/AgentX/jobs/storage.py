from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from agentx.config import AgentXConfig

from .models import FailureCategory, Job, JobBudgets, JobFailureReflection, JobStatus, JobStepRecord, PendingApproval, RetryDecision


class JobStore:
    def __init__(self, *, cfg: AgentXConfig, runtime_paths) -> None:
        self.cfg = cfg
        self.runtime_paths = runtime_paths
        self.jobs_dir: Path = runtime_paths.jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def list_jobs(self) -> list[Job]:
        out: list[Job] = []
        for path in sorted(self.jobs_dir.glob("*.json")):
            try:
                out.append(self.load(path.stem))
            except Exception:
                continue
        return sorted(out, key=lambda j: j.created_at, reverse=True)

    def exists(self, job_id: str) -> bool:
        return self._path(job_id).exists()

    def load(self, job_id: str) -> Job:
        path = self._path(job_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return self._from_dict(raw)

    def save(self, job: Job) -> Job:
        job.updated_at = time.time()
        path = self._path(job.job_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._to_dict(job), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return job

    def _path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    @staticmethod
    def _to_dict(job: Job) -> dict:
        data = asdict(job)
        data["status"] = job.status.value
        data["budgets"] = asdict(job.budgets)
        data["iterations"] = [asdict(x) for x in job.iterations]
        data["reflections"] = [
            {
                **asdict(x),
                "category": x.category.value,
                "retry_decision": x.retry_decision.value,
            }
            for x in job.reflections
        ]
        if job.pending_approval:
            data["pending_approval"] = asdict(job.pending_approval)
        return data

    @staticmethod
    def _from_dict(raw: dict) -> Job:
        budgets_raw = raw.get("budgets") or {}
        iterations = [
            JobStepRecord(**item)
            for item in raw.get("iterations", [])
            if isinstance(item, dict)
        ]
        reflections = [
            JobFailureReflection(
                category=FailureCategory(item.get("category", FailureCategory.UNKNOWN.value)),
                summary=str(item.get("summary") or ""),
                strategy=str(item.get("strategy") or ""),
                retry_decision=RetryDecision(item.get("retry_decision", RetryDecision.STOP.value)),
                confidence=float(item.get("confidence") or 0.0),
                reusable=bool(item.get("reusable", False)),
                failure_signature=str(item.get("failure_signature") or ""),
                tool_name=(str(item.get("tool_name")).strip() if item.get("tool_name") is not None else None),
                error=(str(item.get("error")).strip() if item.get("error") is not None else None),
            )
            for item in raw.get("reflections", [])
            if isinstance(item, dict)
        ]
        pending = raw.get("pending_approval")
        pending_obj = PendingApproval(**pending) if isinstance(pending, dict) else None
        return Job(
            job_id=str(raw.get("job_id") or ""),
            goal=str(raw.get("goal") or ""),
            created_at=float(raw.get("created_at") or 0.0),
            updated_at=float(raw.get("updated_at") or 0.0),
            status=JobStatus(str(raw.get("status") or JobStatus.PENDING.value)),
            budgets=JobBudgets(
                max_steps=int(budgets_raw.get("max_steps") or 10),
                max_failures=int(budgets_raw.get("max_failures") or 3),
                max_runtime_s=int(budgets_raw.get("max_runtime_s") or 900),
            ),
            skill_id=(str(raw.get("skill_id")).strip() if raw.get("skill_id") is not None else None),
            steps_taken=int(raw.get("steps_taken") or 0),
            failures=int(raw.get("failures") or 0),
            summary=str(raw.get("summary") or ""),
            result_summary=str(raw.get("result_summary") or ""),
            last_error=(str(raw.get("last_error")).strip() if raw.get("last_error") is not None else None),
            iterations=iterations,
            reflections=reflections,
            approved_plan_fingerprints=[str(x) for x in raw.get("approved_plan_fingerprints", []) if str(x).strip()],
            pending_approval=pending_obj,
            metadata=dict(raw.get("metadata") or {}),
            cancellation_requested=bool(raw.get("cancellation_requested", False)),
        )
