from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolInterpretation:
    summary: str
    sufficient: bool = False
    focus_resources: tuple[str, ...] = tuple()
    evidence_notes: tuple[str, ...] = tuple()


class ToolResultInterpreter:
    def interpret(self, *, tool_name: str, ok: bool, output: Any, error: str | None = None) -> ToolInterpretation:
        if not ok:
            return ToolInterpretation(summary=str(error or "Tool failed."), sufficient=False)
        if isinstance(output, dict):
            resources: list[str] = []
            notes: list[str] = []
            if isinstance(output.get("path"), str) and output.get("path"):
                resources.append(str(output["path"]))
            if isinstance(output.get("url"), str) and output.get("url"):
                resources.append(str(output["url"]))
            if isinstance(output.get("results"), list):
                count = len(output.get("results") or [])
                notes.append(f"{tool_name} returned {count} result(s).")
                return ToolInterpretation(summary=f"{tool_name} returned {count} result(s).", sufficient=count > 0, focus_resources=tuple(resources), evidence_notes=tuple(notes))
            if "text" in output and isinstance(output.get("text"), str):
                text = str(output.get("text") or "").strip()
                notes.append(f"{tool_name} returned text content.")
                return ToolInterpretation(summary=f"{tool_name} returned text content.", sufficient=bool(text), focus_resources=tuple(resources), evidence_notes=tuple(notes))
            if "docs_ingested" in output:
                count = int(output.get("docs_ingested") or 0)
                notes.append(f"{tool_name} ingested {count} document(s).")
                return ToolInterpretation(summary=f"{tool_name} ingested {count} document(s).", sufficient=count > 0, focus_resources=tuple(resources), evidence_notes=tuple(notes))
            return ToolInterpretation(summary=f"{tool_name} completed successfully.", sufficient=True, focus_resources=tuple(resources), evidence_notes=tuple(notes))
        return ToolInterpretation(summary=f"{tool_name} completed successfully.", sufficient=True)
