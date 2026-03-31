from __future__ import annotations

from sol.tools.base import Tool, ToolArgument


class DemoEchoUpperTool(Tool):
    name = "demo.echo_upper"
    description = "Return the input text upper-cased."
    args = (ToolArgument(name="text", type=str, description="Text to transform", required=True),)

    def run(self, ctx, args: dict[str, object]) -> dict[str, object]:
        text = str(args.get("text") or "")
        return {"ok": True, "text": text.upper()}


def register(api):
    _ = api
    return [DemoEchoUpperTool()]
