#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PACKAGE = REPO_ROOT / "agentx"

# These are true stale Python package/source trees after unification.
# All real AgentX Python source should live under agentx/.
FORBIDDEN_SOURCE_PATHS = [
    REPO_ROOT / "AgentX",
    REPO_ROOT / "core",
    REPO_ROOT / "cli",
    REPO_ROOT / "tools",
    REPO_ROOT / "jobs",
    REPO_ROOT / "install",
    REPO_ROOT / "learning",
]

# These top-level folders are allowed as extension/runtime locations,
# but they must not contain Python source that shadows the canonical package.
ALLOWED_NONCANONICAL_DIRS = [
    REPO_ROOT / "plugins",
    REPO_ROOT / "skills",
    REPO_ROOT / "runtime",
]

REQUIRED_CANONICAL_PATHS = [
    CANONICAL_PACKAGE / "__init__.py",
    CANONICAL_PACKAGE / "__main__.py",
    CANONICAL_PACKAGE / "cli" / "__init__.py",
    CANONICAL_PACKAGE / "cli" / "__main__.py",
    CANONICAL_PACKAGE / "core" / "memory.py",
    CANONICAL_PACKAGE / "core" / "project_memory.py",
    CANONICAL_PACKAGE / "core" / "reflection.py",
]


def _contains_python_source(path: Path) -> bool:
    if not path.exists():
        return False
    return any(
        item.is_file()
        and item.suffix == ".py"
        and "__pycache__" not in item.parts
        for item in path.rglob("*.py")
    )


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    if not CANONICAL_PACKAGE.is_dir():
        errors.append(f"missing canonical package directory: {CANONICAL_PACKAGE.relative_to(REPO_ROOT)}")

    for path in REQUIRED_CANONICAL_PATHS:
        if not path.exists():
            errors.append(f"missing required canonical file: {path.relative_to(REPO_ROOT)}")

    for path in FORBIDDEN_SOURCE_PATHS:
        if path.exists():
            errors.append(
                f"stale duplicate source tree exists: {path.relative_to(REPO_ROOT)}; "
                "move source into agentx/ instead"
            )

    for path in ALLOWED_NONCANONICAL_DIRS:
        if _contains_python_source(path):
            warnings.append(
                f"allowed noncanonical directory contains Python files: {path.relative_to(REPO_ROOT)}; "
                "verify these are extensions/runtime files, not duplicate AgentX package source"
            )

    if errors:
        print("AgentX package tree check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        if warnings:
            print("Warnings:", file=sys.stderr)
            for warning in warnings:
                print(f"- {warning}", file=sys.stderr)
        return 1

    print("AgentX package tree OK: canonical source package is agentx/.")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
