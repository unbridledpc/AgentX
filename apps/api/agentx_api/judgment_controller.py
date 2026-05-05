from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Literal

JudgmentRoute = Literal["FAST", "HOLD", "BLOCK", "DEEP", "RECOVER"]


@dataclass(frozen=True)
class JudgmentResult:
    ok: bool
    route: JudgmentRoute
    endpoint: str | None
    reason: str
    confidence: float
    signals: dict[str, Any]


_CODE_PATTERNS = (
    r"```",
    r"\bdef\s+\w+\(",
    r"\bclass\s+\w+",
    r"\bfunction\s+\w+\(",
    r"\bimport\s+[\w.]+",
    r"\bfrom\s+[\w.]+\s+import\b",
    r"\bconst\s+\w+\s*=",
    r"\blet\s+\w+\s*=",
    r"\binterface\s+\w+",
    r"\btype\s+\w+\s*=",
    r"\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b",
)

_ERROR_PATTERNS = (
    r"\btraceback\b",
    r"\bstack trace\b",
    r"\bexception\b",
    r"\berror:",
    r"\bfatal:",
    r"\bfailed\b",
    r"\bsyntaxerror\b",
    r"\btypeerror\b",
    r"\bmodule not found\b",
    r"\bno module named\b",
    r"\bpytest\b.*\bfailed\b",
    r"\bnpm\b.*\berror\b",
    r"\bts\d{4}\b",
)

_PATCH_PATTERNS = (
    r"\bgit apply\b",
    r"\bdiff --git\b",
    r"\bpatch\b",
    r"\bcommit\b",
    r"\bmerge\b",
    r"\btag\b",
    r"\bpush\b",
    r"\bbranch\b",
    r"\bfix\b.*\bfile\b",
    r"\bcreate\b.*\bfile\b",
)

_DESTRUCTIVE_PATTERNS = (
    r"\brm\s+-rf\s+/",
    r"\bdd\s+if=",
    r"\bmkfs\.",
    r"\bformat\s+[a-z]:",
    r"\bdel\s+/s\s+/q\s+c:\\",
    r"\bdrop\s+database\b",
    r"\btruncate\s+table\b",
    r"\bdelete\s+from\b.*\bwhere\s+1\s*=\s*1\b",
    r"\bchmod\s+-R\s+777\s+/",
    r"\bchown\s+-R\b.*\s+/",
)

_CLARIFY_PATTERNS = (
    r"\bwhich\b.*\bfile\b",
    r"\bwhat\b.*\bpath\b",
    r"\bneed\b.*\bmore\b",
    r"\bnot sure\b",
)


def _has_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL) for pattern in patterns)


def _estimate_tokens(text: str) -> int:
    # Cheap local estimate; good enough for pre-inference routing.
    return max(1, len(text) // 4)


def classify_judgment(text: str, *, context_turns: int = 0, previous_error: bool = False) -> dict[str, Any]:
    raw = text or ""
    stripped = raw.strip()
    token_estimate = _estimate_tokens(stripped) if stripped else 0

    signals: dict[str, Any] = {
        "chars": len(stripped),
        "estimated_tokens": token_estimate,
        "context_turns": max(0, int(context_turns or 0)),
        "has_code": _has_any(_CODE_PATTERNS, stripped),
        "has_error_log": _has_any(_ERROR_PATTERNS, stripped),
        "has_patch_or_repo_action": _has_any(_PATCH_PATTERNS, stripped),
        "destructive_intent": _has_any(_DESTRUCTIVE_PATTERNS, stripped),
        "looks_incomplete": _has_any(_CLARIFY_PATTERNS, stripped),
        "long_context": token_estimate >= 1200 or len(stripped.splitlines()) >= 80,
        "previous_error": bool(previous_error),
    }

    if not stripped:
        return asdict(JudgmentResult(
            ok=True,
            route="HOLD",
            endpoint="default",
            reason="Empty input; wait for a user request before calling a model.",
            confidence=0.99,
            signals=signals,
        ))

    if signals["destructive_intent"]:
        return asdict(JudgmentResult(
            ok=False,
            route="BLOCK",
            endpoint=None,
            reason="Input appears to request a destructive or high-risk operation.",
            confidence=0.92,
            signals=signals,
        ))

    if signals["previous_error"] or signals["has_error_log"]:
        return asdict(JudgmentResult(
            ok=True,
            route="RECOVER",
            endpoint="heavy",
            reason="Error/log recovery should use the heavier repair route.",
            confidence=0.88,
            signals=signals,
        ))

    if signals["long_context"] or signals["has_code"] or signals["has_patch_or_repo_action"]:
        return asdict(JudgmentResult(
            ok=True,
            route="DEEP",
            endpoint="heavy",
            reason="Coding, repo actions, patches, or long context should use deep reasoning.",
            confidence=0.84,
            signals=signals,
        ))

    if signals["looks_incomplete"] and token_estimate < 80:
        return asdict(JudgmentResult(
            ok=True,
            route="HOLD",
            endpoint="default",
            reason="Input appears to need clarification before inference.",
            confidence=0.64,
            signals=signals,
        ))

    return asdict(JudgmentResult(
        ok=True,
        route="FAST",
        endpoint="fast",
        reason="Short/simple request can use the fast route.",
        confidence=0.78,
        signals=signals,
    ))


def judgment_policy() -> dict[str, Any]:
    return {
        "version": "0.1",
        "routes": {
            "FAST": {"endpoint": "fast", "description": "Short/simple requests that do not need heavy reasoning."},
            "HOLD": {"endpoint": "default", "description": "Clarify, wait, or avoid inference because required context is missing."},
            "BLOCK": {"endpoint": None, "description": "High-risk/destructive request. Do not call a model route automatically."},
            "DEEP": {"endpoint": "heavy", "description": "Coding, architecture, patch generation, or long-context reasoning."},
            "RECOVER": {"endpoint": "heavy", "description": "Failure recovery, logs, stack traces, and repair loops."},
        },
        "signals": [
            "chars",
            "estimated_tokens",
            "context_turns",
            "has_code",
            "has_error_log",
            "has_patch_or_repo_action",
            "destructive_intent",
            "looks_incomplete",
            "long_context",
            "previous_error",
        ],
    }
