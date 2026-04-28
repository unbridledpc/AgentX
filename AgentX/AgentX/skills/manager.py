from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from agentx.config import AgentXConfig

from .models import SkillRecord


class SkillError(RuntimeError):
    pass


class SkillImportError(SkillError):
    pass


def _parse_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, Any] = {}
    current_list_key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and current_list_key:
            meta.setdefault(current_list_key, [])
            if isinstance(meta[current_list_key], list):
                meta[current_list_key].append(line[4:].strip())
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value == "":
            meta[key] = []
            current_list_key = key
            continue
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
                meta[key] = parsed
                continue
            except Exception:
                pass
        if value.lower() in {"true", "false"}:
            meta[key] = value.lower() == "true"
            continue
        meta[key] = value.strip("\"'")
    return meta, body


class SkillManager:
    def __init__(self, *, cfg: AgentXConfig, runtime_paths) -> None:
        self.cfg = cfg
        self.runtime_paths = runtime_paths
        self._skills: dict[str, SkillRecord] = {}

    def list_skills(self) -> list[SkillRecord]:
        self._discover_if_needed()
        return sorted(self._skills.values(), key=lambda s: s.skill_id)

    def get_skill(self, skill_id: str | None) -> SkillRecord | None:
        self._discover_if_needed()
        if not skill_id:
            return None
        return self._skills.get(skill_id.strip().lower())

    def import_skill_pack(self, source_dir: str, *, skill_id: str | None = None) -> SkillRecord:
        src = Path(source_dir).expanduser().resolve()
        if not src.exists() or not src.is_dir():
            raise SkillImportError(f"Skill source directory not found: {source_dir}")
        skill_md = src / "SKILL.md"
        if not skill_md.exists():
            raise SkillImportError("Skill pack import requires SKILL.md.")
        text = skill_md.read_text(encoding="utf-8")
        meta, body = _parse_yaml_frontmatter(text)
        derived_id = (skill_id or meta.get("id") or src.name).strip().lower().replace(" ", "_")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", derived_id):
            raise SkillImportError(f"Invalid imported skill id: {derived_id!r}")
        dst = self.runtime_paths.skill_imports_dir / derived_id
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        metadata = {
            "id": derived_id,
            "name": str(meta.get("name") or derived_id).strip() or derived_id,
            "description": str(meta.get("description") or "").strip(),
            "required_plugins": list(self._as_list_str(meta.get("required_plugins"))),
            "memory_namespace": str(meta.get("memory_namespace") or derived_id).strip() or derived_id,
            "risk_level": self._normalize_risk(meta.get("risk_level")),
            "examples": list(self._as_list_str(meta.get("examples"))),
            "supporting_files": sorted(str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file() and p.name != "metadata.json"),
            "source": "runtime_import",
        }
        (dst / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        self._skills = {}
        rec = self.get_skill(derived_id)
        if rec is None:
            raise SkillImportError("Imported skill could not be loaded after import.")
        # Preserve normalized body without losing existing SKILL.md content.
        if body is not None:
            _ = body
        return rec

    def _discover_if_needed(self) -> None:
        if self._skills:
            return
        self._skills = {}
        for root, source in (
            (self.runtime_paths.builtin_skills_dir, "builtin"),
            (self.runtime_paths.runtime_skills_dir, "runtime"),
        ):
            if not root.exists():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                rec = self._load_skill_dir(child, source=source)
                if rec:
                    self._skills[rec.skill_id] = rec

    def _load_skill_dir(self, path: Path, *, source: str) -> SkillRecord | None:
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            return None
        text = skill_md.read_text(encoding="utf-8")
        frontmatter, body = _parse_yaml_frontmatter(text)
        metadata_path = path / "metadata.json"
        meta: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta.update(loaded)
            except Exception as e:
                raise SkillError(f"Invalid skill metadata in {metadata_path}: {e}") from e
        meta.update({k: v for k, v in frontmatter.items() if k not in meta})
        skill_id = str(meta.get("id") or path.name).strip().lower().replace(" ", "_")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", skill_id):
            raise SkillError(f"Invalid skill id: {skill_id!r}")
        supporting = sorted(
            str(p.relative_to(path))
            for p in path.rglob("*")
            if p.is_file() and p.name not in {"SKILL.md", "metadata.json"}
        )
        return SkillRecord(
            skill_id=skill_id,
            name=str(meta.get("name") or skill_id).strip() or skill_id,
            description=str(meta.get("description") or "").strip(),
            required_plugins=tuple(self._as_list_str(meta.get("required_plugins"))),
            memory_namespace=str(meta.get("memory_namespace") or skill_id).strip() or skill_id,
            risk_level=self._normalize_risk(meta.get("risk_level")),
            examples=tuple(self._as_list_str(meta.get("examples"))),
            supporting_files=tuple(supporting),
            source=source,
            root_dir=path,
            skill_path=skill_md,
            metadata_path=metadata_path if metadata_path.exists() else None,
            instructions=body.strip(),
        )

    @staticmethod
    def _as_list_str(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _normalize_risk(value: Any) -> str:
        risk = str(value or "medium").strip().lower()
        if risk not in {"low", "medium", "high", "critical"}:
            return "medium"
        return risk
