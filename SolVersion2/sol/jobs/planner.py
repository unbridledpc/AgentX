from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sol.core.agent import Agent, AgentPolicyError
from sol.core.runtime_models import Plan, PlanStep
from sol.core.llm import LlmError, load_ollama_cfg, load_openai_cfg, ollama_generate, openai_chat_completions
from sol.jobs.models import Job, JobStatus
from sol.skills.models import SkillRecord


@dataclass(frozen=True)
class PlannerDecision:
    status: str  # plan | complete | blocked
    summary: str
    plan: Plan
    raw_text: str


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("Empty planner response.")
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\n", "", stripped)
        stripped = re.sub(r"\n```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Planner did not return a JSON object.")
    return json.loads(stripped[start : end + 1])


class JobPlanner:
    def __init__(self, *, agent: Agent):
        self.agent = agent

    def plan_next(self, *, job: Job, skill: SkillRecord | None, hints: list[Any]) -> PlannerDecision:
        provider = str(self.agent.ctx.cfg.llm.get("provider") or "stub").strip().lower()
        if provider not in {"openai", "ollama"}:
            return self._fallback_plan(job=job, skill=skill, hints=hints)

        prompt = self._build_prompt(job=job, skill=skill, hints=hints)
        try:
            raw = self._generate(prompt=prompt, provider=provider)
            parsed = _extract_json_object(raw)
        except Exception:
            return self._fallback_plan(job=job, skill=skill, hints=hints)

        status = str(parsed.get("status") or "blocked").strip().lower()
        summary = str(parsed.get("summary") or "").strip()
        if status == "complete":
            return PlannerDecision(status="complete", summary=summary or "Planner marked the job complete.", plan=Plan(steps=tuple()), raw_text=raw)
        if status == "blocked":
            return PlannerDecision(status="blocked", summary=summary or "Planner could not make further progress.", plan=Plan(steps=tuple()), raw_text=raw)

        plan_payload = {"steps": parsed.get("steps") or []}
        try:
            steps = []
            for step in plan_payload["steps"]:
                if not isinstance(step, dict):
                    continue
                steps.append(
                    PlanStep(
                        tool_name=str(step.get("tool") or step.get("tool_name") or "").strip(),
                        arguments=dict(step.get("arguments") or step.get("args") or {}),
                        reason=str(step.get("reason") or "").strip(),
                    )
                )
            plan = Plan(steps=tuple(steps))
            self.agent.validate(plan)
            return PlannerDecision(status="plan", summary=summary or "Planner produced a plan.", plan=plan, raw_text=raw)
        except Exception:
            return self._fallback_plan(job=job, skill=skill, hints=hints)

    def assess_progress(self, *, job: Job, last_text: str) -> str:
        provider = str(self.agent.ctx.cfg.llm.get("provider") or "stub").strip().lower()
        if provider not in {"openai", "ollama"}:
            if job.steps_taken >= job.budgets.max_steps:
                return "blocked"
            return "complete"
        prompt = (
            "You are assessing supervised autonomous job progress.\n"
            "Return one word only: complete, continue, or blocked.\n\n"
            f"Goal:\n{job.goal}\n\n"
            f"Current summary:\n{job.summary}\n\n"
            f"Latest result:\n{last_text}\n"
        )
        try:
            raw = self._generate(prompt=prompt, provider=provider).strip().lower()
        except Exception:
            return "complete"
        if "continue" in raw:
            return "continue"
        if "blocked" in raw:
            return "blocked"
        return "complete"

    def _fallback_plan(self, *, job: Job, skill: SkillRecord | None, hints: list[Any]) -> PlannerDecision:
        parts = [job.goal]
        if skill and skill.instructions:
            parts.append("\nSkill guidance:\n" + skill.instructions)
        if hints:
            parts.append("\nRelevant learned hints:")
            for hint in hints[:3]:
                parts.append(f"- {hint.strategy}")
        if job.reflections:
            last = job.reflections[-1]
            parts.append(f"\nRetry strategy from previous failure: {last.strategy}")
        text = "\n".join(parts).strip()
        plan = self.agent.plan(text)
        try:
            self.agent.validate(plan)
        except AgentPolicyError:
            return PlannerDecision(status="blocked", summary="Fallback planner could not produce a valid plan.", plan=Plan(steps=tuple()), raw_text=text)
        if not plan.steps:
            return PlannerDecision(status="blocked", summary="Fallback planner found no executable steps.", plan=plan, raw_text=text)
        return PlannerDecision(status="plan", summary="Fallback planner produced a plan.", plan=plan, raw_text=text)

    def _build_prompt(self, *, job: Job, skill: SkillRecord | None, hints: list[Any]) -> str:
        tool_schema = self.agent.tools.schema()
        tool_lines = []
        for tool in tool_schema:
            args = ", ".join(
                f"{a['name']}:{a['type']}{'*' if a.get('required') else ''}"
                for a in tool.get("args", [])
            )
            tool_lines.append(
                f"- {tool['name']} [{tool.get('risk_level','medium')}] ({tool.get('source','builtin')}): {tool.get('description','')} | args: {args}"
            )
        hint_lines = [f"- {h.tool_name or 'general'}: {h.strategy}" for h in hints[:5]]
        reflection_lines = [f"- {r.category.value}: {r.strategy}" for r in job.reflections[-3:]]
        return (
            "You are Sol's supervised job planner.\n"
            "Rules:\n"
            "- Return valid JSON only.\n"
            "- Never bypass approval or policy; risky plans should still be proposed, not executed.\n"
            "- Prefer 1-3 concrete tool steps.\n"
            "- If the goal is already satisfied, use status=complete.\n"
            "- If you cannot safely continue, use status=blocked.\n"
            "- Each step must include tool, reason, and arguments.\n\n"
            "JSON format:\n"
            '{"status":"plan|complete|blocked","summary":"...","steps":[{"tool":"fs.list","reason":"...","arguments":{}}]}\n\n'
            f"Goal:\n{job.goal}\n\n"
            f"Current job summary:\n{job.summary or '(none)'}\n\n"
            f"Previous reflections:\n{chr(10).join(reflection_lines) or '(none)'}\n\n"
            f"Learned hints:\n{chr(10).join(hint_lines) or '(none)'}\n\n"
            f"Skill instructions:\n{skill.instructions if skill else '(none)'}\n\n"
            f"Available tools:\n{chr(10).join(tool_lines)}\n"
        )

    def _generate(self, *, prompt: str, provider: str) -> str:
        if provider == "openai":
            cfg = load_openai_cfg(self.agent.ctx.cfg.llm)
            model = cfg.model
            data = openai_chat_completions(
                cfg=cfg,
                messages=[
                    {"role": "system", "content": "You are Sol's planner. Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
            )
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                raise LlmError("Planner returned no choices.")
            _ = model
            return str((((choices[0] or {}).get("message") or {}).get("content")) or "")
        cfg = load_ollama_cfg(self.agent.ctx.cfg.llm)
        return ollama_generate(cfg=cfg, prompt=prompt)
