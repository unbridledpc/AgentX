from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillRecord:
    skill_id: str
    name: str
    description: str
    required_plugins: tuple[str, ...]
    memory_namespace: str
    risk_level: str
    examples: tuple[str, ...]
    supporting_files: tuple[str, ...]
    source: str
    root_dir: Path
    skill_path: Path
    metadata_path: Path | None
    instructions: str
