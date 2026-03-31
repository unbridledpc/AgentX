from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlatformInfo:
    system: str
    is_linux: bool
    is_wsl: bool
    wsl_version: str | None
    systemd_user_available: bool
    systemd_present_but_unusable: bool
    no_systemd: bool
    notes: tuple[str, ...]


def _systemctl_user_state() -> tuple[bool, bool]:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False, False
    try:
        proc = subprocess.run(
            [systemctl, "--user", "show-environment"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except OSError:
        return False, True
    return proc.returncode == 0, proc.returncode != 0


def detect_platform() -> PlatformInfo:
    system = platform.system().lower()
    release = platform.release().lower()
    version = platform.version().lower()
    proc_version = ""
    proc_path = Path("/proc/version")
    if proc_path.exists():
        try:
            proc_version = proc_path.read_text(encoding="utf-8", errors="replace").lower()
        except Exception:
            proc_version = ""
    env = {k.lower(): v.lower() for k, v in os.environ.items() if isinstance(v, str)}
    is_wsl = system == "linux" and ("microsoft" in release or "microsoft" in version or "microsoft" in proc_version or "wsl" in env.get("wsl_dist_name", "").lower())
    wsl_version = None
    if is_wsl:
        wsl_version = "2" if "wsl2" in proc_version or "wsl2" in release or "wsl2" in version else "1"
    systemd_user_available = False
    systemd_present_but_unusable = False
    no_systemd = True
    if system == "linux":
        systemd_user_available, systemd_present_but_unusable = _systemctl_user_state()
        no_systemd = not systemd_user_available and not systemd_present_but_unusable
    notes: list[str] = []
    if is_wsl:
        notes.append("WSL detected. Prefer runtime and working directories on the Linux filesystem, not under /mnt/*.")
        if not systemd_user_available:
            if systemd_present_but_unusable:
                notes.append("systemctl is present but systemd user services are not usable in this WSL environment.")
            else:
                notes.append("systemd user services do not appear active in this WSL environment.")
    elif system == "linux":
        notes.append("Linux environment detected.")
    if systemd_present_but_unusable:
        notes.append("systemctl --user is present but not usable in this environment.")
    if no_systemd and system == "linux":
        notes.append("systemctl is not available in this environment.")
    return PlatformInfo(
        system=system,
        is_linux=system == "linux",
        is_wsl=is_wsl,
        wsl_version=wsl_version,
        systemd_user_available=systemd_user_available,
        systemd_present_but_unusable=systemd_present_but_unusable,
        no_systemd=no_systemd,
        notes=tuple(notes),
    )
