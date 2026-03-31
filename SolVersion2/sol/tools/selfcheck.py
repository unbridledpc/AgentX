from __future__ import annotations

import json
import sys
import os
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from sol.tools.base import Tool, ToolArgument


SelfCheckStatus = Literal["PASS", "FAIL", "WARN", "SKIP"]
SelfCheckMode = Literal["quick", "full"]


@dataclass(frozen=True)
class ProbeResult:
    id: str
    status: SelfCheckStatus
    duration_ms: float
    detail: str
    remediation: list[str]


@dataclass(frozen=True)
class SelfCheckReport:
    ts: float
    mode: SelfCheckMode
    version: str
    overall: SelfCheckStatus
    results: list[ProbeResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "mode": self.mode,
            "version": self.version,
            "overall": self.overall,
            "results": [
                {
                    "id": r.id,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "detail": r.detail,
                    "remediation": list(r.remediation or []),
                }
                for r in self.results
            ],
        }

    def to_text(self) -> str:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts))
        lines: list[str] = [f"SELF CHECK ({self.mode}) {stamp}", ""]

        # Group by status in-place order for readability.
        for r in self.results:
            dur = f"{r.duration_ms:.0f}ms"
            lines.append(f"[{r.status}] {r.id} ({dur}) {r.detail}")

        lines.append("")
        fails = sum(1 for r in self.results if r.status == "FAIL")
        warns = sum(1 for r in self.results if r.status == "WARN")
        skips = sum(1 for r in self.results if r.status == "SKIP")
        lines.append(f"Overall: {self.overall} ({fails} fail, {warns} warn, {skips} skip)")

        remediation: list[str] = []
        for r in self.results:
            if r.status != "FAIL":
                continue
            for s in r.remediation or []:
                if s and s not in remediation:
                    remediation.append(s)
        if remediation:
            lines.append("")
            lines.append("What to do next:")
            for s in remediation[:12]:
                lines.append(f"- {s}")

        return "\n".join(lines).strip()


def _coerce_mode(raw: Any) -> SelfCheckMode:
    m = str(raw or "").strip().lower()
    return "full" if m == "full" else "quick"


def _probe_should_run(mode: SelfCheckMode, minimum: SelfCheckMode) -> bool:
    if minimum == "quick":
        return True
    return mode == "full"


def _best_effort_version() -> str:
    try:
        import sol

        return str(getattr(sol, "__version__", "") or "") or "<unknown>"
    except Exception:
        return "<unknown>"


def _is_policy_block(err: str) -> bool:
    low = (err or "").lower()
    return any(
        k in low
        for k in (
            "host not in allowlist",
            "blocked by policy",
            "web policy",
            "web access disabled",
            "resolved ip not allowed",
            "redirect blocked",
        )
    )


def _is_truncationish(err: str) -> bool:
    low = (err or "").lower()
    return any(
        k in low
        for k in (
            "unterminated string",
            "json truncated",
            "max_bytes",
            "response was truncated",
            "truncated",
        )
    )


def _invoke_tool(ctx, *, tool_name: str, tool_args: dict[str, Any], reason: str) -> Any:
    agent = getattr(ctx, "agent", None)
    if agent is not None and hasattr(agent, "run_tool"):
        res = agent.run_tool(tool_name=tool_name, tool_args=tool_args, reason=reason)
        if not bool(getattr(res, "ok", False)):
            last = res.tool_results[-1] if getattr(res, "tool_results", None) else None
            err = getattr(last, "error", None) if last is not None else None
            raise RuntimeError(err or "tool failed")
        last = res.tool_results[-1] if getattr(res, "tool_results", None) else None
        return getattr(last, "output", None) if last is not None else None

    reg = getattr(ctx, "tool_registry", None)
    if reg is None:
        from sol.tools.registry import build_default_registry

        reg = build_default_registry()
    tool, validated = reg.prepare_for_execution(tool_name, tool_args, reason=reason)
    return tool.run(ctx, validated)


def run_selfcheck(
    *,
    ctx,
    mode: SelfCheckMode,
    fix: bool,
    exercise_cli_tool_wrappers: bool = False,
    invoke_tool: Callable[..., Any] | None = None,
) -> SelfCheckReport:
    invoker = invoke_tool or (lambda **kwargs: _invoke_tool(ctx, **kwargs))
    started_ts = time.time()

    root = Path(getattr(ctx.cfg, "root_dir", Path.cwd()))
    data_dir = Path(getattr(ctx.cfg.paths, "data_dir", root / "data"))
    selfcheck_dir = (data_dir / "selfcheck").resolve()

    if fix:
        try:
            selfcheck_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Safe: if this fails, probes will surface it as failures later.
            pass

    # Use only files under data/selfcheck for write/move/delete probes.
    note_a = selfcheck_dir / "note.txt"
    note_b = selfcheck_dir / "note-renamed.txt"

    def diff_path(p: Path) -> str:
        try:
            return p.relative_to(root).as_posix()
        except Exception:
            return p.as_posix()

    wiki_url = "https://en.wikipedia.org/wiki/Lua_(programming_language)"
    gh_repo = "https://github.com/atlas-kit/atlas"
    gh_folder = "https://github.com/atlas-kit/atlas/tree/dev/data/actions/scripts"
    gh_rate_limit_url = "https://api.github.com/rate_limit"

    results: list[ProbeResult] = []

    def add_result(
        *,
        probe_id: str,
        status: SelfCheckStatus,
        duration_ms: float,
        detail: str,
        remediation: list[str] | None = None,
    ) -> None:
        results.append(
            ProbeResult(
                id=probe_id,
                status=status,
                duration_ms=duration_ms,
                detail=detail,
                remediation=list(remediation or []),
            )
        )

    def run_tool_probe(
        *,
        probe_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        minimum: SelfCheckMode = "quick",
        remediation: list[str] | None = None,
        warn_on_policy_block: bool = True,
        error_to_status: Callable[[str], SelfCheckStatus] | None = None,
    ) -> None:
        if not _probe_should_run(mode, minimum):
            add_result(
                probe_id=probe_id,
                status="SKIP",
                duration_ms=0.0,
                detail=f"mode={mode} (minimum={minimum})",
                remediation=[],
            )
            return

        t0 = time.perf_counter()
        try:
            out = invoker(tool_name=tool_name, tool_args=tool_args, reason=f"SelfCheck: {probe_id}")
            t1 = time.perf_counter()
            detail = "ok"
            try:
                if isinstance(out, dict):
                    if "ok" in out and out.get("ok") is False:
                        detail = "returned ok=false"
                    elif "success" in out:
                        detail = f"success={out.get('success')}"
                    elif "count" in out:
                        detail = f"count={out.get('count')}"
                    elif "entries" in out and isinstance(out.get("entries"), list):
                        detail = f"entries={len(out.get('entries') or [])}"
                    elif "hits" in out and isinstance(out.get("hits"), list):
                        detail = f"hits={len(out.get('hits') or [])}"
                    elif "pages_ok" in out:
                        detail = f"pages_ok={out.get('pages_ok')} pages_failed={out.get('pages_failed')}"
            except Exception:
                pass
            add_result(probe_id=probe_id, status="PASS", duration_ms=(t1 - t0) * 1000.0, detail=detail, remediation=[])
        except Exception as e:
            t1 = time.perf_counter()
            msg = str(e) or e.__class__.__name__
            status: SelfCheckStatus = "FAIL"
            if error_to_status is not None:
                try:
                    status = error_to_status(msg)
                except Exception:
                    status = "FAIL"
            elif warn_on_policy_block and (_is_policy_block(msg) or (probe_id == "repo.tree" and _is_truncationish(msg))):
                status = "WARN"
            add_result(
                probe_id=probe_id,
                status=status,
                duration_ms=(t1 - t0) * 1000.0,
                detail=msg,
                remediation=remediation or [],
            )

    # -------- Filesystem tools --------
    run_tool_probe(
        probe_id="fs.list",
        tool_name="fs.list",
        tool_args={"path": str(root), "recursive": False, "max_entries": 10},
        remediation=[
            "Check [fs].allowed_roots in config/sol.toml includes this repo path.",
            "Run: python -m sol tool fs.list --reason SelfCheck --json '{\"path\":\".\",\"max_entries\":10}'",
        ],
    )
    run_tool_probe(
        probe_id="fs.read_text",
        tool_name="fs.read_text",
        tool_args={"path": str(root / "README.md")},
        remediation=["Ensure SolVersion2/README.md exists and is under an allowed fs root."],
    )
    run_tool_probe(
        probe_id="fs.grep",
        tool_name="fs.grep",
        tool_args={"query": "web.ingest_url", "path": str(root), "glob": "*.py", "max_hits": 5},
        remediation=["If this fails, check fs policy and that ripgrep-like scanning isn't blocked by size limits."],
    )
    run_tool_probe(
        probe_id="fs.write_text",
        tool_name="fs.write_text",
        tool_args={"path": str(note_a), "content": "alpha\n", "reason": "SelfCheck sandbox write"},
        remediation=[
            "Ensure SolVersion2/data is writable and under an allowed fs root.",
            "Check [fs].max_write_bytes in config/sol.toml.",
        ],
    )
    run_tool_probe(
        probe_id="fs.move",
        tool_name="fs.move",
        tool_args={"src": str(note_a), "dst": str(note_b), "overwrite": True, "reason": "SelfCheck sandbox move"},
        remediation=["Ensure the selfcheck sandbox file exists and is writable."],
    )
    run_tool_probe(
        probe_id="patch_preview",
        tool_name="patch_preview",
        tool_args={
            "patch_text": "\n".join(
                [
                    f"diff --git a/{diff_path(note_b)} b/{diff_path(note_b)}",
                    f"--- a/{diff_path(note_b)}",
                    f"+++ b/{diff_path(note_b)}",
                    "@@ -1 +1 @@",
                    "-alpha",
                    "+beta",
                    "",
                ]
            )
        },
        remediation=[
            "Ensure fs.write_text/fs.move succeeded; patch_preview targets the selfcheck sandbox file.",
        ],
    )
    # Safety: patch_apply is destructive by design. Only run it with an explicit allow-destructive flag.
    add_result(
        probe_id="patch_apply",
        status="SKIP",
        duration_ms=0.0,
        detail="Destructive; requires explicit allow-destructive (not enabled by SelfCheck).",
        remediation=[],
    )
    run_tool_probe(
        probe_id="fs.delete",
        tool_name="fs.delete",
        tool_args={"paths": [str(note_b)], "reason": "SelfCheck sandbox cleanup"},
        remediation=["If cleanup failed, delete SolVersion2/data/selfcheck/* manually."],
    )

    # -------- RAG tools --------
    token = f"selfcheck-{int(time.time())}"
    run_tool_probe(
        probe_id="rag.upsert_text",
        tool_name="rag.upsert_text",
        tool_args={"doc_id": f"selfcheck:{token}", "title": "SelfCheck note", "source": "selfcheck", "text": f"token={token}", "source_type": "note", "trusted": True},
        remediation=["Enable [rag].enabled=true in config/sol.toml."],
    )
    run_tool_probe(
        probe_id="rag.query",
        tool_name="rag.query",
        tool_args={"query": token, "k": 3},
        remediation=["If this returns no hits, check the RAG DB path and that writes are permitted."],
    )
    run_tool_probe(
        probe_id="rag.ingest_path",
        tool_name="rag.ingest_path",
        tool_args={"path": str(root / "README.md"), "recursive": False, "max_files": 1},
        remediation=["If blocked, check fs policy allowed_roots and [rag].enabled."],
    )

    # -------- Web tools --------
    run_tool_probe(
        probe_id="web.search",
        tool_name="web.search",
        tool_args={"query": "Lua programming language site:wikipedia.org", "providers": [], "k_per_provider": 3, "max_total_results": 3, "timeout_s": 5.0, "prefer_primary": False},
        remediation=["If blocked, update [web] provider allowlist and [web.search] config in config/sol.toml."],
        warn_on_policy_block=True,
    )
    run_tool_probe(
        probe_id="web.fetch",
        tool_name="web.fetch",
        tool_args={"url": wiki_url, "store": False, "reason": "SelfCheck web.fetch"},
        remediation=["If blocked, allowlist wikipedia.org in [web.policy] in config/sol.toml (deny wins)."],
        warn_on_policy_block=True,
    )
    run_tool_probe(
        probe_id="web.crawl",
        tool_name="web.crawl",
        tool_args={
            "start_url": wiki_url,
            # web.crawl has an additional "crawl-scope" allowlist separate from web.policy.
            # Keep this tight (same domain) so the probe passes in common configs without loosening policy.
            "allowed_domains": ["wikipedia.org"],
            "max_pages": 3,
            "max_depth": 1,
            "delay_ms": 0,
            "reason": "SelfCheck web.crawl",
        },
        minimum="full",
        remediation=["If blocked, allowlist wikipedia.org in [web.policy] in config/sol.toml (deny wins)."],
        warn_on_policy_block=True,
    )
    run_tool_probe(
        probe_id="web.ingest_url",
        tool_name="web.ingest_url",
        tool_args={"start_url": gh_folder, "mode": "repo", "max_pages": 3, "max_depth": 1, "delay_ms": 0, "respect_robots": False, "include_globs": ["**/*.lua", "**/*.xml"], "exclude_globs": []},
        remediation=[
            "If blocked, allowlist github.com, api.github.com, and raw.githubusercontent.com in [web.policy].",
            "If GitHub trees are too large, verify Contents BFS fallback is enabled (manifest repo.listing_method=contents_bfs).",
        ],
        warn_on_policy_block=True,
    )
    run_tool_probe(
        probe_id="web.ingest_crawl",
        tool_name="web.ingest_crawl",
        tool_args={"start_url": wiki_url, "max_pages": 3, "max_depth": 1, "delay_ms": 0, "reason": "SelfCheck web.ingest_crawl"},
        minimum="full",
        remediation=["If blocked, allowlist wikipedia.org in [web.policy] in config/sol.toml (deny wins)."],
        warn_on_policy_block=True,
    )

    # -------- Tibia forum helpers --------
    run_tool_probe(
        probe_id="tibia.search_sources",
        tool_name="tibia.search_sources",
        tool_args={"query": "TFS monster race system", "k": 3, "reason": "SelfCheck tibia.search_sources"},
        remediation=[
            "If blocked, ensure web.search providers are reachable (web.allow_all_hosts / web.allowed_host_suffixes) and web.enabled=true.",
            "If disabled, enable [tibia.sources] in config/sol.toml.",
        ],
        warn_on_policy_block=True,
    )
    # Avoid hitting real forums in SelfCheck by default; these are bounded but still external + content-variable.
    add_result(
        probe_id="tibia.ingest_thread",
        status="SKIP",
        duration_ms=0.0,
        detail="Skipped by default (external forum). Run manually with a specific thread URL if desired.",
        remediation=[
            "Manual example: /tool tibia.ingest_thread {\"start_url\":\"https://otland.net/threads/<slug>.<id>/\",\"max_pages\":2,\"delay_ms\":500,\"reason\":\"manual tibia thread ingest\"}",
            "Ensure the forum domain is allowed in [web.policy] and robots.txt is respected.",
        ],
    )
    add_result(
        probe_id="tibia.learn",
        status="SKIP",
        duration_ms=0.0,
        detail="Skipped by default (external forums). Run manually when you want forum research.",
        remediation=[
            "Manual example: /tool tibia.learn {\"query\":\"TFS monster race system\",\"max_threads\":2,\"max_pages_per_thread\":2,\"delay_ms\":500,\"reason\":\"manual tibia research\"}",
        ],
    )

    # -------- Repo tools --------
    def run_repo_tree_probe(*, probe_id: str, tool_args: dict[str, Any], minimum: SelfCheckMode = "quick") -> dict[str, Any] | None:
        if not _probe_should_run(mode, minimum):
            add_result(probe_id=probe_id, status="SKIP", duration_ms=0.0, detail=f"mode={mode} (minimum={minimum})", remediation=[])
            return None

        t0 = time.perf_counter()
        try:
            out = invoker(tool_name="repo.tree", tool_args=tool_args, reason=f"SelfCheck: {probe_id}")
            t1 = time.perf_counter()

            if not isinstance(out, dict):
                add_result(
                    probe_id=probe_id,
                    status="FAIL",
                    duration_ms=(t1 - t0) * 1000.0,
                    detail=f"Unexpected output type: {type(out).__name__}",
                    remediation=["Inspect repo.tree tool output shape in sol/tools/repo.py."],
                )
                return None

            count = None
            try:
                count = int(out.get("count")) if out.get("count") is not None else None
            except Exception:
                count = None
            if count is None:
                entries = out.get("entries")
                files = out.get("files")
                if isinstance(entries, list):
                    count = len(entries)
                elif isinstance(files, list):
                    count = len(files)
                else:
                    count = 0

            err = str(out.get("error") or "").strip().lower()
            partial = bool(out.get("partial") or False)
            method = str(out.get("method") or "")
            next_cursor = out.get("next_cursor")
            rate_limited = bool(out.get("rate_limited") or False)
            token_present = bool(out.get("github_token_present") or False)
            token_env_cfg = bool(out.get("github_token_configured") or False)

            # SelfCheck policy:
            # - PASS if it got >0 entries (even partial)
            # - WARN only if it got 0 entries due to max_bytes (truncation)
            # - WARN if rate-limited and no token is present
            # - FAIL if rate-limited even with a token present
            status: SelfCheckStatus
            if count > 0:
                status = "PASS"
            elif err == "max_bytes":
                status = "WARN"
            elif rate_limited and token_present:
                status = "FAIL"
            elif rate_limited and not token_present:
                status = "WARN"
            else:
                status = "PASS"

            detail = f"entries={count} method={method or '<unknown>'} partial={partial}"
            if isinstance(next_cursor, str) and next_cursor.strip():
                detail += " next_cursor=yes"
            if rate_limited:
                detail += " rate_limited=yes"
                if token_present:
                    detail += " token=present"
                else:
                    detail += " token=absent"

            remediation: list[str] = []
            if status == "WARN":
                remediation = [
                    "GitHub listing hit max_bytes; retry with smaller scope or use web.ingest_url (Contents BFS).",
                    "Ensure api.github.com is allowed in [web.policy].",
                ]
                if rate_limited:
                    remediation = [
                        "GitHub API rate limit exceeded for unauthenticated requests.",
                        "Configure a GitHub token via [web.github].token_env and set that env var (do not store tokens in config).",
                        "Example: set env var SOL_GITHUB_TOKEN and set web.github.token_env = \"SOL_GITHUB_TOKEN\".",
                    ]
            if status == "FAIL" and rate_limited:
                remediation = [
                    "GitHub API rate limit exceeded even with a token present.",
                    "Verify the token is valid and has not hit its own rate limit.",
                    "Verify SolVersion2/config/sol.toml has [web.github].token_env set and the env var is visible to the Sol process.",
                ]

            add_result(probe_id=probe_id, status=status, duration_ms=(t1 - t0) * 1000.0, detail=detail, remediation=remediation)
            return out
        except Exception as e:
            t1 = time.perf_counter()
            msg = str(e) or e.__class__.__name__
            status: SelfCheckStatus = "WARN" if _is_policy_block(msg) else "FAIL"
            add_result(
                probe_id=probe_id,
                status=status,
                duration_ms=(t1 - t0) * 1000.0,
                detail=msg,
                remediation=[
                    "If blocked, allowlist github.com/api.github.com in [web.policy].",
                    "If this is an auth/rate-limit issue, provide a GitHub token via your configured mechanism (if supported).",
                ]
                if status != "PASS"
                else [],
            )
            return None

    # Quick: non-recursive directory listing (bounded).
    recursive_flag = True if mode == "full" else False
    repo_tree_max_entries = 25 if mode == "full" else 100
    repo_tree_out = run_repo_tree_probe(
        probe_id="repo.tree",
        tool_args={
            "repo_url": gh_repo,
            "branch": "dev",
            "path": "data/actions/scripts",
            "max_entries": repo_tree_max_entries,
            "recursive": recursive_flag,
        },
        minimum="quick",
    )

    # Full: pagination probe (page 2) using the cursor from page 1.
    if mode == "full":
        # Optional token wiring check: if a token is present, query /rate_limit and surface remaining quota.
        token_env = str(getattr(ctx.cfg.web, "github_token_env", "") or "").strip()
        token_present = bool((os.environ.get(token_env) or "").strip()) if token_env else False
        if token_present:
            t0 = time.perf_counter()
            try:
                out = invoker(tool_name="web.fetch", tool_args={"url": gh_rate_limit_url, "store": False}, reason="SelfCheck: github.rate_limit")
                t1 = time.perf_counter()
                remaining = None
                try:
                    text = str(out.get("text") or "") if isinstance(out, dict) else ""
                    data = json.loads(text) if text.strip().startswith("{") else {}
                    remaining = ((data.get("resources") or {}).get("core") or {}).get("remaining")
                except Exception:
                    remaining = None
                add_result(
                    probe_id="github.rate_limit",
                    status="PASS",
                    duration_ms=(t1 - t0) * 1000.0,
                    detail=f"remaining={remaining}" if remaining is not None else "ok",
                    remediation=[],
                )
            except Exception as e:
                t1 = time.perf_counter()
                add_result(
                    probe_id="github.rate_limit",
                    status="WARN",
                    duration_ms=(t1 - t0) * 1000.0,
                    detail=str(e) or e.__class__.__name__,
                    remediation=["If this is blocked, allowlist api.github.com in [web.policy]."],
                )

        next_cur = repo_tree_out.get("next_cursor") if isinstance(repo_tree_out, dict) else None
        if isinstance(next_cur, str) and next_cur.strip():
            _ = run_repo_tree_probe(
                probe_id="repo.tree.page2",
                tool_args={
                    "repo_url": gh_repo,
                    "branch": "dev",
                    "path": "data/actions/scripts",
                    "max_entries": repo_tree_max_entries,
                    "recursive": True,
                    "cursor": next_cur,
                },
                minimum="full",
            )
        else:
            add_result(
                probe_id="repo.tree.page2",
                status="SKIP",
                duration_ms=0.0,
                detail="No next_cursor returned from page 1",
                remediation=[],
            )
    run_tool_probe(
        probe_id="repo.fetch_file",
        tool_name="repo.fetch_file",
        tool_args={"repo_url": gh_repo, "branch": "dev", "path": "README.md", "reason": "SelfCheck repo.fetch_file"},
        remediation=[
            "If blocked, allowlist raw.githubusercontent.com (and github.com/api.github.com) in [web.policy].",
        ],
        warn_on_policy_block=True,
    )
    run_tool_probe(
        probe_id="repo.ingest",
        tool_name="repo.ingest",
        tool_args={"repo_url": gh_repo, "branch": "dev", "path": "data/actions/scripts", "file_pattern": "*.xml", "collection": "selfcheck.xml", "source": "selfcheck", "write_manifest": True, "reason": "SelfCheck repo.ingest"},
        minimum="full",
        remediation=[
            "If GitHub Trees API is too large, confirm repo.ingest returns partial results and uses contents_bfs fallback.",
            "Ensure raw.githubusercontent.com is allowed in [web.policy].",
        ],
        warn_on_policy_block=True,
    )

    # -------- Domain tools --------
    run_tool_probe(
        probe_id="monster.generate",
        tool_name="monster.generate",
        tool_args={"base_race": "undead", "difficulty": "mid", "style": "melee", "inspiration": ["selfcheck"], "examples": [], "reason": "SelfCheck monster.generate"},
        remediation=["If this fails, inspect sol/tools/monster.py and its schema."],
    )

    # -------- Status tools --------
    run_tool_probe(probe_id="voice.status", tool_name="voice.status", tool_args={}, remediation=[])
    run_tool_probe(probe_id="vision.status", tool_name="vision.status", tool_args={}, remediation=[])

    # -------- HermesBK dev tools --------
    run_tool_probe(
        probe_id="run_py_compile",
        tool_name="run_py_compile",
        tool_args={"paths": [str(root / "sol")], "max_files": 3000},
        remediation=["If syntax errors are reported, fix the indicated file/line."],
    )
    run_tool_probe(
        probe_id="run_pytest",
        tool_name="run_pytest",
        tool_args={"args": "-q", "cwd": str(root)},
        minimum="full",
        remediation=["Run `python -m pytest -q` in SolVersion2 and inspect failures."],
    )

    # -------- CLI verification via exec.run --------
    run_tool_probe(
        probe_id="exec.run",
        tool_name="exec.run",
        tool_args={"cmd": "python -c \"print('OK')\"", "cwd": str(root), "reason": "SelfCheck exec.run"},
        remediation=["Enable [exec].enabled=true and ensure python is in [exec].allowed_commands."],
    )
    run_tool_probe(
        probe_id="cli.sol_run_import",
        tool_name="exec.run",
        tool_args={"cmd": "python -c \"import sol.cli.run; print('OK')\"", "cwd": str(root), "reason": "SelfCheck verify sol run import"},
        remediation=["Ensure SolVersion2 is importable (run from its root, or fix PYTHONPATH)."],
    )
    run_tool_probe(
        probe_id="cli.sol_memory_stats",
        tool_name="exec.run",
        tool_args={"cmd": "python -m sol memory stats --reason SelfCheck", "cwd": str(root), "reason": "SelfCheck memory stats CLI"},
        remediation=["If this fails, check [memory].enabled=true and writable data paths."],
    )
    if mode == "full":
        # Safe: dry-run only (no writes/deletes).
        t0 = time.perf_counter()
        try:
            res = invoker(
                tool_name="exec.run",
                tool_args={
                    "cmd": "python -m sol memory prune --older-than-days 30 --dry-run --reason SelfCheck",
                    "cwd": str(root),
                    "reason": "SelfCheck memory prune dry-run",
                },
                reason="SelfCheck: cli.sol_memory_prune",
            )
            t1 = time.perf_counter()
            rc = int(res.get("returncode") or 0) if isinstance(res, dict) else 0
            if rc != 0:
                stderr = str(res.get("stderr") or "") if isinstance(res, dict) else ""
                add_result(
                    probe_id="cli.sol_memory_prune",
                    status="FAIL",
                    duration_ms=(t1 - t0) * 1000.0,
                    detail=f"dry_run_failed rc={rc} stderr={stderr[-200:].strip()}",
                    remediation=["Run manually: python -m sol memory prune --older-than-days 30 --dry-run --reason SelfCheck"],
                )
            else:
                add_result(
                    probe_id="cli.sol_memory_prune",
                    status="PASS",
                    duration_ms=(t1 - t0) * 1000.0,
                    detail="dry_run_ok",
                    remediation=[],
                )
        except Exception as e:
            t1 = time.perf_counter()
            add_result(
                probe_id="cli.sol_memory_prune",
                status="FAIL",
                duration_ms=(t1 - t0) * 1000.0,
                detail=str(e) or e.__class__.__name__,
                remediation=["Ensure `python -m sol memory prune --dry-run` is supported and exec.run is enabled."],
            )
    else:
        add_result(
            probe_id="cli.sol_memory_prune",
            status="SKIP",
            duration_ms=0.0,
            detail="quick mode: skipping memory prune (even dry-run) to keep SelfCheck fast.",
            remediation=[],
        )
    run_tool_probe(
        probe_id="cli.sol_ingest",
        tool_name="exec.run",
        tool_args={
            "cmd": f"python -m sol ingest --path \"{(root / 'README.md').as_posix()}\" --reason SelfCheck --tags selfcheck --max_files 1",
            "cwd": str(root),
            "reason": "SelfCheck sol ingest CLI",
        },
        remediation=["If blocked, check fs policy allowed_roots and memory.enabled."],
    )
    if mode == "full" and exercise_cli_tool_wrappers:
        t0 = time.perf_counter()
        try:
            payload = json.dumps(
                {
                    "start_url": wiki_url,
                    "mode": "single",
                    "max_pages": 1,
                    "max_depth": 0,
                    "delay_ms": 0,
                    "respect_robots": False,
                },
                ensure_ascii=False,
            )
            payload_escaped = payload.replace('"', '\\"')
            res = invoker(
                tool_name="exec.run",
                tool_args={
                    "cmd": f"python -m sol tool web.ingest_url --reason \"SelfCheck CLI wrapper\" --json \"{payload_escaped}\"",
                    "cwd": str(root),
                    "reason": "SelfCheck sol tool wrapper",
                },
                reason="SelfCheck: cli.sol_tool_web_ingest_url",
            )
            t1 = time.perf_counter()
            rc = int(res.get("returncode") or 0) if isinstance(res, dict) else 0
            if rc != 0:
                stderr = str(res.get("stderr") or "") if isinstance(res, dict) else ""
                add_result(
                    probe_id="cli.sol_tool_web_ingest_url",
                    status="FAIL",
                    duration_ms=(t1 - t0) * 1000.0,
                    detail=f"build_failed returncode={rc} stderr={stderr[-200:].strip()}",
                    remediation=["Run manually: python -m sol tool web.ingest_url --reason SelfCheck --json '{...}'"],
                )
            else:
                add_result(
                    probe_id="cli.sol_tool_web_ingest_url",
                    status="PASS",
                    duration_ms=(t1 - t0) * 1000.0,
                    detail="ok",
                    remediation=[],
                )
        except Exception as e:
            t1 = time.perf_counter()
            add_result(
                probe_id="cli.sol_tool_web_ingest_url",
                status="FAIL",
                duration_ms=(t1 - t0) * 1000.0,
                detail=str(e) or e.__class__.__name__,
                remediation=["Ensure `python -m sol tool ...` works from SolVersion2 root."],
            )
    else:
        add_result(
            probe_id="cli.sol_tool_web_ingest_url",
            status="SKIP",
            duration_ms=0.0,
            detail="Covered via direct web.ingest_url probe; add --exercise-cli-tool-wrappers to run CLI wrappers.",
            remediation=[],
        )
    run_tool_probe(
        probe_id="cli.pytest",
        tool_name="exec.run",
        tool_args={"cmd": "python -m pytest -q", "cwd": str(root), "reason": "SelfCheck pytest CLI"},
        minimum="full",
        remediation=["If this times out, increase [exec].timeout_s in config/sol.toml or run pytest manually."],
    )
    def npm_build_probe(*, probe_id: str, project_dir: Path | None) -> None:
        if not _probe_should_run(mode, "full"):
            add_result(probe_id=probe_id, status="SKIP", duration_ms=0.0, detail=f"mode={mode} (minimum=full)", remediation=[])
            return

        if project_dir is None:
            add_result(
                probe_id=probe_id,
                status="SKIP",
                duration_ms=0.0,
                detail="not_configured: set [paths].solweb_dir / [paths].desktop_dir in config/sol.toml",
                remediation=[
                    'Example: [paths] solweb_dir="F:/openai/SolWeb" desktop_dir="F:/openai/apps/desktop"',
                ],
            )
            return
        if not project_dir.exists() or not project_dir.is_dir():
            add_result(
                probe_id=probe_id,
                status="SKIP",
                duration_ms=0.0,
                detail=f"not_configured: path does not exist: {project_dir}",
                remediation=["Fix the configured path in [paths] in config/sol.toml."],
            )
            return
        pkg = project_dir / "package.json"
        if not pkg.exists():
            add_result(
                probe_id=probe_id,
                status="SKIP",
                duration_ms=0.0,
                detail=f"not_configured: missing package.json in {project_dir}",
                remediation=["Ensure the directory points at the project root containing package.json."],
            )
            return

        # npm -v preflight
        t0 = time.perf_counter()
        npm_ok = False
        npm_detail = ""
        tried = ["npm -v"]
        try:
            res_v = invoker(
                tool_name="exec.run",
                tool_args={"cmd": "npm -v", "cwd": str(project_dir), "reason": f"SelfCheck {probe_id} npm -v"},
                reason=f"SelfCheck: {probe_id}",
            )
            rc = int(res_v.get("returncode") or 0) if isinstance(res_v, dict) else 0
            if rc == 0:
                npm_ok = True
            else:
                npm_detail = f"npm -v rc={rc} stderr={str(res_v.get('stderr') or '')[-200:].strip()}"
        except Exception as e:
            npm_detail = str(e) or e.__class__.__name__

        # Windows fallback: try npm.cmd explicitly (narrowly allowed by executor).
        if not npm_ok and os.name == "nt":
            tried.append("npm.cmd -v")
            try:
                res_v2 = invoker(
                    tool_name="exec.run",
                    tool_args={"cmd": "npm.cmd -v", "cwd": str(project_dir), "reason": f"SelfCheck {probe_id} npm.cmd -v"},
                    reason=f"SelfCheck: {probe_id}",
                )
                rc2 = int(res_v2.get("returncode") or 0) if isinstance(res_v2, dict) else 0
                if rc2 == 0:
                    npm_ok = True
                else:
                    npm_detail = f"npm.cmd -v rc={rc2} stderr={str(res_v2.get('stderr') or '')[-200:].strip()}"
            except Exception as e:
                npm_detail = str(e) or e.__class__.__name__

        if not npm_ok:
            t1 = time.perf_counter()
            path_head = [p for p in (os.environ.get("PATH") or "").split(os.pathsep) if p.strip()][:3]
            add_result(
                probe_id=probe_id,
                status="SKIP",
                duration_ms=(t1 - t0) * 1000.0,
                detail=f"missing_dependency: npm unavailable (tried={','.join(tried)}) (python={sys.executable}, path_head={path_head}) ({npm_detail})",
                remediation=["Install Node.js/npm and ensure `npm` is on PATH for the shell Sol uses."],
            )
            return

        # npm run build
        try:
            res_b = invoker(
                tool_name="exec.run",
                tool_args={"cmd": "npm run build", "cwd": str(project_dir), "reason": f"SelfCheck {probe_id} npm run build"},
                reason=f"SelfCheck: {probe_id}",
            )
            t1 = time.perf_counter()
            rc = int(res_b.get("returncode") or 0) if isinstance(res_b, dict) else 0
            if rc != 0:
                stderr = str(res_b.get("stderr") or "") if isinstance(res_b, dict) else ""
                add_result(
                    probe_id=probe_id,
                    status="FAIL",
                    duration_ms=(t1 - t0) * 1000.0,
                    detail=f"build_failed: returncode={rc} stderr={stderr[-200:].strip()}",
                    remediation=[f"Run manually: cd {project_dir} && npm run build"],
                )
                return
            add_result(probe_id=probe_id, status="PASS", duration_ms=(t1 - t0) * 1000.0, detail="ok", remediation=[])
        except Exception as e:
            t1 = time.perf_counter()
            msg = str(e) or e.__class__.__name__
            add_result(
                probe_id=probe_id,
                status="FAIL",
                duration_ms=(t1 - t0) * 1000.0,
                detail=f"build_failed: {msg}",
                remediation=[f"Run manually: cd {project_dir} && npm run build"],
            )

    npm_build_probe(probe_id="cli.solweb_build", project_dir=getattr(ctx.cfg.paths, "solweb_dir", None))
    npm_build_probe(probe_id="cli.desktop_build", project_dir=getattr(ctx.cfg.paths, "desktop_dir", None))

    # Overall status: FAIL if any fails, else WARN if any warns, else PASS.
    overall: SelfCheckStatus = "PASS"
    if any(r.status == "FAIL" for r in results):
        overall = "FAIL"
    elif any(r.status == "WARN" for r in results):
        overall = "WARN"

    return SelfCheckReport(ts=started_ts, mode=mode, version=_best_effort_version(), overall=overall, results=results)


class SelfCheckRunTool(Tool):
    name = "selfcheck.run"
    description = "Run an end-to-end diagnostic suite (tools + CLI checks) and return a report."
    args = (
        ToolArgument("mode", str, "SelfCheck mode: quick|full", required=False, default="quick"),
        ToolArgument("json", bool, "Return structured JSON report (default: false)", required=False, default=False),
        ToolArgument("fix", bool, "Apply safe auto-fixes only (default: false)", required=False, default=False),
        ToolArgument("exercise_cli_tool_wrappers", bool, "Also exercise `python -m sol tool ...` CLI wrappers (slower)", required=False, default=False),
    )
    safety_flags = ("filesystem", "network", "exec", "rag")
    requires_confirmation = False

    def run(self, ctx, args: dict[str, Any]) -> Any:
        mode = _coerce_mode(args.get("mode"))
        want_json = bool(args.get("json") or False)
        fix = bool(args.get("fix") or False)
        exercise_cli = bool(args.get("exercise_cli_tool_wrappers") or False)

        # SelfCheck runs sandboxed destructive probes (fs.move/fs.delete/exec.run) by design.
        # Keep SelfCheck behavior unchanged by explicitly enabling UNSAFE mode for its thread context
        # and disabling it afterwards (both actions are audited to disk).
        from sol.core.unsafe_mode import disable as unsafe_disable
        from sol.core.unsafe_mode import enable as unsafe_enable
        from sol.core.unsafe_mode import reset_request_context, set_request_context

        th = (getattr(ctx, "web_session_thread_id", None) or "").strip() or "selfcheck"
        fallback_user = getattr(getattr(ctx, "local_profile", None), "profile_id", None)
        usr = (getattr(ctx, "web_session_user", None) or "").strip() or (str(fallback_user or "").strip() or "local-user")
        prev_th = getattr(ctx, "web_session_thread_id", None)
        prev_usr = getattr(ctx, "web_session_user", None)
        try:
            ctx.web_session_thread_id = th  # type: ignore[attr-defined]
            ctx.web_session_user = usr  # type: ignore[attr-defined]
        except Exception:
            pass
        tokens = set_request_context(thread_id=th, user=usr)
        try:
            unsafe_enable(th, reason="SelfCheck run", user=usr, cfg=ctx.cfg)
        except Exception:
            # If UNSAFE mode cannot be enabled, continue in safe mode and let probes report failures.
            pass

        try:
            report = run_selfcheck(ctx=ctx, mode=mode, fix=fix, exercise_cli_tool_wrappers=exercise_cli)
        except Exception as e:
            # Never raise: SelfCheck must be able to report failures.
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))[-4000:]
            report = SelfCheckReport(
                ts=time.time(),
                mode=mode,
                version=_best_effort_version(),
                overall="FAIL",
                results=[
                    ProbeResult(
                        id="selfcheck.internal",
                        status="FAIL",
                        duration_ms=0.0,
                        detail=str(e) or e.__class__.__name__,
                        remediation=[tb],
                    )
                ],
            )
        finally:
            try:
                unsafe_disable(th, reason="SelfCheck finished", user=usr, cfg=ctx.cfg)
            except Exception:
                pass
            reset_request_context(tokens)
            try:
                ctx.web_session_thread_id = prev_th  # type: ignore[attr-defined]
                ctx.web_session_user = prev_usr  # type: ignore[attr-defined]
            except Exception:
                pass

        if want_json:
            payload = report.to_dict()
            payload["summary"] = report.to_text()
            return payload
        return report.to_text()
