from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sol.config import SolConfig


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    jobs_dir: Path
    jobs_index_path: Path
    plugin_state_path: Path
    skill_imports_dir: Path
    runtime_plugins_dir: Path
    builtin_plugins_dir: Path
    runtime_skills_dir: Path
    builtin_skills_dir: Path
    learned_hints_path: Path
    cache_dir: Path


def build_runtime_paths(cfg: SolConfig) -> RuntimePaths:
    root = cfg.paths.runtime_dir
    return RuntimePaths(
        root=root,
        jobs_dir=root / "jobs",
        jobs_index_path=root / "jobs" / "index.json",
        plugin_state_path=root / "plugins" / "state.json",
        skill_imports_dir=cfg.paths.user_skills_dir,
        runtime_plugins_dir=cfg.paths.user_plugins_dir,
        builtin_plugins_dir=cfg.paths.plugins_dir,
        runtime_skills_dir=cfg.paths.user_skills_dir,
        builtin_skills_dir=cfg.paths.skills_dir,
        learned_hints_path=root / "learning" / "hints.jsonl",
        cache_dir=root / "cache",
    )


def ensure_runtime_dirs(paths: RuntimePaths) -> None:
    for d in (
        paths.root,
        paths.jobs_dir,
        paths.plugin_state_path.parent,
        paths.runtime_plugins_dir,
        paths.skill_imports_dir,
        paths.learned_hints_path.parent,
        paths.cache_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)
