from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from agentx.core.project_memory import Durability, MemoryKind, MemoryScope, ProjectMemoryEntry, ProjectMemoryStore


@dataclass(frozen=True)
class TaskReflection:
    task_id: str
    goal: str
    summary: str
    changed: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    affected_modules: list[str] = field(default_factory=list)
    assumptions_corrected: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    durable_knowledge: list[str] = field(default_factory=list)
    discard_noise: list[str] = field(default_factory=list)
    docs_update_needed: bool = False
    changelog_update_needed: bool = False
    created_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "TaskReflection":
        if not isinstance(raw, dict):
            raise ValueError("reflection must be a dict")
        return TaskReflection(
            task_id=str(raw.get("task_id") or "").strip(),
            goal=str(raw.get("goal") or "").strip(),
            summary=str(raw.get("summary") or "").strip(),
            changed=_list(raw.get("changed")),
            affected_files=_list(raw.get("affected_files")),
            affected_modules=_list(raw.get("affected_modules")),
            assumptions_corrected=_list(raw.get("assumptions_corrected")),
            decisions=_list(raw.get("decisions")),
            errors=_list(raw.get("errors")),
            tests=_list(raw.get("tests")),
            durable_knowledge=_list(raw.get("durable_knowledge")),
            discard_noise=_list(raw.get("discard_noise")),
            docs_update_needed=bool(raw.get("docs_update_needed", False)),
            changelog_update_needed=bool(raw.get("changelog_update_needed", False)),
            created_at=float(raw.get("created_at") or time.time()),
            meta=dict(raw.get("meta") or {}),
        )


def build_reflection_from_job(job: Any) -> TaskReflection:
    """Create a deterministic post-task reflection from an AgentX Job object."""

    task_id = str(getattr(job, "job_id", "") or "").strip()
    goal = str(getattr(job, "goal", "") or "").strip()
    result_summary = str(getattr(job, "result_summary", "") or getattr(job, "summary", "") or "").strip()
    iterations = list(getattr(job, "iterations", []) or [])
    reflections = list(getattr(job, "reflections", []) or [])

    affected_files: list[str] = []
    changed: list[str] = []
    tests: list[str] = []
    errors: list[str] = []
    for iteration in iterations:
        plan = getattr(iteration, "plan", None)
        if isinstance(plan, dict):
            changed.extend(_extract_plan_summaries(plan))
        for tr in getattr(iteration, "tool_results", []) or []:
            if not isinstance(tr, dict):
                continue
            changed.extend(_extract_tool_change(tr))
            affected_files.extend(_extract_files_from_obj(tr))
            if _looks_like_test(tr):
                tests.append(_summarize_tool_result(tr))
            if not bool(tr.get("ok", True)):
                err = str(tr.get("error") or tr.get("output") or "tool failed").strip()
                if err:
                    errors.append(err[:500])
    for refl in reflections:
        err = str(getattr(refl, "error", None) or getattr(refl, "summary", "") or "").strip()
        if err:
            errors.append(err[:500])

    modules = infer_modules(affected_files)
    summary = result_summary or (changed[0] if changed else "Task finished; review the changed files and outputs before promoting durable knowledge.")
    durable = _derive_durable_knowledge(goal=goal, summary=summary, changed=changed, affected_files=affected_files)
    return TaskReflection(
        task_id=task_id,
        goal=goal,
        summary=summary,
        changed=_dedupe(changed)[:20],
        affected_files=_dedupe(affected_files)[:50],
        affected_modules=modules,
        errors=_dedupe(errors)[:20],
        tests=_dedupe(tests)[:20],
        durable_knowledge=durable,
        docs_update_needed=_needs_docs_update(goal, changed, affected_files),
        changelog_update_needed=bool(changed or affected_files),
        meta={"source": "job_runner"},
    )


def save_reflection_to_memory(store: ProjectMemoryStore, reflection: TaskReflection) -> list[ProjectMemoryEntry]:
    """Persist reflection outputs as scoped project memory entries."""

    entries: list[ProjectMemoryEntry] = []
    base_meta = {"reflection": reflection.to_dict()}
    entries.append(
        store.add_entry(
            title=f"Task reflection: {reflection.goal[:120] or reflection.task_id}",
            summary=render_reflection(reflection),
            scope=MemoryScope.TASK,
            kind=MemoryKind.CHANGE_SUMMARY,
            durability=Durability.MEDIUM,
            task_id=reflection.task_id or None,
            source="post_task_reflection",
            tags=["reflection", "task-summary"],
            affected_files=reflection.affected_files,
            decisions=reflection.decisions,
            assumptions_corrected=reflection.assumptions_corrected,
            evidence=reflection.tests + reflection.errors,
            meta=base_meta,
        )
    )
    for module in reflection.affected_modules:
        module_notes = [x for x in reflection.durable_knowledge if module.lower() in x.lower()]
        summary = "\n".join(module_notes or reflection.durable_knowledge or reflection.changed or [reflection.summary])
        entries.append(
            store.add_entry(
                title=f"Module update: {module}",
                summary=summary,
                scope=MemoryScope.MODULE,
                kind=MemoryKind.MODULE_NOTE,
                durability=Durability.HIGH if reflection.durable_knowledge else Durability.MEDIUM,
                module=module,
                task_id=reflection.task_id or None,
                source="post_task_reflection",
                tags=["reflection", "module-update"],
                affected_files=[p for p in reflection.affected_files if module.lower() in p.lower()],
                decisions=reflection.decisions,
                assumptions_corrected=reflection.assumptions_corrected,
                meta=base_meta,
            )
        )
    for decision in reflection.decisions:
        entries.append(
            store.add_entry(
                title=f"Decision: {decision[:120]}",
                summary=decision,
                scope=MemoryScope.DECISION,
                kind=MemoryKind.DECISION,
                durability=Durability.HIGH,
                task_id=reflection.task_id or None,
                source="post_task_reflection",
                tags=["reflection", "decision"],
                affected_files=reflection.affected_files,
                meta=base_meta,
            )
        )
    return entries


def render_reflection(reflection: TaskReflection) -> str:
    sections = [
        ("Goal", [reflection.goal]),
        ("Summary", [reflection.summary]),
        ("Changed", reflection.changed),
        ("Affected files", reflection.affected_files),
        ("Affected modules", reflection.affected_modules),
        ("Assumptions corrected", reflection.assumptions_corrected),
        ("Decisions", reflection.decisions),
        ("Errors", reflection.errors),
        ("Tests", reflection.tests),
        ("Durable knowledge", reflection.durable_knowledge),
        ("Discarded task noise", reflection.discard_noise),
    ]
    lines: list[str] = []
    for title, items in sections:
        clean = _list(items)
        if not clean:
            continue
        lines.append(f"## {title}")
        lines.extend(f"- {item}" for item in clean)
        lines.append("")
    lines.append(f"Docs update needed: {reflection.docs_update_needed}")
    lines.append(f"Changelog update needed: {reflection.changelog_update_needed}")
    return "\n".join(lines).strip() + "\n"


def reflection_prompt_template() -> str:
    return (
        "Post-task reflection is required before durable memory promotion.\n"
        "Answer these fields with reusable project knowledge only:\n"
        "1. What changed?\n"
        "2. What files/modules were affected?\n"
        "3. What assumptions were corrected?\n"
        "4. What decisions were made?\n"
        "5. What errors or tests matter later?\n"
        "6. What should be promoted to durable knowledge?\n"
        "7. What should be discarded as task noise?\n"
    )


def infer_modules(paths: Iterable[str]) -> list[str]:
    modules: list[str] = []
    for path in paths:
        p = str(path).replace("\\", "/").strip()
        parts = [x for x in p.split("/") if x]
        if not parts:
            continue
        module = ""
        if "core" in parts:
            idx = parts.index("core")
            module = parts[idx + 1].removesuffix(".py") if idx + 1 < len(parts) else "core"
        elif "tools" in parts:
            idx = parts.index("tools")
            module = parts[idx + 1].removesuffix(".py") if idx + 1 < len(parts) else "tools"
        elif "jobs" in parts:
            idx = parts.index("jobs")
            module = parts[idx + 1].removesuffix(".py") if idx + 1 < len(parts) else "jobs"
        elif len(parts) >= 2:
            module = parts[-2]
        else:
            module = parts[0].removesuffix(".py")
        if module and module not in modules:
            modules.append(module)
    return modules[:20]


def _extract_plan_summaries(plan: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for step in plan.get("steps", []) if isinstance(plan.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool_name") or step.get("tool") or "tool").strip()
        reason = str(step.get("reason") or step.get("summary") or "").strip()
        out.append(f"Planned {tool}: {reason}" if reason else f"Planned {tool}")
    return out


def _extract_tool_change(tr: dict[str, Any]) -> list[str]:
    tool = str(tr.get("tool") or tr.get("tool_name") or "tool").strip()
    out = tr.get("output")
    text = json.dumps(out, ensure_ascii=False) if isinstance(out, (dict, list)) else str(out or "")
    if not text.strip():
        return [f"Ran {tool}"]
    first = text.strip().replace("\n", " ")[:240]
    return [f"{tool}: {first}"]


def _extract_files_from_obj(obj: Any) -> list[str]:
    text = json.dumps(obj, ensure_ascii=False) if isinstance(obj, (dict, list)) else str(obj)
    matches = re.findall(r"(?:AgentX/|Server/|tests/|docs/|config/)[A-Za-z0-9_./\\-]+", text)
    return _dedupe(matches)


def _looks_like_test(tr: dict[str, Any]) -> bool:
    blob = json.dumps(tr, ensure_ascii=False).lower()
    return any(x in blob for x in ("pytest", "test_", "passed", "failed", "coverage"))


def _summarize_tool_result(tr: dict[str, Any]) -> str:
    tool = str(tr.get("tool") or tr.get("tool_name") or "tool")
    ok = bool(tr.get("ok", True))
    return f"{tool}: {'ok' if ok else 'failed'}"


def _derive_durable_knowledge(*, goal: str, summary: str, changed: list[str], affected_files: list[str]) -> list[str]:
    out: list[str] = []
    if summary:
        out.append(summary[:700])
    if affected_files:
        out.append("Affected files: " + ", ".join(affected_files[:12]))
    for item in changed[:5]:
        low = item.lower()
        if any(w in low for w in ("added", "created", "implemented", "changed", "updated", "fixed")):
            out.append(item[:500])
    return _dedupe(out)[:10]


def _needs_docs_update(goal: str, changed: list[str], affected_files: list[str]) -> bool:
    blob = "\n".join([goal] + changed + affected_files).lower()
    return any(w in blob for w in ("readme", "docs", "feature", "api", "config", "install", "setup"))


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    else:
        try:
            values = list(value)
        except TypeError:
            values = [value]
    return _dedupe(str(x).strip() for x in values if str(x).strip())


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        s = str(value).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
