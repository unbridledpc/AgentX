from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Iterable

from agentx.config import AgentXConfig
from agentx.tools.base import Tool
from agentx.tools.registry import ToolRegistry

from .models import PluginManifest, PluginRecord, PluginToolSpec


class PluginError(RuntimeError):
    pass


class PluginValidationError(PluginError):
    pass


class PluginLoadError(PluginError):
    pass


class PluginApi:
    def __init__(self, *, manifest: PluginManifest, plugin_root: Path):
        self.manifest = manifest
        self.plugin_root = plugin_root


class PluginManager:
    def __init__(self, *, cfg: AgentXConfig, runtime_paths) -> None:
        self.cfg = cfg
        self.runtime_paths = runtime_paths
        self._records: dict[str, PluginRecord] = {}
        self._tool_to_plugin: dict[str, PluginRecord] = {}

    def list_plugins(self) -> list[PluginRecord]:
        self._discover_if_needed()
        return sorted(self._records.values(), key=lambda r: r.manifest.plugin_id)

    def get_plugin(self, plugin_id: str) -> PluginRecord | None:
        self._discover_if_needed()
        return self._records.get((plugin_id or "").strip().lower())

    def get_tool_plugin(self, tool_name: str) -> PluginRecord | None:
        self._discover_if_needed()
        return self._tool_to_plugin.get((tool_name or "").strip().lower())

    def is_enabled(self, plugin_id: str) -> bool:
        rec = self.get_plugin(plugin_id)
        return bool(rec and rec.enabled and not rec.error)

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginRecord:
        self._discover_if_needed()
        key = (plugin_id or "").strip().lower()
        if key not in self._records:
            raise PluginError(f"Plugin not found: {plugin_id}")
        state = self._load_state()
        state[key] = bool(enabled)
        self._write_state(state)
        self._records = {}
        self._tool_to_plugin = {}
        self._discover_if_needed()
        rec = self._records[key]
        return rec

    def register_enabled_tools(self, registry: ToolRegistry) -> None:
        self._discover_if_needed()
        for rec in self.list_plugins():
            if not rec.enabled or rec.error:
                continue
            tools = self._load_tools(rec)
            loaded_names = tuple(sorted(t.name for t in tools))
            self._records[rec.manifest.plugin_id] = PluginRecord(
                manifest=rec.manifest,
                root_dir=rec.root_dir,
                enabled=rec.enabled,
                source=rec.source,
                error=None,
                loaded_tool_names=loaded_names,
            )
            for tool in tools:
                registry.register(
                    tool,
                    metadata={
                        "source": f"plugin:{rec.manifest.plugin_id}",
                        "plugin_id": rec.manifest.plugin_id,
                        "risk_level": rec.manifest.risk_level,
                        "permissions": list(rec.manifest.permissions),
                    },
                )
                self._tool_to_plugin[tool.name.lower()] = self._records[rec.manifest.plugin_id]

    def _discover_if_needed(self) -> None:
        if self._records:
            return
        self._records = {}
        self._tool_to_plugin = {}
        state = self._load_state()
        for base, source in (
            (self.runtime_paths.builtin_plugins_dir, "builtin"),
            (self.runtime_paths.runtime_plugins_dir, "runtime"),
        ):
            if not base.exists():
                continue
            for child in sorted(base.iterdir()):
                if not child.is_dir():
                    continue
                manifest_path = child / "manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    manifest = self._load_manifest(manifest_path)
                    enabled = bool(state.get(manifest.plugin_id, manifest.enabled_by_default))
                    self._records[manifest.plugin_id] = PluginRecord(
                        manifest=manifest,
                        root_dir=child,
                        enabled=enabled,
                        source=source,
                    )
                except Exception as e:
                    key = child.name.strip().lower()
                    fallback = PluginManifest(
                        plugin_id=key or "invalid",
                        name=child.name,
                        version="0.0.0",
                        description="Invalid plugin",
                        entrypoint="",
                        permissions=tuple(),
                        risk_level="high",
                        tools=tuple(),
                        enabled_by_default=False,
                    )
                    self._records[fallback.plugin_id] = PluginRecord(
                        manifest=fallback,
                        root_dir=child,
                        enabled=False,
                        source=source,
                        error=str(e),
                    )

    def _load_state(self) -> dict[str, bool]:
        path = self.runtime_paths.plugin_state_path
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise PluginError(f"Failed to read plugin state: {e}") from e
        if not isinstance(raw, dict):
            return {}
        out: dict[str, bool] = {}
        for k, v in raw.items():
            if isinstance(k, str) and k.strip():
                out[k.strip().lower()] = bool(v)
        return out

    def _write_state(self, state: dict[str, bool]) -> None:
        path = self.runtime_paths.plugin_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def _load_manifest(self, manifest_path: Path) -> PluginManifest:
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise PluginValidationError(f"Invalid manifest JSON in {manifest_path}: {e}") from e
        if not isinstance(raw, dict):
            raise PluginValidationError(f"Plugin manifest must be an object: {manifest_path}")
        plugin_id = str(raw.get("id") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", plugin_id):
            raise PluginValidationError(f"Invalid plugin id: {plugin_id!r}")
        tools_raw = raw.get("tools")
        tools: list[PluginToolSpec] = []
        if not isinstance(tools_raw, list) or not tools_raw:
            raise PluginValidationError("Plugin manifest must declare at least one tool.")
        for item in tools_raw:
            if isinstance(item, str):
                name = item.strip()
                desc = ""
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                desc = str(item.get("description") or "").strip()
            else:
                raise PluginValidationError("Plugin tools entries must be strings or objects.")
            if not re.fullmatch(r"[a-z0-9._-]{2,128}", name.lower()):
                raise PluginValidationError(f"Invalid plugin tool name: {name!r}")
            tools.append(PluginToolSpec(name=name.lower(), description=desc))

        risk = str(raw.get("risk_level") or "medium").strip().lower()
        if risk not in {"low", "medium", "high", "critical"}:
            raise PluginValidationError(f"Invalid plugin risk level: {risk!r}")

        permissions_raw = raw.get("permissions")
        permissions: list[str] = []
        if isinstance(permissions_raw, list):
            for p in permissions_raw:
                if isinstance(p, str) and p.strip():
                    permissions.append(p.strip().lower())

        entrypoint = str(raw.get("entrypoint") or "").strip()
        if not entrypoint:
            raise PluginValidationError("Plugin manifest missing entrypoint.")

        return PluginManifest(
            plugin_id=plugin_id,
            name=str(raw.get("name") or plugin_id).strip() or plugin_id,
            version=str(raw.get("version") or "0.0.0").strip() or "0.0.0",
            description=str(raw.get("description") or "").strip(),
            entrypoint=entrypoint,
            permissions=tuple(permissions),
            risk_level=risk,
            tools=tuple(tools),
            enabled_by_default=bool(raw.get("enabled_by_default", False)),
        )

    def _load_tools(self, rec: PluginRecord) -> list[Tool]:
        entry = rec.manifest.entrypoint
        rel, func_name = entry, "register"
        if ":" in entry:
            rel, func_name = entry.split(":", 1)
        entry_path = (rec.root_dir / rel).resolve()
        if not entry_path.exists():
            raise PluginLoadError(f"Plugin entrypoint not found: {entry_path}")
        spec = importlib.util.spec_from_file_location(f"agentx_plugin_{rec.manifest.plugin_id}", entry_path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Could not load plugin module: {entry_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, func_name, None)
        if not callable(fn):
            raise PluginLoadError(f"Plugin entrypoint callable not found: {func_name}")
        result = fn(PluginApi(manifest=rec.manifest, plugin_root=rec.root_dir))
        tools = self._normalize_tools(result)
        declared = {t.name for t in rec.manifest.tools}
        actual = {t.name.lower() for t in tools}
        if actual != declared:
            raise PluginLoadError(
                f"Plugin {rec.manifest.plugin_id} tools mismatch. declared={sorted(declared)} actual={sorted(actual)}"
            )
        return tools

    @staticmethod
    def _normalize_tools(result: Any) -> list[Tool]:
        if isinstance(result, Tool):
            return [result]
        if isinstance(result, Iterable):
            out: list[Tool] = []
            for item in result:
                if not isinstance(item, Tool):
                    raise PluginLoadError("Plugin register() must return Tool or iterable[Tool].")
                out.append(item)
            if not out:
                raise PluginLoadError("Plugin register() returned no tools.")
            return out
        raise PluginLoadError("Plugin register() must return Tool or iterable[Tool].")
