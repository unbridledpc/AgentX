from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from agentx.tools.base import Tool, ToolValidationError


TOOL_NAME_ALIASES: dict[str, str] = {
    # snake_case aliases for dotted tools
    "fs_list": "fs.list",
    "fs_read_text": "fs.read_text",
    "fs_write_text": "fs.write_text",
    "web_search": "web.search",
    "web_fetch": "web.fetch",
}


def normalize_tool_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return raw
    low = raw.lower()
    return TOOL_NAME_ALIASES.get(low, low)


def aliases_for_tool(name: str) -> list[str]:
    canonical = normalize_tool_name(name)
    out = [alias for (alias, target) in TOOL_NAME_ALIASES.items() if target == canonical]
    return sorted(set(out))


def _type_to_schema(t: type | tuple[type, ...]) -> str:
    # Best-effort mapping for UI templates/labels.
    types: tuple[type, ...] = (t,) if isinstance(t, type) else t
    if any(x is str for x in types):
        return "string"
    if any(x is bool for x in types):
        return "boolean"
    if any(x is int for x in types):
        return "integer"
    if any(x is float for x in types):
        return "number"
    if any(x is list for x in types):
        return "array"
    if any(x is dict for x in types):
        return "object"
    return "any"


@dataclass
class ToolRegistry:
    _tools: Dict[str, Tool]
    _tool_meta: Dict[str, dict[str, Any]]

    def __init__(self) -> None:
        self._tools = {}
        self._tool_meta = {}

    def register(self, tool: Tool, *, metadata: dict[str, Any] | None = None) -> None:
        key = tool.name.lower()
        self._tools[key] = tool
        self._tool_meta[key] = dict(metadata or {})

    def list_tools(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: t.name.lower())

    def get_tool(self, name: str) -> Optional[Tool]:
        if not name:
            return None
        key = normalize_tool_name(name)
        tool = self._tools.get(key)
        if tool:
            return tool
        return None

    def get_metadata(self, name: str) -> dict[str, Any]:
        key = normalize_tool_name(name)
        return dict(self._tool_meta.get(key, {}))

    def prepare(self, name: str, raw_args: dict[str, Any]) -> tuple[Tool, dict[str, Any]]:
        tool = self.get_tool(name)
        if not tool:
            raise KeyError(name)
        validated = tool.validate_args(raw_args or {})
        return tool, validated

    def prepare_for_execution(self, name: str, raw_args: dict[str, Any], *, reason: str) -> tuple[Tool, dict[str, Any]]:
        """Prepare a tool call for execution (validation + reason enforcement).

        Execution is intended to be orchestrated by the Agent loop. This method only:
        - enforces non-empty reason metadata
        - validates args against the tool schema
        - injects reason into tool args if the tool declares a `reason` parameter
        """

        reason_s = (reason or "").strip()
        if not reason_s:
            raise ToolValidationError("Missing required reason.")

        raw = dict(raw_args or {})
        # Prevent callers from smuggling an empty or conflicting reason in raw args.
        if "reason" in raw:
            raw.pop("reason", None)

        tool, validated = self.prepare(normalize_tool_name(name), raw)
        if any(a.name == "reason" for a in getattr(tool, "args", ())):
            validated = dict(validated)
            validated["reason"] = reason_s
        return tool, validated

    def schema(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for tool in self.list_tools():
            args = []
            for a in getattr(tool, "args", ()) or ():
                args.append(
                    {
                        "name": a.name,
                        "type": _type_to_schema(a.type),
                        "required": bool(a.required),
                        "description": a.description,
                    }
                )
            tools.append(
                {
                    "name": tool.name,
                    "aliases": [a for a in aliases_for_tool(tool.name) if a != tool.name],
                    "description": getattr(tool, "description", "") or "",
                    "args": args,
                    "source": self.get_metadata(tool.name).get("source", "builtin"),
                    "plugin_id": self.get_metadata(tool.name).get("plugin_id"),
                    "risk_level": self.get_metadata(tool.name).get("risk_level", "medium"),
                    "permissions": self.get_metadata(tool.name).get("permissions", []),
                }
            )
        return sorted(tools, key=lambda t: str(t.get("name") or "").lower())


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    # Import locally to avoid circular imports at module load.
    from agentx.tools.fs import (
        FsDeleteTool,
        FsGrepTool,
        FsListTool,
        FsMoveTool,
        FsReadTool,
        FsWriteTool,
    )
    from agentx.tools.exec import ExecRunTool
    from agentx.tools.monster import MonsterGenerateTool
    from agentx.tools.rag import RagIngestPathTool, RagQueryTool, RagUpsertTextTool
    from agentx.tools.repo import RepoFetchFileTool, RepoIngestTool, RepoTreeTool
    from agentx.tools.selfcheck import SelfCheckRunTool
    from agentx.tools.tibia import TibiaIngestThreadTool, TibiaLearnTool, TibiaSearchSourcesTool
    from agentx.tools.web import WebCrawlTool, WebFetchTool, WebSearchTool
    from agentx.tools.web_ingest import WebIngestCrawlTool
    from agentx.tools.web_ingest_url import WebIngestUrlTool
    from agentx.tools.voice import VoiceStubTool
    from agentx.tools.vision import VisionStubTool
    from agentx.tools.hermesbk_tools import register_hermesbk_tools

    for t in (
        FsListTool(),
        FsReadTool(),
        FsWriteTool(),
        FsMoveTool(),
        FsDeleteTool(),
        FsGrepTool(),
        ExecRunTool(),
        WebFetchTool(),
        WebSearchTool(),
        WebCrawlTool(),
        WebIngestCrawlTool(),
        WebIngestUrlTool(),
        RepoTreeTool(),
        RepoFetchFileTool(),
        RepoIngestTool(),
        RagUpsertTextTool(),
        RagQueryTool(),
        RagIngestPathTool(),
        MonsterGenerateTool(),
        VoiceStubTool(),
        VisionStubTool(),
        SelfCheckRunTool(),
        TibiaSearchSourcesTool(),
        TibiaIngestThreadTool(),
        TibiaLearnTool(),
    ):
        reg.register(t)

    # Hermes.BK tool-pack compatibility names (fs_list/http_get/devtools).
    register_hermesbk_tools(reg)
    return reg
