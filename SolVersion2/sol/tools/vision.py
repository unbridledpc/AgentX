from __future__ import annotations

from typing import Any

from sol.tools.base import Tool, ToolArgument, ToolExecutionError


class VisionStubTool(Tool):
    name = "vision.status"
    description = "Vision/webcam pipeline status (stub). No face recognition."
    args = ()
    safety_flags = ("vision",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "enabled": bool(ctx.cfg.vision.enabled),
            "device_index": int(ctx.cfg.vision.device_index),
            "note": "Stub only. Add a real webcam capture pipeline later.",
        }

