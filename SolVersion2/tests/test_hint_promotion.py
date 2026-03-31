from __future__ import annotations

from sol.config import load_config
from sol.learning.hints import HintStore, ReflectionHint
from sol.runtime.paths import build_runtime_paths, ensure_runtime_dirs

from conftest import write_test_config


def test_hint_promotion_requires_repetition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_test_config(tmp_path)
    cfg = load_config("config/sol.toml")
    runtime_paths = build_runtime_paths(cfg)
    ensure_runtime_dirs(runtime_paths)
    store = HintStore(cfg=cfg, runtime_paths=runtime_paths)

    first = store.consider_reflection(
        ReflectionHint(
            failure_signature="sig-1",
            category="validation_error",
            strategy="Inspect the tool schema before retrying.",
            confidence=0.9,
            reusable=True,
            tool_name="fs.write_text",
        )
    )
    assert first is not None
    assert first.status == "observation"

    second = store.consider_reflection(
        ReflectionHint(
            failure_signature="sig-1",
            category="validation_error",
            strategy="Inspect the tool schema before retrying.",
            confidence=0.9,
            reusable=True,
            tool_name="fs.write_text",
        )
    )
    assert second is not None
    assert second.status == "promoted"
    assert store.query(goal="retry fs.write_text safely", tool_names=["fs.write_text"])
