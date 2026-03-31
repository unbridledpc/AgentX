from __future__ import annotations

from typing import Any

from sol.tools.base import Tool, ToolArgument, ToolExecutionError


class VoiceStubTool(Tool):
    name = "voice.status"
    description = "Voice pipeline status (stub). Hardware integration is not implemented in SolVersion2."
    args = ()
    safety_flags = ("voice",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "enabled": bool(ctx.cfg.voice.enabled),
            "wake_word_enabled": bool(ctx.cfg.voice.wake_word_enabled),
            "wake_word": ctx.cfg.voice.wake_word,
            "mic_device": ctx.cfg.voice.mic_device,
            "note": "Stub only. Add a real audio capture/wake-word implementation later.",
        }

