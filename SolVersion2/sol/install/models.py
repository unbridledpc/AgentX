from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class InstallProfile(str, Enum):
    CLI = "cli"
    STANDARD = "standard"
    SERVER = "server"
    DEVELOPER = "developer"


class ServiceMode(str, Enum):
    NONE = "none"
    SYSTEMD_USER = "systemd-user"
    SYSTEMD_SYSTEM = "systemd-system"


@dataclass(frozen=True)
class WebRuntimeConfig:
    enabled: bool
    host: str
    port: int
    open_browser: bool = False


@dataclass(frozen=True)
class ApiRuntimeConfig:
    enabled: bool
    host: str
    port: int


@dataclass(frozen=True)
class InstallConfig:
    schema_version: int
    install_name: str
    profile: InstallProfile
    service_mode: ServiceMode
    app_root: Path
    runtime_root: Path
    working_dir: Path
    config_path: Path
    model_provider: str
    ollama_base_url: str
    api: ApiRuntimeConfig
    web: WebRuntimeConfig

    def to_dict(self) -> dict:
        data = asdict(self)
        data["profile"] = self.profile.value
        data["service_mode"] = self.service_mode.value
        data["app_root"] = str(self.app_root)
        data["runtime_root"] = str(self.runtime_root)
        data["working_dir"] = str(self.working_dir)
        data["config_path"] = str(self.config_path)
        return data


@dataclass(frozen=True)
class InstallPaths:
    app_root: Path
    runtime_root: Path
    config_dir: Path
    config_path: Path
    extensions_dir: Path
    builtin_plugins_dir: Path
    runtime_plugins_dir: Path
    builtin_skills_dir: Path
    runtime_skills_dir: Path
    data_dir: Path
    memory_dir: Path
    logs_dir: Path
    audit_dir: Path
    cache_dir: Path
    temp_dir: Path
    run_dir: Path
    work_dir: Path
    plugins_state_dir: Path
    skills_state_dir: Path
    web_runtime_dir: Path
    api_data_dir: Path
    lifecycle_dir: Path
    runtime_bin_dir: Path
    web_config_path: Path
    api_pid_path: Path
    web_pid_path: Path
    api_log_path: Path
    web_log_path: Path
    profile_path: Path
    runtime_venv_dir: Path
    runtime_python_path: Path
    install_log_path: Path
    sol_launcher_path: Path
