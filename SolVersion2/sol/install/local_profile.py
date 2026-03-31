from __future__ import annotations

import getpass
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class LocalProfile:
    mode: str
    display_name: str
    profile_id: str
    os_username: str
    home_dir: Path
    memory_namespace: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["home_dir"] = str(self.home_dir)
        return data


@dataclass(frozen=True)
class LocalProfileSelection:
    mode: str
    display_name: str | None = None
    profile_id: str | None = None


def profile_config_path(runtime_root: Path) -> Path:
    return runtime_root.expanduser().resolve() / "config" / "profile.json"


def _os_username() -> str:
    for candidate in (
        os.environ.get("SOL_PROFILE_OS_USER"),
        os.environ.get("USER"),
        os.environ.get("USERNAME"),
    ):
        text = (candidate or "").strip()
        if text:
            return text
    try:
        text = (getpass.getuser() or "").strip()
        if text:
            return text
    except Exception:
        pass
    return "local-user"


def _display_name_from_username(username: str) -> str:
    cleaned = username.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned else "Local User"


def _safe_profile_id(value: str) -> str:
    lowered = (value or "").strip().lower()
    slug = _SLUG_RE.sub("-", lowered).strip("-.")
    return slug or "local-user"


def _memory_namespace(profile_id: str) -> str:
    return f"user.{_safe_profile_id(profile_id)}"


def build_local_profile(*, mode: str, display_name: str | None = None, profile_id: str | None = None) -> LocalProfile:
    username = _os_username()
    home_dir = Path.home().expanduser().resolve()
    resolved_display_name = (display_name or "").strip() or _display_name_from_username(username)
    base_profile_id = (profile_id or "").strip() or username or resolved_display_name
    resolved_profile_id = _safe_profile_id(base_profile_id)
    resolved_mode = "explicit" if (mode or "").strip().lower() == "explicit" else "os-fallback"
    return LocalProfile(
        mode=resolved_mode,
        display_name=resolved_display_name,
        profile_id=resolved_profile_id,
        os_username=username,
        home_dir=home_dir,
        memory_namespace=_memory_namespace(resolved_profile_id),
    )


def save_local_profile(runtime_root: Path, selection: LocalProfileSelection | None) -> Path:
    chosen = selection or LocalProfileSelection(mode="os-fallback")
    profile = build_local_profile(mode=chosen.mode, display_name=chosen.display_name, profile_id=chosen.profile_id)
    path = profile_config_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def resolve_local_profile(runtime_root: Path) -> LocalProfile:
    path = profile_config_path(runtime_root)
    if not path.exists():
        return build_local_profile(mode="os-fallback")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return build_local_profile(mode="os-fallback")
    return build_local_profile(
        mode=str(data.get("mode", "os-fallback")),
        display_name=str(data.get("display_name", "")).strip() or None,
        profile_id=str(data.get("profile_id", "")).strip() or None,
    )
