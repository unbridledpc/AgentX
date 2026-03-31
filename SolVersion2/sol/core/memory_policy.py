from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any

from sol.core.web_policy import registrable_domain
from sol.tools.base import ToolExecutionError


class MemoryPromotionPolicy:
    """Explicit durable-memory promotion rules for tool outputs."""

    def __init__(self, *, agent) -> None:
        self.agent = agent

    def promote_tool_result(self, *, tool, args: dict[str, Any], output: Any) -> None:
        if not (getattr(self.agent.ctx.cfg, "memory", None) and self.agent.ctx.cfg.memory.enabled):
            if tool.name in ("web.ingest_crawl", "repo.ingest", "web.ingest_url", "tibia.ingest_thread", "tibia.learn"):
                raise ToolExecutionError("Memory is disabled; ingestion requires memory.enabled=true.")
            return

        decision = self._classify(tool=tool, output=output)
        if not decision["promote"]:
            return

        # Keep complex manifest-based ingestion behavior intact for now, but make the
        # promotion gate explicit and testable here instead of relying on implicit execution side effects.
        self.agent._post_tool_memory_legacy(tool=tool, args=args, output=output)

    def _classify(self, *, tool, output: Any) -> dict[str, Any]:
        flags = set(getattr(tool, "safety_flags", ()) or ())
        if tool.name in ("web.ingest_crawl", "repo.ingest", "web.ingest_url", "tibia.ingest_thread", "tibia.learn"):
            return {"promote": True, "reason": "durable_ingestion"}
        if "network" not in flags:
            return {"promote": False, "reason": "non_network_tool"}
        if not isinstance(output, dict):
            return {"promote": False, "reason": "non_structured_output"}
        if tool.name == "web.fetch":
            text = str(output.get("text") or "").strip()
            if not text or len(text) < 80:
                return {"promote": False, "reason": "insufficient_fetch_text"}
            return {"promote": True, "reason": "web_fetch_text"}
        if tool.name == "web.crawl":
            pages = output.get("pages")
            if not isinstance(pages, list) or not any(isinstance(p, dict) and str(p.get("text") or "").strip() for p in pages):
                return {"promote": False, "reason": "empty_crawl_pages"}
            return {"promote": True, "reason": "web_crawl_pages"}
        return {"promote": False, "reason": "transient_network_output"}
