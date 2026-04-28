from __future__ import annotations

import importlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from agentx.install.models import InstallConfig, InstallProfile


@dataclass(frozen=True)
class DependencySpec:
    module: str
    package: str
    service: str


API_RUNTIME_DEPENDENCIES: tuple[DependencySpec, ...] = (
    DependencySpec(module="uvicorn", package="uvicorn[standard]>=0.27", service="api"),
    DependencySpec(module="fastapi", package="fastapi>=0.110", service="api"),
    DependencySpec(module="pydantic", package="pydantic>=2.6", service="api"),
)

DEVELOPER_EXTRA_DEPENDENCIES: tuple[DependencySpec, ...] = (
    DependencySpec(module="pytest", package="pytest>=8.0", service="developer"),
)


PROFILE_EXTRAS: dict[InstallProfile, str] = {
    InstallProfile.CLI: "cli",
    InstallProfile.SERVER: "server",
    InstallProfile.STANDARD: "standard",
    InstallProfile.DEVELOPER: "developer",
}


def profile_dependency_specs(config: InstallConfig) -> tuple[DependencySpec, ...]:
    specs: list[DependencySpec] = []
    if bool(config.api.enabled):
        specs.extend(API_RUNTIME_DEPENDENCIES)
    if config.profile == InstallProfile.DEVELOPER:
        specs.extend(DEVELOPER_EXTRA_DEPENDENCIES)
    return tuple(specs)


def profile_extra_name(config: InstallConfig) -> str:
    return PROFILE_EXTRAS[config.profile]


def required_dependency_packages(config: InstallConfig) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for spec in profile_dependency_specs(config):
        if spec.package in seen:
            continue
        seen.add(spec.package)
        out.append(spec.package)
    return tuple(out)


def install_target_for_config(config: InstallConfig) -> str:
    extra = profile_extra_name(config)
    return f"{config.app_root / 'AgentX'}[{extra}]"


def _dependency_report_current(config: InstallConfig) -> list[dict[str, str | bool]]:
    report: list[dict[str, str | bool]] = []
    for spec in profile_dependency_specs(config):
        try:
            importlib.import_module(spec.module)
            report.append({"module": spec.module, "package": spec.package, "service": spec.service, "ok": True})
        except ModuleNotFoundError as e:
            missing_module = str(getattr(e, "name", "") or spec.module)
            report.append(
                {
                    "module": spec.module,
                    "package": spec.package,
                    "service": spec.service,
                    "ok": False,
                    "missing_module": missing_module,
                    "error": str(e),
                }
            )
        except Exception as e:
            report.append(
                {
                    "module": spec.module,
                    "package": spec.package,
                    "service": spec.service,
                    "ok": False,
                    "missing_module": spec.module,
                    "error": str(e),
                }
            )
    return report


def dependency_report(config: InstallConfig, *, python_executable: str | Path | None = None) -> list[dict[str, str | bool]]:
    if python_executable is None:
        return _dependency_report_current(config)
    py = Path(python_executable)
    if not py.exists():
        return [
            {
                "module": spec.module,
                "package": spec.package,
                "service": spec.service,
                "ok": False,
                "missing_module": spec.module,
                "error": f"Python interpreter not found: {py}",
            }
            for spec in profile_dependency_specs(config)
        ]
    payload = json.dumps(
        [{"module": spec.module, "package": spec.package, "service": spec.service} for spec in profile_dependency_specs(config)],
        ensure_ascii=False,
    )
    script = (
        "import importlib, json, sys\n"
        "specs = json.loads(sys.argv[1])\n"
        "out = []\n"
        "for spec in specs:\n"
        "    try:\n"
        "        importlib.import_module(spec['module'])\n"
        "        out.append({'module': spec['module'], 'package': spec['package'], 'service': spec['service'], 'ok': True})\n"
        "    except ModuleNotFoundError as e:\n"
        "        out.append({'module': spec['module'], 'package': spec['package'], 'service': spec['service'], 'ok': False, 'missing_module': getattr(e, 'name', '') or spec['module'], 'error': str(e)})\n"
        "    except Exception as e:\n"
        "        out.append({'module': spec['module'], 'package': spec['package'], 'service': spec['service'], 'ok': False, 'missing_module': spec['module'], 'error': str(e)})\n"
        "print(json.dumps(out, ensure_ascii=False))\n"
    )
    try:
        proc = subprocess.run(
            [str(py), "-c", script, payload],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return json.loads(proc.stdout or "[]")
    except Exception as e:
        return [
            {
                "module": spec.module,
                "package": spec.package,
                "service": spec.service,
                "ok": False,
                "missing_module": spec.module,
                "error": f"Dependency check failed via {py}: {e}",
            }
            for spec in profile_dependency_specs(config)
        ]


def missing_dependency_messages(config: InstallConfig, *, python_executable: str | Path | None = None) -> list[str]:
    messages: list[str] = []
    for item in dependency_report(config, python_executable=python_executable):
        if bool(item["ok"]):
            continue
        missing_module = str(item.get("missing_module") or item["module"])
        messages.append(
            f"Missing dependency for {item['service']}: module `{missing_module}` is not importable. Install `{item['package']}`."
        )
    return messages
