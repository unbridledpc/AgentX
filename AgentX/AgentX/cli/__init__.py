from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from agentx.cli.run import compose_run_prompt, interactive_run, read_stdin_text, read_task_file, run_task_via_api
from agentx.install.bootstrap import read_bootstrap_app_root
from agentx.install import (
    apply_safe_doctor_fixes,
    LocalProfileSelection,
    ensure_installation_ready,
    inspect_runtime,
    load_installation,
    run_doctor,
    save_local_profile,
    show_paths,
    start_installation,
    status_installation,
    restart_installation,
    stop_installation,
    uninstall_installation,
    write_installation,
    write_cli_launcher,
)
from agentx.install.lifecycle import (
    autostart_state_from_services,
    canonical_bootstrap_fallback,
    canonical_user_launcher_path,
    collect_health_report,
    compatibility_user_launcher_path,
    compute_install_paths,
    disable_systemd_units,
    enable_systemd_units,
    install_systemd_units,
    read_service_logs,
    remove_systemd_units,
    serve_api_forever,
    serve_web_forever,
)
from agentx.install.store import default_install_config_path
from agentx.install.wizard import app_root_sanity_error, build_install_config, fatal_bundle_validation_errors, prompt_install_config, render_setup_summary, validate_install_config
from agentx.install.ui import (
    BRAND_NAME,
    bullet_list,
    error as ui_error,
    failure_panel,
    info as ui_info,
    key_value_table,
    next_steps_panel,
    note as ui_note,
    preflight_result,
    run_with_status,
    section,
    success as ui_success,
    summary_panel,
    warn as ui_warn,
)
from agentx.jobs.runner import JobRunner
from agentx.install.models import InstallProfile, ServiceMode
from agentx.runtime.bootstrap import build_runtime_services_from_config


def _service_state_level(state: str) -> str:
    if state in {"started", "already_running", "running", "ready"}:
        return "pass"
    if state in {"disabled", "stopped", "not_running", "stale_pid_removed", "degraded", "port_in_use"}:
        return "warn"
    return "fail"


def _print_doctor_report(result: dict) -> None:
    section("Doctor", subtitle="Inspecting AgentX install, launcher, runtime, and service readiness.")
    key_value_table(
        "Resolved Paths",
        [
            ("App bundle", str(result["paths"]["app_root"])),
            ("Runtime root", str(result["paths"]["runtime_root"])),
            ("Working directory", str(result["paths"]["working_dir"])),
            ("Config path", str(result["paths"]["config_path"])),
            ("Managed runtime", str(result["managed_runtime_path"])),
            ("Managed Python", str(result["managed_python_path"])),
        ],
    )
    section("Checks")
    for item in result.get("checks", []):
        detail_parts = [str(item.get("message", ""))]
        if item.get("path"):
            detail_parts.append(str(item["path"]))
        preflight_result("pass" if bool(item.get("ok")) else "fail", str(item.get("name")), " — ".join(part for part in detail_parts if part))
    if result.get("environment", {}).get("notes"):
        section("Environment Notes")
        bullet_list([str(item) for item in result["environment"]["notes"]], style="warn")
    if result.get("provider", {}).get("provider") == "ollama":
        summary_panel(
            "Model Provider",
            [
                f"Provider: {result['provider']['provider']}",
                f"Ollama endpoint: {result['provider'].get('base_url', 'unknown')}",
            ],
            style="#8A5BFF",
        )
    if result.get("problems"):
        failure_panel("Doctor Found Problems", "AgentX is not fully ready yet.", guidance=[str(item) for item in result["problems"]], log_path=str(result["paths"]["install_log_path"]))
    else:
        next_steps_panel(
            "Doctor Summary",
            ["Managed runtime looks healthy.", "Launcher and config are ready.", "You can start AgentX with `agentx start`."],
        )


def _print_doctor_fix_report(result: dict[str, object]) -> None:
    section("Doctor Findings")
    findings = [str(item) for item in result.get("findings", [])]
    if findings:
        bullet_list(findings, style="warn")
    else:
        bullet_list(["No major problems were detected before fixes ran."], style="pass")

    section("Applied Fixes")
    fixes_applied = [str(item) for item in result.get("fixes_applied", [])]
    if fixes_applied:
        bullet_list(fixes_applied, style="pass")
    else:
        bullet_list(["No safe fixes were necessary."], style="warn")

    failures = [str(item) for item in result.get("fix_failures", [])]
    if failures:
        section("Fix Failures")
        bullet_list(failures, style="error")

    section("Remaining Problems")
    remaining = [str(item) for item in result.get("remaining_problems", [])]
    if remaining:
        bullet_list(remaining, style="warn")
    else:
        bullet_list(["No remaining problems detected."], style="pass")

    section("Final Status")
    bullet_list([str(result.get("final_status", "unknown"))], style="pass" if str(result.get("final_status", "")) == "OK" else "warn")


def _print_start_result(result: dict) -> None:
    section("Startup", subtitle="Bringing AgentX services online.")
    summary_panel("Startup Summary", [f"Profile: {result.get('profile', 'unknown')}"], style="#5B8CFF")
    for name, item in result.get("services", {}).items():
        state = str(item.get("state", "unknown"))
        detail = item.get("detail") or item.get("error") or item.get("url") or ""
        preflight_result(_service_state_level(state), f"{name.upper()}  {state}", str(detail))
        if item.get("log_path"):
            ui_note(f"{name.upper()} log: {item['log_path']}")
        if item.get("service_log_path"):
            ui_note(f"{name.upper()} service log: {item['service_log_path']}")
    failed = [item for item in result.get("services", {}).values() if str(item.get("state")) in {"failed", "missing_runtime", "missing_config", "missing_dependencies", "blocked"}]
    if failed:
        failure_panel(
            "Startup Failed",
            "One or more AgentX services could not start.",
            guidance=[
                "Run `agentx doctor` to inspect the install.",
                "Review the log paths above for the failing service.",
            ],
        )
    else:
        next_steps_panel(
            "Next Steps",
            ["Run `agentx status` to confirm health.", "Open the web UI if it is enabled.", "Use `agentx doctor` if something looks off."],
        )


def _print_stop_result(result: dict[str, object]) -> None:
    section("Shutdown", subtitle="Stopping AgentX services.")
    services = result.get("services", {}) if isinstance(result.get("services"), dict) else result
    for name, item in services.items():
        payload = item if isinstance(item, dict) else {"state": str(item)}
        state = str(payload.get("state", "unknown"))
        detail = payload.get("warning") or payload.get("error") or payload.get("path") or payload.get("pid") or ""
        preflight_result(_service_state_level(state), f"{str(name).upper()}  {state}", str(detail))
    next_steps_panel(
        "Next Useful Commands",
        [
            "agentx start",
            "agentx status",
            "agentx logs api --tail 100",
        ],
    )


def _print_restart_result(result: dict[str, object]) -> None:
    section("Restart", subtitle="Cycling AgentX services.")
    if not bool(result.get("ok")):
        failure_panel(
            "Restart Failed",
            str(result.get("error", "AgentX could not complete the restart sequence.")),
            guidance=["Run `agentx stop` and inspect logs before retrying."],
        )
        _print_stop_result({"services": result.get("stop", {})})
        return
    _print_stop_result({"services": result.get("stop", {})})
    _print_start_result(result.get("start", {}))


def _print_uninstall_result(result: dict[str, object]) -> None:
    section("Uninstall", subtitle="Removing the local AgentX install.")
    summary_panel(
        "Removed or Kept",
        [
            f"Runtime root: {((result.get('runtime_root') or {}).get('state', 'unknown'))}",
            f"App bundle: {((result.get('app_root') or {}).get('state', 'unknown'))}",
            f"Install config: {((result.get('install_config') or {}).get('state', 'unknown'))}",
            f"Bootstrap record: {((result.get('bootstrap_record') or {}).get('state', 'unknown'))}",
        ],
        style="#5B8CFF",
    )
    launchers = result.get("launchers", {}) if isinstance(result.get("launchers"), dict) else {}
    if launchers:
        section("Launchers")
        for name, item in launchers.items():
            payload = item if isinstance(item, dict) else {"state": str(item)}
            preflight_result(_service_state_level(str(payload.get("state", "unknown"))), str(name), str(payload.get("path", "")))
    units = result.get("systemd_units", {}) if isinstance(result.get("systemd_units"), dict) else {}
    if units:
        section("Systemd Units")
        preflight_result(_service_state_level(str(units.get("state", "unknown"))), "systemd-user", ", ".join(units.get("paths", [])) if isinstance(units.get("paths"), list) else str(units.get("paths", "")))
    warnings = [str(item) for item in result.get("warnings", []) if str(item).strip()]
    if warnings:
        section("Warnings")
        bullet_list(warnings, style="warn")
    next_steps_panel(
        "Lifecycle Commands",
        [
            "agentx setup",
            "agentx start",
            "agentx status",
        ],
        notes=["Re-run `install.sh` or `install-agentx.sh` if you want to install AgentX again."],
    )


def _confirm_uninstall(install, *, keep_app_root: bool) -> bool:
    app_behavior = "keep the app bundle checkout" if keep_app_root else "remove the app bundle checkout"
    section("Confirm Uninstall", subtitle="This removes the local AgentX install managed by this launcher.")
    bullet_list(
        [
            f"Runtime root: {install.runtime_root}",
            f"Install config: {default_install_config_path()}",
            f"App bundle: {install.app_root} ({app_behavior})",
            f"Launchers: {canonical_user_launcher_path()} and {compatibility_user_launcher_path()} when they belong to this install",
        ],
        style="warn",
    )
    response = input("Continue uninstall? [y/N]: ").strip().lower()
    return response in {"y", "yes"}


def _print_status_result(result: dict) -> None:
    section("Status", subtitle="Current AgentX runtime and service state.")
    key_value_table(
        "Runtime",
        [
            ("Profile", str(result.get("profile", "unknown"))),
            ("Service mode", str(result.get("service_mode", "unknown"))),
            ("App bundle", str(result.get("app_root", ""))),
            ("Runtime root", str(result.get("runtime_root", ""))),
            ("Working directory", str(result.get("working_dir", ""))),
            ("Managed runtime", str(result.get("managed_runtime_path", ""))),
            ("Runtime Python", str(result.get("runtime_python", ""))),
            ("Install log", str(result.get("install_log_path", ""))),
        ],
    )
    managed = result.get("managed_runtime", {})
    preflight_result("pass" if bool(managed.get("ready")) else "fail", "Managed runtime", f"{managed.get('python_path', '')}")
    section("Services")
    for name, item in result.get("services", {}).items():
        state = str(item.get("state", "unknown"))
        details = f"{item.get('host', '')}:{item.get('port', '')}"
        if item.get("url"):
            details = f"{details} — {item['url']}"
        preflight_result(_service_state_level(state), f"{name.upper()}  {state}", details)
        if item.get("unit_file_path"):
            ui_note(f"{name.upper()} unit file: {item['unit_file_path']}")
        if item.get("log_source"):
            ui_note(f"{name.upper()} logs: {item['log_source']}")
        if item.get("log_path"):
            ui_note(f"{name.upper()} log: {item['log_path']}")


def _print_service_status(result: dict[str, object]) -> None:
    services = result.get("services", {}) if isinstance(result.get("services"), dict) else {}
    section("Service Status", subtitle="Operational summary for AgentX managed services.")
    key_value_table(
        "Install",
        [
            ("Service mode", str(result.get("service_mode", "unknown"))),
            ("Auto-start", autostart_state_from_services(services)),
            ("App bundle", str(result.get("app_root", ""))),
            ("Runtime root", str(result.get("runtime_root", ""))),
            ("Web UI URL", str(result.get("web_url", ""))),
        ],
    )
    section("Services")
    for name in ("api", "web"):
        item = services.get(name, {})
        state = str(item.get("state", "unknown"))
        level = _service_state_level(state if state != "active" else "running")
        enabled = item.get("systemd_enabled", item.get("enabled", "unknown"))
        detail = f"state={state}"
        if enabled not in {"", None}:
            detail += f" enabled={enabled}"
        preflight_result(level, name.upper(), detail)
        if item.get("unit_file_path"):
            ui_note(f"{name.upper()} unit file: {item['unit_file_path']}")
        if item.get("log_source"):
            ui_note(f"{name.upper()} logs: {item['log_source']}")
        if item.get("health_url") and name == "api":
            ui_note(f"API health: {item['health_url']}")
        if item.get("web_url") and name == "web":
            ui_note(f"Web URL: {item['web_url']}")
    next_steps_panel(
        "Next Useful Commands",
        [
            "agentx logs api --tail 100",
            "agentx logs web --tail 100",
            "agentx doctor",
        ],
    )


def _print_service_toggle_summary(title: str, states: dict[str, str], *, note: str) -> None:
    lines = [f"{name}: {state}" for name, state in states.items()]
    summary_panel(title, lines or ["No service units were selected."], style="green")
    ui_note(note)


def _print_logs_header(config, service: str, tail: int, result: dict[str, object]) -> None:
    section("Logs", subtitle="Recent AgentX service output.")
    source = ""
    if result.get("source") == "journalctl":
        source = str(result.get("unit", ""))
        if source:
            source = f"journalctl --user -u {source}"
    elif result.get("path"):
        source = str(result.get("path"))
    elif result.get("source"):
        source = str(result.get("source"))
    summary_panel(
        f"{service.upper()} Logs",
        [
            f"Service: {service}",
            f"Service mode: {config.service_mode.value}",
            f"Source: {source}",
            f"Tail: {tail}",
            f"App bundle: {config.app_root}",
            f"Runtime root: {config.runtime_root}",
        ],
        style="#5B8CFF",
    )
    if result.get("path"):
        print(f"Log path: {result['path']}")


def _print_health_report(result: dict[str, object]) -> None:
    section("AgentX Health Check")
    key_value_table(
        "Health",
        [
            ("API", str((result.get("api") or {}).get("message", "unknown"))),
            ("Web", str((result.get("web") or {}).get("message", "unknown"))),
            ("Services", str((result.get("services") or {}).get("summary", "unknown"))),
            ("Model", str((result.get("model") or {}).get("message", "unknown"))),
            ("Overall", str(result.get("overall", "unknown"))),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentx",
        description="AgentX local-first assistant CLI",
        epilog="Lifecycle commands: agentx start | stop | restart | status | uninstall",
    )
    p.add_argument(
        "--config",
        default="config/agentx.toml",
        help="Path to AgentX runtime TOML config (default: config/agentx.toml)",
    )
    p.add_argument(
        "--install-config",
        default=str(default_install_config_path()),
        help="Path to AgentX install metadata JSON",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run a task through the local AgentX API, or start the interactive CLI with no task")
    run.add_argument("--file", default="", help="Read plain UTF-8 text input from a file")
    run.add_argument("task", nargs=argparse.REMAINDER, help="Task to send to the AgentX API")

    tool = sub.add_parser("tool", help="Run a tool through the agent loop")
    tool.add_argument("name", help="Tool name, e.g. fs.list")
    tool.add_argument("--reason", required=True, help="Human-readable reason for this tool call (required)")
    tool.add_argument("--json", default="", help="Tool args as JSON object string")
    tool.add_argument("tool_args", nargs=argparse.REMAINDER, help="Optional --key value args")

    ingest = sub.add_parser("ingest", help="Ingest local path into RAG (through agent loop)")
    ingest.add_argument("--path", required=True, help="File or directory path to ingest")
    ingest.add_argument("--reason", required=True, help="Reason for ingest (required)")
    ingest.add_argument(
        "--tags",
        action="append",
        default=[],
        help="Tag for this ingest (repeatable), e.g. --tags trusted:localdoc",
    )
    ingest.add_argument("--recursive", action="store_true", help="Recurse directories")
    ingest.add_argument("--max_files", type=int, default=200, help="Max files to ingest")

    mem = sub.add_parser("memory", help="Memory operations (audited)")
    mem_sub = mem.add_subparsers(dest="memory_cmd", required=True)
    mem_stats = mem_sub.add_parser("stats", help="Show memory stats (requires reason)")
    mem_stats.add_argument("--reason", required=True, help="Reason for reading memory stats (required)")

    mem_prune = mem_sub.add_parser("prune", help="Prune old memory events (requires reason)")
    mem_prune.add_argument("--older-than-days", type=int, required=True, help="Prune events older than N days")
    mem_prune.add_argument("--dry-run", action="store_true", help="Do not delete; only report what would be pruned")
    mem_prune.add_argument("--reason", required=True, help="Reason for pruning (required)")

    selfcheck = sub.add_parser("selfcheck", help="Run SelfCheck diagnostics")
    selfcheck.add_argument("--mode", choices=("quick", "full"), default="quick", help="Mode: quick|full (default: quick)")
    selfcheck.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    selfcheck.add_argument("--fix", action="store_true", help="Apply safe auto-fixes only")
    selfcheck.add_argument("--exercise-cli-tool-wrappers", action="store_true", help="Also exercise `python -m agentx tool ...` wrappers (slower)")
    selfcheck.add_argument("--reason", default="SelfCheck", help="Reason for running SelfCheck (default: SelfCheck)")

    jobs = sub.add_parser("job", help="Create and manage supervised autonomous jobs")
    jobs_sub = jobs.add_subparsers(dest="job_cmd", required=True)
    job_create = jobs_sub.add_parser("create", help="Create a new job")
    job_create.add_argument("--goal", required=True, help="Goal for the job")
    job_create.add_argument("--skill", default="", help="Optional skill id")
    job_create.add_argument("--max-steps", type=int, default=10)
    job_create.add_argument("--max-failures", type=int, default=3)
    job_create.add_argument("--max-runtime-s", type=int, default=900)

    job_run = jobs_sub.add_parser("run", help="Run a job until terminal state")
    job_run.add_argument("job_id")

    job_show = jobs_sub.add_parser("show", help="Show job JSON")
    job_show.add_argument("job_id")

    job_cancel = jobs_sub.add_parser("cancel", help="Request cancellation for a job")
    job_cancel.add_argument("job_id")
    job_cancel.add_argument("--reason", default="")

    job_approve = jobs_sub.add_parser("approve", help="Approve or deny the current pending plan for a job")
    job_approve.add_argument("job_id")
    job_approve.add_argument("--deny", action="store_true")
    job_approve.add_argument("--note", default="")

    plugins = sub.add_parser("plugins", help="List or toggle plugins")
    plugins_sub = plugins.add_subparsers(dest="plugins_cmd", required=True)
    plugins_sub.add_parser("list", help="List plugins")
    plugins_enable = plugins_sub.add_parser("enable", help="Enable a plugin")
    plugins_enable.add_argument("plugin_id")
    plugins_disable = plugins_sub.add_parser("disable", help="Disable a plugin")
    plugins_disable.add_argument("plugin_id")

    skills = sub.add_parser("skills", help="List or import skills")
    skills_sub = skills.add_subparsers(dest="skills_cmd", required=True)
    skills_sub.add_parser("list", help="List skills")
    skills_import = skills_sub.add_parser("import-pack", help="Import a local SKILL.md-based skill pack")
    skills_import.add_argument("source_dir")
    skills_import.add_argument("--skill-id", default="")

    setup = sub.add_parser("setup", help="Create or update a product-style AgentX installation")
    setup.add_argument("--non-interactive", action="store_true", help="Use flags/defaults instead of prompts")
    setup.add_argument("--profile", choices=[p.value for p in InstallProfile], default=InstallProfile.STANDARD.value)
    setup.add_argument("--app-root", default="")
    setup.add_argument("--runtime-root", default="")
    setup.add_argument("--working-dir", default="")
    setup.add_argument("--model-provider", default="ollama")
    setup.add_argument("--ollama-base-url", default="")
    setup.add_argument("--api-host", default="127.0.0.1")
    setup.add_argument("--api-port", type=int, default=8420)
    setup.add_argument("--web-host", default="127.0.0.1")
    setup.add_argument("--web-port", type=int, default=5173)
    setup.add_argument("--web-enabled", choices=("true", "false"), default="")
    setup.add_argument("--service-mode", choices=(ServiceMode.NONE.value, ServiceMode.SYSTEMD_USER.value), default=ServiceMode.NONE.value)

    sub.add_parser("start", help="Start installed AgentX services")
    sub.add_parser("stop", help="Stop installed AgentX services")
    sub.add_parser("restart", help="Restart installed AgentX services")
    sub.add_parser("status", help="Show installed AgentX runtime status")
    uninstall = sub.add_parser("uninstall", help="Remove the local AgentX install managed by this launcher")
    uninstall.add_argument("--yes", action="store_true", help="Skip the uninstall confirmation prompt")
    uninstall.add_argument("--keep-app-root", action="store_true", help="Keep the app bundle checkout and remove launcher/runtime state only")
    doctor = sub.add_parser("doctor", help="Run install/runtime diagnostics")
    doctor.add_argument("--fix", action="store_true", help="Apply safe automatic fixes, then re-run diagnostics")
    sub.add_parser("health", help="Run a fast read-only AgentX health check")
    sub.add_parser("paths", help="Show resolved install/runtime paths")
    logs = sub.add_parser("logs", help="Show AgentX service logs")
    logs.add_argument("service", choices=("api", "web"))
    logs.add_argument("--tail", type=int, default=100, help="Number of lines to show")
    service = sub.add_parser("service", help="Manage AgentX systemd-user services")
    service_sub = service.add_subparsers(dest="service_cmd", required=True)
    service_sub.add_parser("install", help="Install systemd-user unit files")
    service_sub.add_parser("uninstall", help="Remove systemd-user unit files")
    service_sub.add_parser("enable", help="Enable AgentX systemd-user services")
    service_sub.add_parser("disable", help="Disable AgentX systemd-user services")
    service_sub.add_parser("status", help="Show systemd-user unit status")
    runtime_cmd = sub.add_parser("runtime", help="Inspect the managed runtime")
    runtime_sub = runtime_cmd.add_subparsers(dest="runtime_cmd", required=True)
    runtime_sub.add_parser("inspect", help="Show managed runtime path, interpreter, and import checks")

    config_cmd = sub.add_parser("config", help="Show generated install/runtime config")
    config_sub = config_cmd.add_subparsers(dest="config_cmd", required=True)
    config_sub.add_parser("show", help="Show install metadata and generated agentx.toml path")

    internal = sub.add_parser("internal", help=argparse.SUPPRESS)
    internal_sub = internal.add_subparsers(dest="internal_cmd", required=True)
    internal_sub.add_parser("serve-api", help=argparse.SUPPRESS)
    internal_sub.add_parser("serve-web", help=argparse.SUPPRESS)

    return p


def _parse_tool_args(json_str: str, rest: list[str]) -> dict:
    if json_str:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            raise ValueError("--json must be a JSON object")
        out = dict(data)
    else:
        out = {}

    # Parse `--key value` style pairs from remaining args.
    i = 0
    while i < len(rest):
        k = rest[i]
        if not k.startswith("--"):
            i += 1
            continue
        key = k[2:]
        val: object = True
        if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
            raw = rest[i + 1]
            low = raw.lower()
            if low in ("true", "false"):
                val = low == "true"
            else:
                try:
                    val = int(raw)
                except Exception:
                    try:
                        val = float(raw)
                    except Exception:
                        if (raw.startswith("{") and raw.endswith("}")) or (raw.startswith("[") and raw.endswith("]")):
                            try:
                                val = json.loads(raw)
                            except Exception:
                                val = raw
                        else:
                            val = raw
            i += 2
        else:
            i += 1
        out[key] = val
    return out


def _confirm(prompt: str) -> bool:
    ans = input(f"{prompt}\nType 'yes' to allow: ").strip().lower()
    return ans == "yes"


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = build_parser().parse_args(argv)
    install_cfg_path = Path(args.install_config).expanduser().resolve()

    if args.cmd == "setup":
        ui_info(f"{BRAND_NAME} setup is preparing your install choices.")
        bootstrap_app_root = read_bootstrap_app_root(bootstrap_python=Path(sys.executable).resolve())
        if args.app_root:
            app_root = Path(args.app_root).expanduser().resolve()
        elif bootstrap_app_root is not None:
            app_root = bootstrap_app_root.expanduser().resolve()
        else:
            fallback_root = Path(__file__).resolve().parents[3]
            sanity_error = app_root_sanity_error(fallback_root)
            if sanity_error:
                failure_panel(
                    "Invalid App Bundle",
                    "AgentX could not determine a valid app bundle root.",
                    guidance=sanity_error.splitlines(),
                )
                return 2
            app_root = fallback_root
        local_profile: LocalProfileSelection | None = LocalProfileSelection(mode="os-fallback")
        if args.non_interactive:
            runtime_root = Path(args.runtime_root).expanduser().resolve() if args.runtime_root else (Path.home() / ".local" / "share" / "agentx")
            working_dir = Path(args.working_dir).expanduser().resolve() if args.working_dir else (Path.home() / "agentx-work")
            web_enabled = None
            if args.web_enabled:
                web_enabled = args.web_enabled == "true"
            config = build_install_config(
                app_root=app_root,
                runtime_root=runtime_root,
                working_dir=working_dir,
                profile=InstallProfile(args.profile),
                model_provider=args.model_provider,
                ollama_base_url=args.ollama_base_url,
                api_host=args.api_host,
                api_port=int(args.api_port),
                web_host=args.web_host,
                web_port=int(args.web_port),
                web_enabled=web_enabled,
                service_mode=ServiceMode(args.service_mode),
            )
        else:
            try:
                config, install_cfg_path, local_profile = prompt_install_config(app_root=app_root)
            except RuntimeError as exc:
                ui_error(str(exc))
                return 2
        validation = validate_install_config(config)
        if validation.warnings:
            ui_warn("Setup validation produced warnings:")
            bullet_list(validation.warnings, style="warn")
        fatal_errors = fatal_bundle_validation_errors(validation.errors)
        if fatal_errors:
            failure_panel(
                "Invalid App Bundle",
                "AgentX setup cannot continue because the app bundle path is invalid.",
                guidance=fatal_errors + ["Fix the bundle path and re-run `agentx setup`."],
            )
            return 2
        if not validation.ok:
            ui_error("Setup validation failed:")
            bullet_list(validation.errors, style="error")
            return 2
        try:
            paths = run_with_status("Provisioning managed runtime and writing config", ensure_installation_ready, config)
        except Exception as e:
            install_log = config.runtime_root / "logs" / "install.log"
            failure_panel(
                "Setup Failed",
                str(e),
                guidance=[
                    "Review the install log for the exact failing command.",
                    "Fix the reported issue and run `agentx setup` again.",
                ],
                log_path=str(install_log),
            )
            return 2
        runtime_info = run_with_status("Verifying managed runtime", inspect_runtime, config)
        if not bool(runtime_info.get("ready")):
            failure_panel(
                "Setup Failed",
                "Managed runtime provisioning did not complete successfully.",
                guidance=[
                    "Run `agentx runtime inspect` for a detailed runtime report.",
                    "Review the install log and retry setup after fixing the issue.",
                ],
                log_path=str(runtime_info["install_log_path"]),
            )
            return 2
        write_installation(config, install_cfg_path)
        write_cli_launcher(config, paths, install_cfg_path)
        launcher_path = canonical_user_launcher_path()
        profile_path = save_local_profile(config.runtime_root, local_profile)
        ui_success(f"{BRAND_NAME} setup completed successfully.")
        summary_panel(
            f"{BRAND_NAME} Ready",
            [line for line in render_setup_summary(
                config,
                setup_complete=True,
                managed_runtime_path=str(paths.runtime_venv_dir),
                provisioning_ok=True,
                launcher_path=str(launcher_path),
            ).splitlines() if line.strip()],
            style="green",
        )
        next_steps_panel(
            "Next Steps",
            [
                "agentx doctor",
                "agentx start",
                "agentx stop",
                "agentx restart",
                "agentx status",
                "agentx uninstall",
            ],
            notes=[
                f"Launcher: {launcher_path}",
                f"Compatibility alias: {compatibility_user_launcher_path()}",
                f"Bootstrap fallback: {canonical_bootstrap_fallback()}",
                f"Managed runtime: {paths.runtime_venv_dir}",
                f"Runtime config: {paths.config_path}",
                f"Local profile: {profile_path}",
            ],
        )
        return 0

    if args.cmd in {"start", "stop", "restart", "status", "uninstall", "doctor", "health", "paths", "runtime", "service", "logs"} or (args.cmd == "config" and args.config_cmd == "show") or args.cmd == "internal":
        install = load_installation(install_cfg_path)
        if args.cmd == "start":
            result = run_with_status("Starting AgentX services", start_installation, install, install_config_path=install_cfg_path)
            _print_start_result(result)
            service_states = [item.get("state") for item in result.get("services", {}).values()]
            return 0 if all(state in {"started", "already_running", "disabled"} for state in service_states) else 2
        if args.cmd == "stop":
            result = run_with_status("Stopping AgentX services", stop_installation, install)
            _print_stop_result({"services": result})
            stop_states = [str((item or {}).get("state", "")) for item in result.values() if isinstance(item, dict)]
            return 0 if all(state in {"stopped", "already_stopped", "not_running", "stale_pid_removed", "disabled"} for state in stop_states) else 2
        if args.cmd == "restart":
            result = run_with_status("Restarting AgentX services", restart_installation, install, install_config_path=install_cfg_path)
            _print_restart_result(result)
            if not bool(result.get("ok")):
                return 2
            service_states = [item.get("state") for item in (result.get("start", {}) or {}).get("services", {}).values()]
            return 0 if all(state in {"started", "already_running", "disabled"} for state in service_states) else 2
        if args.cmd == "status":
            result = run_with_status("Inspecting AgentX status", status_installation, install)
            _print_status_result(result)
            return 0
        if args.cmd == "uninstall":
            if not getattr(args, "yes", False) and not _confirm_uninstall(install, keep_app_root=bool(getattr(args, "keep_app_root", False))):
                ui_note("Uninstall cancelled.")
                return 1
            result = run_with_status(
                "Removing the local AgentX install",
                uninstall_installation,
                install,
                install_config_path=install_cfg_path,
                remove_app_root=not bool(getattr(args, "keep_app_root", False)),
            )
            _print_uninstall_result(result)
            return 0
        if args.cmd == "doctor":
            if getattr(args, "fix", False):
                result = run_with_status("Running AgentX doctor with safe fixes", apply_safe_doctor_fixes, install, install_config_path=install_cfg_path)
                _print_doctor_fix_report(result)
                final_status = str(result.get("final_status", "FAIL"))
                fixes_applied = bool(result.get("fixes_applied"))
                if final_status == "OK":
                    return 0
                if final_status == "DEGRADED" and fixes_applied:
                    return 1
                return 2
            result = run_with_status("Running AgentX diagnostics", run_doctor, install)
            _print_doctor_report(result)
            return 0 if bool(result.get("ok")) else 2
        if args.cmd == "health":
            result = collect_health_report(install)
            _print_health_report(result)
            overall = str(result.get("overall", "unknown"))
            if overall == "OK":
                return 0
            if overall == "DEGRADED":
                return 1
            return 2
        if args.cmd == "paths":
            print(json.dumps(show_paths(install), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "logs":
            try:
                result = run_with_status(f"Reading {args.service} logs", read_service_logs, install, args.service, tail=int(args.tail))
            except Exception as exc:
                failure_panel("Logs Failed", str(exc))
                return 2
            _print_logs_header(install, args.service, int(args.tail), result)
            print(result.get("text", ""))
            return 0
        if args.cmd == "service":
            paths = compute_install_paths(install)
            try:
                if args.service_cmd == "install":
                    written = run_with_status("Installing systemd-user units", install_systemd_units, install, paths)
                    summary_panel("Service Units Installed", [str(path) for path in written], style="green")
                    return 0
                if args.service_cmd == "uninstall":
                    removed = run_with_status("Removing systemd-user units", remove_systemd_units, paths)
                    summary_panel("Service Units Removed", [str(path) for path in removed] or ["No unit files were present."], style="#8A5BFF")
                    return 0
                if args.service_cmd == "enable":
                    states = run_with_status("Enabling systemd-user units", enable_systemd_units, install)
                    ui_success("AgentX systemd-user units enabled.")
                    _print_service_toggle_summary(
                        "Auto-start Enabled",
                        states,
                        note="AgentX will start automatically on login when the user systemd session is active.",
                    )
                    return 0
                if args.service_cmd == "disable":
                    states = run_with_status("Disabling systemd-user units", disable_systemd_units, install)
                    ui_success("AgentX systemd-user units disabled.")
                    _print_service_toggle_summary(
                        "Auto-start Disabled",
                        states,
                        note="AgentX will no longer start automatically on login until the units are enabled again.",
                    )
                    return 0
                if args.service_cmd == "status":
                    result = run_with_status("Inspecting AgentX service status", status_installation, install)
                    _print_service_status(result)
                    return 0
            except Exception as exc:
                failure_panel("Service Command Failed", str(exc))
                return 2
        if args.cmd == "runtime" and args.runtime_cmd == "inspect":
            result = inspect_runtime(install)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if bool(result.get("ready")) else 2
        if args.cmd == "config" and args.config_cmd == "show":
            print(json.dumps({"install_config": install.to_dict(), "runtime_paths": show_paths(install)}, ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "internal" and args.internal_cmd == "serve-api":
            try:
                return serve_api_forever(install)
            except Exception:
                paths = compute_install_paths(install)
                paths.api_log_path.parent.mkdir(parents=True, exist_ok=True)
                with paths.api_log_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n[internal serve-api failure]\n")
                    handle.write(traceback.format_exc())
                    handle.write("\n")
                return 2
        if args.cmd == "internal" and args.internal_cmd == "serve-web":
            try:
                return serve_web_forever(install)
            except Exception:
                paths = compute_install_paths(install)
                paths.web_log_path.parent.mkdir(parents=True, exist_ok=True)
                with paths.web_log_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n[internal serve-web failure]\n")
                    handle.write(traceback.format_exc())
                    handle.write("\n")
                return 2

    config_path = args.config
    if args.config == "config/agentx.toml" and install_cfg_path.exists():
        config_path = str(load_installation(install_cfg_path).config_path)
    services = build_runtime_services_from_config(config_path=config_path, confirm=_confirm)
    agent = services.agent

    if args.cmd == "run":
        stdin_text = read_stdin_text(sys.stdin)
        if not list(args.task or []) and not str(getattr(args, "file", "") or "").strip() and stdin_text is None:
            return interactive_run(agent)
        task_text = " ".join(str(part) for part in (args.task or [])).strip()
        file_text: str | None = None
        file_arg = str(getattr(args, "file", "") or "").strip()
        if file_arg:
            file_result = read_task_file(file_arg)
            if not isinstance(file_result, str):
                print(file_result.text)
                return file_result.exit_code
            file_text = file_result
        prompt = compose_run_prompt(task_text, file_text=file_text, stdin_text=stdin_text)
        if not isinstance(prompt, str):
            print(prompt.text)
            return prompt.exit_code
        install = load_installation(install_cfg_path)
        status: dict[str, object] | None = None
        try:
            status = status_installation(install)
        except Exception:
            status = None
        result = run_task_via_api(install, prompt, status=status)
        print(result.text)
        return result.exit_code

    if args.cmd == "tool":
        tool_args = _parse_tool_args(args.json, list(args.tool_args or []))
        res = agent.run_tool(tool_name=args.name, tool_args=tool_args, reason=args.reason)
        print("PLAN:")
        for step in res.plan.steps:
            print(f"- tool={step.tool_name} reason={step.reason!r} args={step.arguments}")
        print("")
        print(res.text)
        return 0 if res.ok else 2

    if args.cmd == "ingest":
        tags = [t for t in (args.tags or []) if isinstance(t, str) and t.strip()]
        out = agent.ingest_path(
            path=args.path,
            tags=tags,
            reason=args.reason,
            recursive=bool(args.recursive),
            max_files=int(args.max_files),
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "memory":
        if args.memory_cmd == "stats":
            out = agent.memory_stats(reason=args.reason)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        if args.memory_cmd == "prune":
            out = agent.memory_prune(older_than_days=int(args.older_than_days), reason=args.reason, dry_run=bool(args.dry_run))
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        return 2

    if args.cmd == "selfcheck":
        res = agent.run_tool(
            tool_name="selfcheck.run",
            tool_args={
                "mode": str(args.mode),
                "json": bool(args.json),
                "fix": bool(args.fix),
                "exercise_cli_tool_wrappers": bool(getattr(args, "exercise_cli_tool_wrappers", False)),
            },
            reason=str(args.reason or "SelfCheck"),
        )
        out = res.tool_results[-1].output if res.tool_results else None
        if isinstance(out, str):
            print(out)
            return 2 if "Overall: FAIL" in out else 0
        if isinstance(out, dict):
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 2 if str(out.get("overall") or "").upper() == "FAIL" else 0
        print(json.dumps({"ok": bool(res.ok), "output": out}, ensure_ascii=False, indent=2))
        return 0 if res.ok else 2

    if args.cmd == "job":
        runner = JobRunner(
            agent=services.agent,
            store=services.job_store,
            plugin_manager=services.plugin_manager,
            skill_manager=services.skill_manager,
            hint_store=services.hint_store,
        )
        if args.job_cmd == "create":
            job = runner.create_job(
                goal=str(args.goal),
                skill_id=(str(args.skill).strip() or None),
                max_steps=int(args.max_steps),
                max_failures=int(args.max_failures),
                max_runtime_s=int(args.max_runtime_s),
            )
            print(json.dumps(services.job_store._to_dict(job), ensure_ascii=False, indent=2))
            return 0
        if args.job_cmd == "run":
            job = runner.run_to_terminal(args.job_id)
            print(json.dumps(services.job_store._to_dict(job), ensure_ascii=False, indent=2))
            return 0 if job.status.value == "completed" else 2
        if args.job_cmd == "show":
            job = services.job_store.load(args.job_id)
            print(json.dumps(services.job_store._to_dict(job), ensure_ascii=False, indent=2))
            return 0
        if args.job_cmd == "cancel":
            job = runner.cancel(args.job_id, reason=str(args.reason or ""))
            print(json.dumps(services.job_store._to_dict(job), ensure_ascii=False, indent=2))
            return 0
        if args.job_cmd == "approve":
            job = runner.approve_pending(args.job_id, approved=not bool(args.deny), note=str(args.note or ""))
            print(json.dumps(services.job_store._to_dict(job), ensure_ascii=False, indent=2))
            return 0

    if args.cmd == "plugins":
        if args.plugins_cmd == "list":
            rows = []
            for rec in services.plugin_manager.list_plugins():
                rows.append(
                    {
                        "id": rec.manifest.plugin_id,
                        "name": rec.manifest.name,
                        "enabled": rec.enabled,
                        "risk_level": rec.manifest.risk_level,
                        "tools": [t.name for t in rec.manifest.tools],
                        "error": rec.error,
                    }
                )
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if args.plugins_cmd == "enable":
            rec = services.plugin_manager.set_enabled(args.plugin_id, True)
            print(json.dumps({"id": rec.manifest.plugin_id, "enabled": rec.enabled}, ensure_ascii=False, indent=2))
            return 0
        if args.plugins_cmd == "disable":
            rec = services.plugin_manager.set_enabled(args.plugin_id, False)
            print(json.dumps({"id": rec.manifest.plugin_id, "enabled": rec.enabled}, ensure_ascii=False, indent=2))
            return 0

    if args.cmd == "skills":
        if args.skills_cmd == "list":
            rows = []
            for rec in services.skill_manager.list_skills():
                rows.append(
                    {
                        "id": rec.skill_id,
                        "name": rec.name,
                        "source": rec.source,
                        "required_plugins": list(rec.required_plugins),
                        "risk_level": rec.risk_level,
                    }
                )
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if args.skills_cmd == "import-pack":
            rec = services.skill_manager.import_skill_pack(args.source_dir, skill_id=(str(args.skill_id).strip() or None))
            print(
                json.dumps(
                    {
                        "id": rec.skill_id,
                        "name": rec.name,
                        "source": rec.source,
                        "required_plugins": list(rec.required_plugins),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

    return 0
