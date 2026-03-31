from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AuditEvent:
    ts: float
    mode: str
    event: str  # tool_start | tool_end | agent_info
    tool: str | None
    args: dict[str, Any] | None
    reason: str | None
    duration_ms: float | None
    success: bool | None
    summary: str | None
    error: str | None
    invocation_id: str | None = None


class AuditLog:
    """Append-only audit log.

    Design goals:
    - Machine readable JSONL
    - Fail-closed: agent checks writability before executing tools
    - Never raises from append(): returns (ok, error_message)
    """

    def __init__(self, log_path: Path):
        self.log_path = log_path

    def ensure_writable(self) -> tuple[bool, str | None]:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            # Open for append and immediately close to validate permissions.
            with self.log_path.open("a", encoding="utf-8"):
                pass
            return True, None
        except Exception as e:
            return False, str(e)

    def append(self, event: AuditEvent) -> tuple[bool, str | None]:
        payload = {
            "ts": event.ts,
            "mode": event.mode,
            "event": event.event,
            "tool": event.tool,
            "args": event.args,
            "reason": event.reason,
            "duration_ms": event.duration_ms,
            "success": event.success,
            "summary": event.summary,
            "error": event.error,
            "invocation_id": event.invocation_id,
        }
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False)
            self.log_path.open("a", encoding="utf-8").write(line + "\n")
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def new_invocation_id() -> str:
        return uuid.uuid4().hex

    def tool_start(self, *, mode: str, tool: str, args: dict[str, Any], reason: str) -> tuple[str, tuple[bool, str | None]]:
        inv = self.new_invocation_id()
        ok, err = self.append(
            AuditEvent(
                ts=time.time(),
                mode=mode,
                event="tool_start",
                tool=tool,
                args=args,
                reason=reason,
                duration_ms=None,
                success=None,
                summary=None,
                error=None,
                invocation_id=inv,
            )
        )
        return inv, (ok, err)

    def tool_end(
        self,
        *,
        mode: str,
        tool: str,
        args: dict[str, Any],
        reason: str,
        invocation_id: str,
        duration_ms: float,
        success: bool,
        summary: str,
        error: str | None,
    ) -> tuple[bool, str | None]:
        return self.append(
            AuditEvent(
                ts=time.time(),
                mode=mode,
                event="tool_end",
                tool=tool,
                args=args,
                reason=reason,
                duration_ms=duration_ms,
                success=success,
                summary=summary,
                error=error,
                invocation_id=invocation_id,
            )
        )

    def tail(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return the last N audit events (best-effort).

        This is used by UI surfaces to display recent activity.
        """

        n = max(1, min(int(limit), 1000))
        if not self.log_path.exists():
            return []
        try:
            # Small-ish logs: read all. If huge, this is still bounded by n filtering.
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for line in reversed(lines):
            if len(out) >= n:
                break
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
            except Exception:
                continue
        return list(reversed(out))
