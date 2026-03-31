from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PluginToolSpec:
    name: str
    description: str = ""


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    description: str
    entrypoint: str
    permissions: tuple[str, ...]
    risk_level: str
    tools: tuple[PluginToolSpec, ...]
    enabled_by_default: bool


@dataclass(frozen=True)
class PluginRecord:
    manifest: PluginManifest
    root_dir: Path
    enabled: bool
    source: str = "builtin"
    error: str | None = None
    loaded_tool_names: tuple[str, ...] = field(default_factory=tuple)
