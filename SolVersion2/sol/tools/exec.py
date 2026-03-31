from __future__ import annotations

from typing import Any

from sol.core.executor import ExecPolicyError, run_command
from sol.tools.base import Tool, ToolArgument, ToolExecutionError


class ExecRunTool(Tool):
    name = "exec.run"
    description = "Run a command under a controlled executor (allowlist + timeout)"
    destructive = True
    args = (
        ToolArgument("cmd", str, "Command line to run", required=True),
        ToolArgument("cwd", str, "Optional working directory", required=False, default=""),
        ToolArgument("reason", str, "Reason for executing this command", required=False, default=""),
    )
    safety_flags = ("exec",)
    requires_confirmation = True

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        try:
            res = run_command(cmd=args["cmd"], cwd=(args.get("cwd") or None), cfg=ctx.cfg)
        except ExecPolicyError as e:
            raise ToolExecutionError(str(e))
        return {
            "cmd": res.cmd,
            "cwd": res.cwd,
            "returncode": res.returncode,
            "stdout": res.stdout[-20000:],
            "stderr": res.stderr[-20000:],
            "duration_ms": res.duration_ms,
        }
