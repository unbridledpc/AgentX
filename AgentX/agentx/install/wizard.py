from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from agentx.install.models import ApiRuntimeConfig, AuthRuntimeConfig, InstallConfig, InstallProfile, ServiceMode, WebRuntimeConfig
from agentx.install.local_profile import LocalProfileSelection, build_local_profile
from agentx.install.ollama import (
    DEFAULT_OLLAMA_BASE_URL,
    build_ollama_base_url,
    is_full_ollama_url,
    normalize_ollama_base_url,
    probe_ollama_endpoint,
    wsl_ollama_guidance,
)
from agentx.install.platform import detect_platform
from agentx.install.store import default_install_config_path
from agentx.install.ui import (
    BRAND_NAME,
    BRAND_SUBTITLE,
    SummaryItem,
    bullet_list,
    error as ui_error,
    failure_panel,
    info as ui_info,
    next_steps_panel,
    note as ui_note,
    preflight_result,
    run_with_status,
    section,
    show_logo,
    spacer,
    stage,
    subsection,
    success as ui_success,
    summary_panel,
    warn as ui_warn,
)


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class PromptSpec:
    title: str
    prompt: str
    default: str
    help_text: str


@dataclass(frozen=True)
class PreflightCheck:
    status: str
    title: str
    details: str


_INVALID_APP_ROOT_MARKERS = (
    "/site-packages/",
    "\\site-packages\\",
    "/dist-packages/",
    "\\dist-packages\\",
    "/venv/lib/python",
    "\\venv\\lib\\python",
    "bootstrap/venv/lib/python",
    "bootstrap\\venv\\lib\\python",
)


def _is_wsl_mount_path(path: Path) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return (
        normalized == "/mnt"
        or normalized.startswith("/mnt/")
        or normalized.endswith(":/mnt")
        or ":/mnt/" in normalized
    )


def app_root_sanity_error(app_root: Path) -> str | None:
    normalized = str(app_root).replace("\\", "/").lower()
    if any(marker in normalized for marker in _INVALID_APP_ROOT_MARKERS):
        return (
            f"Invalid AgentX app bundle root detected: {app_root}\n"
            "This points inside a Python environment, not a AgentX bundle.\n"
            "Re-run install-agentx.sh or repair the bootstrap launcher."
        )
    return None


def fatal_bundle_validation_errors(errors: tuple[str, ...] | list[str]) -> list[str]:
    return [
        str(item)
        for item in errors
        if str(item).startswith("App root")
        or "built frontend assets are missing" in str(item)
        or "packaging metadata is missing" in str(item)
        or "Invalid AgentX app bundle root detected" in str(item)
    ]


def _normalize_setup_path_input(
    raw_value: str,
    *,
    default_value: str,
    platform_info,
    label: str,
) -> Path:
    text = raw_value.strip()
    if not text:
        text = default_value
    if getattr(platform_info, "is_linux", False) and "\\" in text:
        raise ValueError(
            f"{label} must use Linux-style paths such as `/home/user/agentx` or `/srv/agentx`. "
            "Backslashes are not valid here."
        )
    return Path(text).expanduser().resolve(strict=False)


def profile_defaults(profile: InstallProfile) -> tuple[bool, bool]:
    if profile == InstallProfile.CLI:
        return False, False
    if profile == InstallProfile.STANDARD:
        return True, True
    if profile == InstallProfile.SERVER:
        return True, False
    return True, True


def profile_description(profile: InstallProfile) -> str:
    return {
        InstallProfile.CLI: "Run AgentX from the terminal only (no web UI).",
        InstallProfile.STANDARD: "Recommended: AgentX CLI + API + Web UI.",
        InstallProfile.SERVER: "Run AgentX as a background service with the API only (no UI).",
        InstallProfile.DEVELOPER: "Full AgentX development setup with CLI, API, web UI, and broader local access.",
    }[profile]


def build_install_config(
    *,
    app_root: Path,
    runtime_root: Path,
    working_dir: Path,
    profile: InstallProfile,
    model_provider: str,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    api_host: str,
    api_port: int,
    web_host: str,
    web_port: int,
    web_enabled: bool | None = None,
    service_mode: ServiceMode = ServiceMode.NONE,
    install_name: str = "default",
) -> InstallConfig:
    default_api_enabled, default_web_enabled = profile_defaults(profile)
    config_path = runtime_root / "config" / "agentx.toml"
    return InstallConfig(
        schema_version=1,
        install_name=install_name,
        profile=profile,
        service_mode=service_mode,
        app_root=app_root.expanduser().resolve(),
        runtime_root=runtime_root.expanduser().resolve(),
        working_dir=working_dir.expanduser().resolve(),
        config_path=config_path.expanduser().resolve(),
        model_provider=(model_provider or "ollama").strip().lower() or "ollama",
        ollama_base_url=normalize_ollama_base_url(ollama_base_url),
        api=ApiRuntimeConfig(enabled=default_api_enabled, host=api_host.strip() or "127.0.0.1", port=int(api_port)),
        web=WebRuntimeConfig(
            enabled=default_web_enabled if web_enabled is None else bool(web_enabled),
            host=web_host.strip() or "127.0.0.1",
            port=int(web_port),
            open_browser=False,
        ),
        auth=AuthRuntimeConfig(enabled=False),
    )


def _path_writable(path: Path) -> bool:
    probe_dir = path if path.exists() and path.is_dir() else path.parent
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe = probe_dir / ".agentx-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def validate_install_config(config: InstallConfig) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    platform_info = detect_platform()
    sanity_error = app_root_sanity_error(config.app_root)
    if sanity_error:
        errors.append(sanity_error)
    if not config.app_root.exists():
        errors.append(f"App root does not exist: {config.app_root}")
    if not (config.app_root / "AgentX" / "agentx").exists():
        errors.append(f"App root does not look like a AgentX bundle: {config.app_root}")
    for label, path in (("runtime root", config.runtime_root), ("working directory", config.working_dir)):
        if not _path_writable(path):
            errors.append(f"{label.capitalize()} is not writable: {path}")
    if config.runtime_root == config.app_root:
        warnings.append("Runtime root matches app root. Product installs are cleaner when mutable state is stored separately.")
    if platform_info.is_wsl and _is_wsl_mount_path(config.runtime_root):
        warnings.append("Runtime root is under /mnt/*. This works, but Linux filesystem paths are usually faster and more reliable in WSL.")
    if str(config.working_dir).startswith(str(config.app_root)):
        warnings.append("Working directory is inside the app bundle. Prefer a separate work area.")
    if platform_info.is_wsl and _is_wsl_mount_path(config.working_dir):
        warnings.append("Working directory is under /mnt/*. Linux filesystem paths are usually faster and more reliable in WSL.")
    if config.web.enabled:
        web_dist = config.app_root / "AgentXWeb" / "dist" / "index.html"
        if not web_dist.exists():
            errors.append(f"Web UI is enabled but built frontend assets are missing: {web_dist}")
    provider = config.model_provider.strip().lower()
    if provider not in {"ollama", "openai", "stub"}:
        errors.append(f"Unsupported model provider: {provider}")
    if provider == "ollama":
        probe = probe_ollama_endpoint(config.ollama_base_url)
        if probe.status == "unreachable":
            warnings.append(probe.message)
            for note in wsl_ollama_guidance(platform_info=platform_info, base_url=config.ollama_base_url):
                warnings.append(note)
        elif probe.status == "reachable_no_models":
            warnings.append(probe.message)
    if provider == "openai" and not (os.environ.get("AGENTX_OPENAI_API_KEY") or os.environ.get("SOL_OPENAI_API_KEY") or os.environ.get("NEXAI_OPENAI_API_KEY")):
        warnings.append("OpenAI provider selected but AGENTX_OPENAI_API_KEY is not set in the current environment.")
    if config.api.port <= 0 or config.api.port > 65535:
        errors.append(f"Invalid API port: {config.api.port}")
    if config.web.port <= 0 or config.web.port > 65535:
        errors.append(f"Invalid web port: {config.web.port}")
    if config.service_mode == ServiceMode.SYSTEMD_USER and not platform_info.systemd_user_available:
        warnings.append("systemd user services are not active in this environment. AgentX can still run with direct lifecycle commands.")
    if not (config.app_root / "AgentX" / "pyproject.toml").exists():
        warnings.append("AgentX packaging metadata is missing from the app bundle. Automatic dependency provisioning may be unavailable.")
    return ValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def _print_profiles() -> None:
    summary_panel(
        "Install Profiles",
        [(profile.value, profile_description(profile)) for profile in InstallProfile],
        style="#5B8CFF",
    )


def _is_path_on_env(path: Path) -> bool:
    target = str(path.expanduser().resolve(strict=False))
    for item in os.environ.get("PATH", "").split(os.pathsep):
        if not item:
            continue
        try:
            candidate = str(Path(item).expanduser().resolve(strict=False))
        except Exception:
            candidate = item
        if candidate == target:
            return True
    return False


def _run_preflight(*, app_root: Path, install_cfg_path: Path) -> tuple[list[PreflightCheck], list[str]]:
    platform_info = detect_platform()
    checks: list[PreflightCheck] = []
    failures: list[str] = []
    launcher_dir = Path.home() / ".local" / "bin"
    bootstrap_root = Path.home() / ".local" / "share" / "agentx" / "bootstrap"
    runtime_root = Path.home() / ".local" / "share" / "agentx"

    if sys.version_info >= (3, 10):
        checks.append(PreflightCheck("pass", "Python version", f"Using Python {sys.version.split()[0]}"))
    else:
        failures.append("Install or use Python 3.10 or newer, then run `agentx setup` again.")
        checks.append(PreflightCheck("fail", "Python version", f"Python {sys.version.split()[0]} is too old for AgentX"))

    if importlib.util.find_spec("venv") is not None:
        checks.append(PreflightCheck("pass", "Python venv module", "Managed runtime creation is available"))
    else:
        failures.append("Install the system package that provides python3-venv before running setup.")
        checks.append(PreflightCheck("fail", "Python venv module", "The `venv` module is not available in this interpreter"))

    install_dir = install_cfg_path.parent
    if _path_writable(install_dir):
        checks.append(PreflightCheck("pass", "Install config directory", f"Writable: {install_dir}"))
    else:
        failures.append(f"Make this directory writable before continuing: {install_dir}")
        checks.append(PreflightCheck("fail", "Install config directory", f"Not writable: {install_dir}"))

    if _path_writable(launcher_dir):
        checks.append(PreflightCheck("pass", "Launcher directory", f"Writable: {launcher_dir}"))
    else:
        failures.append(f"Create or fix permissions for the launcher directory: {launcher_dir}")
        checks.append(PreflightCheck("fail", "Launcher directory", f"Not writable: {launcher_dir}"))

    if _is_path_on_env(launcher_dir):
        checks.append(PreflightCheck("pass", "PATH", f"{launcher_dir} is on PATH"))
    else:
        checks.append(PreflightCheck("warn", "PATH", f"{launcher_dir} is not on PATH yet. Direct launcher use will still work."))

    if platform_info.is_wsl:
        checks.append(PreflightCheck("warn", "Environment", "WSL detected. Linux filesystem paths are usually the safest choice."))
    else:
        checks.append(PreflightCheck("pass", "Environment", f"Detected platform: {getattr(platform_info, 'system', 'unknown')}"))

    if platform_info.is_wsl and _is_wsl_mount_path(app_root):
        checks.append(PreflightCheck("warn", "App bundle location", f"{app_root} is under /mnt/*. This can be slower on WSL."))
    else:
        checks.append(PreflightCheck("pass", "App bundle location", str(app_root)))

    if bootstrap_root.exists():
        checks.append(PreflightCheck("pass", "Bootstrap environment", f"Existing bootstrap data found at {bootstrap_root}"))
    else:
        checks.append(PreflightCheck("warn", "Bootstrap environment", f"No bootstrap data found yet at {bootstrap_root}"))

    if runtime_root.exists():
        checks.append(PreflightCheck("warn", "Existing runtime data", f"Existing runtime state found at {runtime_root}"))
    else:
        checks.append(PreflightCheck("pass", "Existing runtime data", f"No prior runtime data found at {runtime_root}"))

    existing_agentx = shutil.which("agentx")
    expected_agentx = launcher_dir / "agentx"
    if existing_agentx and Path(existing_agentx).resolve(strict=False) != expected_agentx.resolve(strict=False):
        checks.append(PreflightCheck("warn", "Command shadowing", f"`agentx` on PATH resolves to {existing_agentx}. AgentX prefers {expected_agentx}."))
    elif existing_agentx:
        checks.append(PreflightCheck("pass", "Command shadowing", f"`agentx` resolves to {existing_agentx}"))
    else:
        checks.append(PreflightCheck("warn", "Command shadowing", "No `agentx` launcher is currently on PATH. Setup will still complete."))
    existing_sol = shutil.which("sol")
    if existing_sol:
        checks.append(PreflightCheck("warn", "Legacy sol command", f"`sol` may resolve to a system game or another command: {existing_sol}. Use `agentx` as the supported command."))

    return checks, failures


def _render_preflight(*, app_root: Path, install_cfg_path: Path) -> None:
    section("System Check", subtitle="Validating your environment before AgentX asks for install choices.")
    checks, failures = _run_preflight(app_root=app_root, install_cfg_path=install_cfg_path)
    for check in checks:
        preflight_result(check.status, check.title, check.details)
    if failures:
        spacer()
        failure_panel(
            "Preflight Failed",
            "AgentX setup cannot continue until these issues are fixed.",
            guidance=failures,
        )
        raise RuntimeError("Preflight checks failed.")
    spacer()
    ui_success("System check passed. AgentX is ready to configure.")


def _ask(spec: PromptSpec, *, index: int | None = None, total: int | None = None, render_heading: bool = True) -> str:
    if render_heading:
        if index is not None and total is not None:
            stage(index, total, spec.title)
        else:
            section(spec.title)
    while True:
        value = input(f"{spec.prompt} [{spec.default}] (? for help): ").strip()
        if value == "?":
            bullet_list(spec.help_text.splitlines())
            continue
        return value or spec.default


def _ask_path(spec: PromptSpec, *, platform_info, label: str, index: int | None = None, total: int | None = None, render_heading: bool = True) -> Path:
    if render_heading:
        if index is not None and total is not None:
            stage(index, total, spec.title)
        else:
            section(spec.title)
    while True:
        raw_value = input(f"{spec.prompt} [{spec.default}] (? for help): ")
        value = raw_value.strip()
        if value == "?":
            bullet_list(spec.help_text.splitlines())
            continue
        try:
            path = _normalize_setup_path_input(
                value,
                default_value=spec.default,
                platform_info=platform_info,
                label=label,
            )
        except ValueError as exc:
            ui_error(f"Invalid path: {exc}")
            continue
        if getattr(platform_info, "is_wsl", False) and _is_wsl_mount_path(path):
            ui_warn("This path is under /mnt/*. It can work, but Linux filesystem paths are usually faster and more reliable in WSL.")
        return path


def _profile_prompt() -> PromptSpec:
    return PromptSpec(
        title="Install Profile",
        prompt="Choose how you want to run AgentX",
        default="standard",
        help_text=(
            "What this controls:\n"
            "- Picks the main way AgentX will be used.\n"
            "Why it matters:\n"
            "- It decides whether the API and web UI are enabled by default.\n"
            "When to change it:\n"
            "- Change this if you only want terminal use, a headless server, or a dev-focused setup.\n"
            "Profiles:\n"
            "- cli: Run AgentX from the terminal only (no web UI).\n"
            "- standard: Recommended: AgentX CLI + API + Web UI.\n"
            "- server: Run AgentX as a background service (no UI).\n"
            "- developer: Full AgentX development setup with all tools and local access."
        ),
    )


def _runtime_prompt() -> PromptSpec:
    return PromptSpec(
        title="Runtime Data Directory",
        prompt="Where should AgentX store its runtime data",
        default=str(Path.home() / ".local" / "share" / "agentx"),
        help_text=(
            "What is stored here:\n"
            "- logs, memory databases, jobs, runtime extensions, caches, and audit data.\n"
            "Why it matters:\n"
            "- This is AgentX's writable state directory.\n"
            "Safe default:\n"
            "- The default location is suitable for most users.\n"
            "When to change it:\n"
            "- Use a different path if you want larger storage, a different disk, or a shared mounted location.\n"
            "Examples:\n"
            f"- {Path.home() / '.local' / 'share' / 'agentx'}\n"
            "- /srv/agentx/runtime"
        ),
    )


def _working_prompt() -> PromptSpec:
    return PromptSpec(
        title="Working Directory",
        prompt="Where should AgentX work on your files by default",
        default=str(Path.home() / "agentx-work"),
        help_text=(
            "What this is:\n"
            "- The default folder where AgentX will operate on files and projects.\n"
            "Why it matters:\n"
            "- It becomes the main safe workspace for file tasks.\n"
            "Safe default:\n"
            "- Leaving the default is fine if you do not already have a preferred work folder.\n"
            "When to change it:\n"
            "- Change it if you already keep projects somewhere else.\n"
            "Examples:\n"
            f"- {Path.home() / 'agentx-work'}\n"
            f"- {Path.home() / 'projects'}\n"
            "- /srv/agentx/work"
        ),
    )


def _provider_prompt() -> PromptSpec:
    return PromptSpec(
        title="Model Provider",
        prompt="Choose the model provider",
        default="ollama",
        help_text=(
            "What this controls:\n"
            "- Which model backend AgentX uses for assistant responses and planning.\n"
            "Why it matters:\n"
            "- It changes whether AgentX runs local models, remote API models, or no real model at all.\n"
            "Options:\n"
            "- ollama: Local models running on your machine. Choose this for local-first use.\n"
            "- openai: Remote API models. Choose this if you have an API key and want hosted models.\n"
            "- stub: Testing mode with no real model. Useful for setup checks and development.\n"
            "When to change it:\n"
            "- Choose openai if you already use the OpenAI API.\n"
            "- Choose stub only for testing."
        ),
    )


def _service_prompt() -> PromptSpec:
    return PromptSpec(
        title="Service Install",
        prompt="Install AgentX as a background service",
        default="none",
        help_text=(
            "What this controls:\n"
            "- Whether AgentX writes a user service so it can be started through systemd.\n"
            "Why it matters:\n"
            "- Useful if you want AgentX to run in the background more like a system app.\n"
            "Options:\n"
            "- none: Safe default. Start AgentX manually with `agentx start`.\n"
            "- systemd-user: Creates a per-user service managed by systemd.\n"
            "When to use systemd-user:\n"
            "- Use it on Linux systems where `systemd --user` is available and active.\n"
            "WSL note:\n"
            "- Some WSL setups do not run systemd user services. In that case, keep `none`."
        ),
    )


def _ollama_endpoint_prompt(*, platform_info, default_url: str) -> PromptSpec:
    extra = ""
    guidance = wsl_ollama_guidance(platform_info=platform_info, base_url=default_url)
    if guidance:
        extra = "\nWSL guidance:\n" + "\n".join(f"- {line}" for line in guidance)
    return PromptSpec(
        title="Ollama Endpoint",
        prompt="Where is Ollama running",
        default=default_url,
        help_text=(
            "What this is:\n"
            "- The base URL AgentX will use to talk to Ollama.\n"
            "Why it matters:\n"
            "- AgentX cannot discover models or run Ollama chats unless this endpoint is reachable.\n"
            "Examples:\n"
            f"- {DEFAULT_OLLAMA_BASE_URL}\n"
            "- http://192.168.1.50:11434\n"
            "- http://host.docker.internal:11434\n"
            "When to change it:\n"
            "- Change it if Ollama runs on another machine, in another container, or on Windows while AgentX runs inside WSL."
            + extra
        ),
    )


def _ollama_host_prompt(default_host: str) -> PromptSpec:
    return PromptSpec(
        title="Ollama Host",
        prompt="Ollama host or IP",
        default=default_host,
        help_text=(
            "What this is:\n"
            "- The host name or IP address where Ollama is reachable.\n"
            "Why it matters:\n"
            "- AgentX builds the full Ollama endpoint from this host and the port.\n"
            "Normal examples:\n"
            "- 127.0.0.1\n"
            "- localhost\n"
            "- <your-ollama-host>\n"
            "Power-user option:\n"
            "- You can also paste a full URL like http://localhost:11434 and AgentX will use it directly."
        ),
    )


def _ollama_port_prompt(default_port: str) -> PromptSpec:
    return PromptSpec(
        title="Ollama Port",
        prompt="Ollama port",
        default=default_port,
        help_text=(
            "What this is:\n"
            "- The port where Ollama listens.\n"
            "Why it matters:\n"
            "- AgentX combines this port with the Ollama host to form the endpoint.\n"
            "Safe default:\n"
            "- 11434 is the standard Ollama port.\n"
            "When to change it:\n"
            "- Change it only if your Ollama server is configured to use another port."
        ),
    )


def _prompt_ollama_endpoint(*, platform_info) -> str:
    default_url = normalize_ollama_base_url(DEFAULT_OLLAMA_BASE_URL)
    parsed = urllib.parse.urlparse(default_url)
    default_host = parsed.hostname or "127.0.0.1"
    default_port = str(parsed.port or 11434)
    while True:
        host_or_url = input(f"{_ollama_host_prompt(default_host).prompt} [{default_host}] (? for help): ").strip()
        if host_or_url == "?":
            bullet_list(_ollama_host_prompt(default_host).help_text.splitlines())
            continue
        host_or_url = host_or_url or default_host
        try:
            if is_full_ollama_url(host_or_url):
                base_url = build_ollama_base_url(host_or_url=host_or_url)
            else:
                port_value = input(f"{_ollama_port_prompt(default_port).prompt} [{default_port}] (? for help): ").strip()
                if port_value == "?":
                    bullet_list(_ollama_port_prompt(default_port).help_text.splitlines())
                    continue
                base_url = build_ollama_base_url(host_or_url=host_or_url, port=port_value or default_port)
        except ValueError as exc:
            ui_error(f"Invalid Ollama endpoint: {exc}")
            continue
        guidance = wsl_ollama_guidance(platform_info=platform_info, base_url=base_url)
        if platform_info.is_wsl and host_or_url in {"127.0.0.1", "localhost"}:
            for note in guidance:
                ui_warn(note)
        return base_url


_BIND_ALL_HOSTS = {"0.0.0.0", "::", "[::]"}


def _detect_primary_interface_ip() -> str | None:
    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.25)
            sock.connect(("8.8.8.8", 80))
            candidates.append(sock.getsockname()[0])
    except OSError:
        pass
    try:
        candidates.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    for candidate in candidates:
        if candidate and not candidate.startswith("127."):
            return candidate
    return None


def _format_url_host(host: str) -> str:
    host = (host or "").strip()
    if not host:
        return "127.0.0.1"
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host


def display_host_for_bind_host(host: str) -> str:
    normalized = (host or "").strip().lower()
    if normalized in _BIND_ALL_HOSTS:
        return _detect_primary_interface_ip() or "127.0.0.1"
    return _format_url_host(host or "127.0.0.1")


def web_ui_display_url(config: InstallConfig) -> str | None:
    if not config.web.enabled:
        return None
    return f"http://{display_host_for_bind_host(config.web.host)}:{config.web.port}"

def render_setup_summary(
    config: InstallConfig,
    *,
    setup_complete: bool = False,
    managed_runtime_path: str | None = None,
    provisioning_ok: bool | None = None,
    launcher_path: str | None = None,
) -> str:
    web_url = web_ui_display_url(config)
    lines = [
        "",
        f"{BRAND_NAME} is ready." if setup_complete else f"{BRAND_NAME} setup plan:",
        "Summary:",
        f"- Product: {BRAND_NAME}",
        f"- Tagline: {BRAND_SUBTITLE}",
        f"- App bundle: {config.app_root}",
        f"- Runtime data: {config.runtime_root}",
        f"- Working directory: {config.working_dir}",
        f"- Install profile: {config.profile.value}",
        f"- Model provider: {config.model_provider}",
        f"- API auth: {'enabled' if config.auth.enabled else 'disabled (local-first default)'}",
        f"- Ollama endpoint: {config.ollama_base_url}" if config.model_provider == "ollama" else None,
        f"- Managed runtime: {managed_runtime_path}" if managed_runtime_path else None,
        f"- CLI launcher: {launcher_path}" if launcher_path else None,
        f"- Provisioning: {'succeeded' if provisioning_ok else 'pending' if provisioning_ok is None else 'failed'}",
        f"- Start AgentX: {launcher_path} start" if launcher_path else f"- Start AgentX: agentx --install-config {default_install_config_path()} start",
        f"- Check status: {launcher_path} status" if launcher_path else f"- Check status: agentx --install-config {default_install_config_path()} status",
    ]
    lines = [line for line in lines if line]
    if web_url:
        lines.append(f"- Open the web UI: {web_url}")
    return "\n".join(lines)


def render_profile_summary(selection: LocalProfileSelection | None) -> str:
    resolved = build_local_profile(
        mode=(selection.mode if selection else "os-fallback"),
        display_name=(selection.display_name if selection else None),
        profile_id=(selection.profile_id if selection else None),
    )
    lines = [
        "Local profile:",
        f"- Mode: {resolved.mode}",
        f"- Display name: {resolved.display_name}",
        f"- Profile ID: {resolved.profile_id}",
        f"- Memory namespace: {resolved.memory_namespace}",
    ]
    return "\n".join(lines)


def _print_setup_summary(config: InstallConfig) -> None:
    print(render_setup_summary(config))


def _profile_mode_prompt() -> PromptSpec:
    return PromptSpec(
        title="Local Profile",
        prompt="Set a local AgentX profile or skip it",
        default="skip",
        help_text=(
            "What this controls:\n"
            "- Whether AgentX stores a simple local profile for display and internal identity.\n"
            "Why it matters:\n"
            "- AgentX uses this for local labels, audit metadata, and runtime defaults.\n"
            "Options:\n"
            "- set: Create a local profile with a display name and optional profile ID.\n"
            "- skip: Do not create one. AgentX will fall back to your OS username automatically.\n"
            "Safe default:\n"
            "- `skip` is fine if you do not care about naming AgentX locally yet."
        ),
    )


def _display_name_prompt(default_display_name: str) -> PromptSpec:
    return PromptSpec(
        title="Display Name",
        prompt="Choose a local display name for AgentX to use",
        default=default_display_name,
        help_text=(
            "What this is:\n"
            "- A friendly local name AgentX will use in labels and local metadata.\n"
            "Why it matters:\n"
            "- It makes logs and local runtime context easier to recognize.\n"
            "When to change it:\n"
            "- Change it if you want AgentX to use your preferred name instead of the OS-derived default.\n"
            "Example:\n"
            f"- {default_display_name}"
        ),
    )


def _profile_id_prompt(default_profile_id: str) -> PromptSpec:
    return PromptSpec(
        title="Profile ID",
        prompt="Optional: choose a local profile ID",
        default=default_profile_id,
        help_text=(
            "What this is:\n"
            "- A stable local identifier used internally for audit metadata and namespaces.\n"
            "Why it matters:\n"
            "- It should stay short and stable if you want predictable local identity.\n"
            "When to change it:\n"
            "- Change it if you want something specific like `jane-dev` or `lab-server`.\n"
            "Safe default:\n"
            "- The OS-based default is usually fine."
        ),
    )


def prompt_local_profile_selection() -> LocalProfileSelection | None:
    mode = _ask(_profile_mode_prompt(), render_heading=False).strip().lower()
    if mode not in {"set", "skip"}:
        mode = "skip"
    if mode == "skip":
        return LocalProfileSelection(mode="os-fallback")
    default_profile = build_local_profile(mode="os-fallback")
    display_name = _ask(_display_name_prompt(default_profile.display_name)).strip()
    profile_id = _ask(_profile_id_prompt(default_profile.profile_id)).strip()
    return LocalProfileSelection(
        mode="explicit",
        display_name=display_name or default_profile.display_name,
        profile_id=profile_id or default_profile.profile_id,
    )


def prompt_install_config(*, app_root: Path) -> tuple[InstallConfig, Path, LocalProfileSelection | None]:
    install_cfg_path = default_install_config_path()
    platform_info = detect_platform()
    total_steps = 10
    sanity_error = app_root_sanity_error(app_root)
    if sanity_error:
        failure_panel(
            "Invalid App Bundle",
            "AgentX setup cannot continue with the detected app root.",
            guidance=sanity_error.splitlines(),
        )
        raise RuntimeError("Invalid AgentX bundle root. Re-run install-agentx.sh or repair the bootstrap launcher.")
    show_logo()
    info_items = [
        SummaryItem("Product", BRAND_NAME),
        SummaryItem("App bundle", str(app_root)),
        SummaryItem("Default install config", str(install_cfg_path)),
    ]
    if platform_info.is_wsl:
        info_items.append(SummaryItem("Environment", "WSL detected"))
    summary_panel("Setup Overview", info_items, style="#5B8CFF")
    ui_info("This setup wizard will guide you through a product-style install.")
    ui_info("Tip: type `?` at any prompt to see expanded help.")
    if platform_info.is_wsl:
        ui_warn("WSL detected. Linux filesystem paths are usually the safest choice.")
    _render_preflight(app_root=app_root, install_cfg_path=install_cfg_path)
    _print_profiles()
    while True:
        profile_raw = _ask(_profile_prompt(), index=1, total=total_steps).lower()
        profile = InstallProfile(profile_raw if profile_raw in {p.value for p in InstallProfile} else InstallProfile.STANDARD.value)
        runtime_root = _ask_path(_runtime_prompt(), platform_info=platform_info, label="Runtime data directory", index=2, total=total_steps)
        working_dir = _ask_path(_working_prompt(), platform_info=platform_info, label="Working directory", index=3, total=total_steps)
        stage(4, total_steps, "Local Profile", subtitle="Choose a local identity or use your OS fallback")
        local_profile = prompt_local_profile_selection()
        model_provider = _ask(_provider_prompt(), index=5, total=total_steps).lower()
        ollama_base_url = DEFAULT_OLLAMA_BASE_URL
        if model_provider == "ollama":
            stage(6, total_steps, "Ollama Endpoint", subtitle="Tell AgentX where Ollama is running")
            ollama_base_url = _prompt_ollama_endpoint(platform_info=platform_info)
            probe = run_with_status("Checking Ollama reachability", probe_ollama_endpoint, ollama_base_url)
            if probe.status == "reachable":
                ui_success(f"Ollama check: {probe.message}")
            elif probe.status == "reachable_no_models":
                ui_warn(f"Ollama check: {probe.message}")
            else:
                ui_warn(f"Ollama warning: {probe.message}")
                for note in wsl_ollama_guidance(platform_info=platform_info, base_url=ollama_base_url):
                    ui_warn(note)

        api_host = _ask(
            PromptSpec(
                title="API Bind Address",
                prompt="Which address should the AgentX API listen on",
                default="127.0.0.1",
                help_text=(
                    "What this is:\n"
                    "- The network address the AgentX API listens on.\n"
                    "Why it matters:\n"
                    "- `127.0.0.1` keeps it local to this machine.\n"
                    "When to change it:\n"
                    "- Use `0.0.0.0` if you need other machines or containers to reach it."
                ),
            ),
            index=7,
            total=total_steps,
        )
        api_port = int(
            _ask(
                PromptSpec(
                    title="API Port",
                    prompt="Which port should the AgentX API use",
                    default="8420",
                    help_text=(
                        "What this is:\n"
                        "- The port used by AgentX's API.\n"
                        "Why it matters:\n"
                        "- The web UI and other clients connect here.\n"
                        "When to change it:\n"
                        "- Change it if port 8420 is already in use."
                    ),
                ),
            )
        )

        default_web = "yes" if profile in {InstallProfile.STANDARD, InstallProfile.DEVELOPER} else "no"
        web_enabled = _ask(
            PromptSpec(
                title="Web UI",
                prompt="Enable the web interface",
                default=default_web,
                help_text=(
                    "What this controls:\n"
                    "- Whether AgentX's browser-based UI is enabled.\n"
                    "Why it matters:\n"
                    "- The web UI gives you a graphical way to use AgentX.\n"
                    "When to change it:\n"
                    "- Disable it for server-only or terminal-only use."
                ),
            ),
            index=8,
            total=total_steps,
        ).lower() in {"y", "yes", "true", "1"}

        web_host = _ask(
            PromptSpec(
                title="Web Bind Address",
                prompt="Which address should the web UI listen on",
                default="127.0.0.1",
                help_text=(
                    "What this is:\n"
                    "- The network address used by the AgentX web UI server.\n"
                    "Why it matters:\n"
                    "- `127.0.0.1` keeps the UI local to this machine.\n"
                    "When to change it:\n"
                    "- Use `0.0.0.0` only if you want access from elsewhere."
                ),
            )
        )
        web_port = int(
            _ask(
                PromptSpec(
                    title="Web UI Port",
                    prompt="Which port should the web UI use",
                    default="5173",
                help_text=(
                    "What this is:\n"
                    "- The port used by the AgentX browser UI.\n"
                    "Why it matters:\n"
                    "- You will open the UI in a browser at this address.\n"
                    "When to change it:\n"
                    "- Change it if 5173 is already in use."
                ),
                )
            )
        )

        service_mode_raw = _ask(_service_prompt(), index=9, total=total_steps).lower()
        service_mode = ServiceMode.SYSTEMD_USER if service_mode_raw == ServiceMode.SYSTEMD_USER.value else ServiceMode.NONE

        cfg = build_install_config(
            app_root=app_root,
            runtime_root=runtime_root,
            working_dir=working_dir,
            profile=profile,
            model_provider=model_provider,
            ollama_base_url=ollama_base_url,
            api_host=api_host,
            api_port=api_port,
            web_host=web_host,
            web_port=web_port,
            web_enabled=web_enabled,
            service_mode=service_mode,
        )
        stage(10, total_steps, "Validation and Provisioning Readiness", subtitle="Review warnings before AgentX provisions its runtime")
        validation = validate_install_config(cfg)
        if validation.warnings:
            ui_warn("Review these warnings before continuing:")
            bullet_list(validation.warnings, style="warn")
        fatal_errors = fatal_bundle_validation_errors(validation.errors)
        if fatal_errors:
            failure_panel(
                "Invalid App Bundle",
                "AgentX setup cannot continue because the app bundle path is invalid.",
                guidance=fatal_errors + ["Fix the bundle path and re-run `agentx setup`."],
            )
            raise RuntimeError("Invalid AgentX bundle root. Re-run install-agentx.sh or repair the bootstrap launcher.")
        if validation.ok:
            subsection("Validation Summary", subtitle="Your install choices are ready for provisioning.")
            summary_panel(
                f"{BRAND_NAME} Setup Summary",
                [line for line in render_setup_summary(cfg).splitlines() if line.strip()],
                style="#5B8CFF",
            )
            summary_panel("Local Profile", [line for line in render_profile_summary(local_profile).splitlines() if line.strip()], style="#8A5BFF")
            next_steps_panel(
                "Next Stage",
                [
                    "Provision the managed runtime and write config files.",
                    "Run health checks before starting AgentX services.",
                ],
                notes=["You can restart setup later if you want to change these values."],
            )
            return cfg, install_cfg_path, local_profile
        ui_error("Please fix these setup errors before continuing:")
        bullet_list(validation.errors, style="error")
        spacer()
