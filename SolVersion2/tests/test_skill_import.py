from __future__ import annotations

from sol.config import load_config
from sol.runtime.paths import build_runtime_paths, ensure_runtime_dirs
from sol.skills.manager import SkillManager

from conftest import write_test_config


def test_import_skill_pack_preserves_supporting_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_test_config(tmp_path)
    source = tmp_path / "skill_pack"
    source.mkdir()
    (source / "SKILL.md").write_text(
        """---
id: import_me
name: Import Me
required_plugins:
  - echo_demo
memory_namespace: import_me
---

# Import Me

Use this for testing.
""",
        encoding="utf-8",
    )
    (source / "helper.txt").write_text("hello\n", encoding="utf-8")

    cfg = load_config("config/sol.toml")
    runtime_paths = build_runtime_paths(cfg)
    ensure_runtime_dirs(runtime_paths)
    mgr = SkillManager(cfg=cfg, runtime_paths=runtime_paths)
    rec = mgr.import_skill_pack(str(source))
    assert rec.skill_id == "import_me"
    assert rec.source == "runtime"
    assert "helper.txt" in rec.supporting_files


def test_runtime_skill_overrides_builtin_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_test_config(tmp_path)
    builtin = tmp_path / "skills" / "triage"
    runtime = tmp_path / "extensions" / "skills" / "triage"
    builtin.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (builtin / "SKILL.md").write_text("# Builtin\nbuiltin\n", encoding="utf-8")
    (runtime / "SKILL.md").write_text("# Runtime\nruntime\n", encoding="utf-8")

    cfg = load_config("config/sol.toml")
    runtime_paths = build_runtime_paths(cfg)
    ensure_runtime_dirs(runtime_paths)
    mgr = SkillManager(cfg=cfg, runtime_paths=runtime_paths)
    rec = mgr.get_skill("triage")
    assert rec is not None
    assert rec.source == "runtime"
    assert "runtime" in rec.instructions
