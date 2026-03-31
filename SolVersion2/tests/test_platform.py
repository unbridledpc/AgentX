from __future__ import annotations

from pathlib import Path

from sol.install import platform as platform_mod


def test_detect_platform_wsl(monkeypatch) -> None:
    monkeypatch.setattr(platform_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform_mod.platform, "release", lambda: "5.15.90.1-microsoft-standard-WSL2")
    monkeypatch.setattr(platform_mod.platform, "version", lambda: "test")
    monkeypatch.setattr(platform_mod, "Path", lambda p: Path(p))
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == "/proc/version")
    monkeypatch.setattr(Path, "read_text", lambda self, **kwargs: "Linux version 5.15 microsoft WSL2")
    monkeypatch.setenv("WSL_DIST_NAME", "Ubuntu")
    info = platform_mod.detect_platform()
    assert info.is_linux is True
    assert info.is_wsl is True
    assert info.wsl_version == "2"
