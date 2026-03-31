from __future__ import annotations

import json

from sol.config import load_config
from sol.plugins.manager import PluginManager
from sol.runtime.paths import build_runtime_paths, ensure_runtime_dirs
from sol.tools.registry import ToolRegistry

from conftest import write_test_config


def test_plugin_manager_discovers_and_registers_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_test_config(tmp_path)
    plugin_dir = tmp_path / "plugins" / "sample_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "sample_plugin",
                "name": "Sample Plugin",
                "version": "1.0.0",
                "description": "Test plugin",
                "entrypoint": "plugin.py:register",
                "permissions": ["text"],
                "risk_level": "low",
                "tools": [{"name": "sample.echo", "description": "Echo text"}],
                "enabled_by_default": True,
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """
from sol.tools.base import Tool, ToolArgument

class SampleEchoTool(Tool):
    name = "sample.echo"
    description = "Echo"
    args = (ToolArgument(name="text", type=str, description="Text", required=True),)

    def run(self, ctx, args):
        return {"text": args["text"]}

def register(api):
    return [SampleEchoTool()]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    cfg = load_config("config/sol.toml")
    runtime_paths = build_runtime_paths(cfg)
    ensure_runtime_dirs(runtime_paths)
    mgr = PluginManager(cfg=cfg, runtime_paths=runtime_paths)
    registry = ToolRegistry()
    mgr.register_enabled_tools(registry)

    tool = registry.get_tool("sample.echo")
    assert tool is not None
    meta = registry.get_metadata("sample.echo")
    assert meta["plugin_id"] == "sample_plugin"
    assert meta["risk_level"] == "low"


def test_runtime_plugin_overrides_builtin_plugin(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_test_config(tmp_path)
    builtin = tmp_path / "plugins" / "sample_plugin"
    builtin.mkdir(parents=True)
    runtime = tmp_path / "extensions" / "plugins" / "sample_plugin"
    runtime.mkdir(parents=True)

    manifest = {
        "id": "sample_plugin",
        "name": "Sample Plugin",
        "version": "1.0.0",
        "description": "Test plugin",
        "entrypoint": "plugin.py:register",
        "permissions": ["text"],
        "risk_level": "low",
        "tools": [{"name": "sample.echo", "description": "Echo text"}],
        "enabled_by_default": True,
    }
    for target, value in ((builtin, "builtin"), (runtime, "runtime")):
        (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (target / "plugin.py").write_text(
            f"""
from sol.tools.base import Tool, ToolArgument

class SampleEchoTool(Tool):
    name = "sample.echo"
    description = "Echo"
    args = (ToolArgument(name="text", type=str, description="Text", required=True),)

    def run(self, ctx, args):
        return {{"text": "{value}"}}

def register(api):
    return [SampleEchoTool()]
""".strip()
            + "\n",
            encoding="utf-8",
        )

    cfg = load_config("config/sol.toml")
    runtime_paths = build_runtime_paths(cfg)
    ensure_runtime_dirs(runtime_paths)
    mgr = PluginManager(cfg=cfg, runtime_paths=runtime_paths)
    registry = ToolRegistry()
    mgr.register_enabled_tools(registry)
    tool = registry.get_tool("sample.echo")
    assert tool is not None
    rec = mgr.get_plugin("sample_plugin")
    assert rec is not None
    assert rec.source == "runtime"
