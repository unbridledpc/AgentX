from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest


def _load_package_release_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "package_release.py"
    spec = importlib.util.spec_from_file_location("package_release", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load package_release.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _write(repo / "install-sol.sh", "#!/usr/bin/env bash\n")
    _write(repo / "README.md", "readme\n")
    _write(repo / "LICENSE", "license\n")
    _write(repo / "RELEASE.md", "release\n")
    _write(repo / "SolVersion2" / "pyproject.toml", '[project]\nname="solversion2"\ndynamic=["version"]\n[tool.setuptools.dynamic]\nversion = {attr = "sol.version.__version__"}\n')
    _write(repo / "SolVersion2" / "MANIFEST.in", "graft sol\n")
    _write(repo / "SolVersion2" / "sol" / "__init__.py", "from sol.version import __version__\n")
    _write(repo / "SolVersion2" / "sol" / "version.py", '__version__ = "1.2.3"\n')
    _write(repo / "apps" / "api" / "requirements.txt", "fastapi\n")
    _write(repo / "apps" / "api" / "sol_api" / "__init__.py", "")
    _write(repo / "apps" / "api" / "sol_api" / "data" / "settings.json", "{}\n")
    _write(repo / "apps" / "desktop" / "package.json", '{"name":"desktop"}')
    _write(repo / "SolWeb" / "package.json", '{"name":"solweb","private":true}')
    _write(repo / "SolWeb" / "src" / "main.tsx", "console.log('ok');\n")
    _write(repo / "SolWeb" / "dist" / "index.html", "<html></html>\n")
    _write(repo / "SolWeb" / "dist" / "assets" / "index.js", "console.log('dist');\n")

    _write(repo / ".git" / "config", "git\n")
    _write(repo / "SolVersion2" / ".venv" / "pyvenv.cfg", "venv\n")
    _write(repo / "apps" / "api" / ".venv" / "pyvenv.cfg", "venv\n")
    _write(repo / "SolWeb" / "node_modules" / "pkg" / "index.js", "node\n")
    _write(repo / "SolVersion2" / "data" / "runtime.db", "data\n")
    _write(repo / "SolVersion2" / "logs" / "install.log", "log\n")
    _write(repo / "SolVersion2" / "tests" / "test_anything.py", "def test_nope(): pass\n")
    _write(repo / ".vscode" / "settings.json", "{}\n")
    _write(repo / "SolVersion2" / "solversion2.egg-info" / "PKG-INFO", "pkg\n")
    _write(repo / "SolVersion2" / "sol" / "__pycache__" / "x.pyc", "pyc\n")
    return repo


def test_version_is_discovered_from_canonical_source(tmp_path: Path) -> None:
    module = _load_package_release_module()
    repo = _make_repo(tmp_path)
    assert module.discover_version(repo) == "1.2.3"


def test_collect_release_files_excludes_local_artifacts(tmp_path: Path) -> None:
    module = _load_package_release_module()
    repo = _make_repo(tmp_path)
    files = [path.as_posix() for path in module.collect_release_files(repo)]
    assert "install-sol.sh" in files
    assert "SolVersion2/sol/__init__.py" in files
    assert "SolVersion2/sol/version.py" in files
    assert "apps/api/sol_api/__init__.py" in files
    assert "SolWeb/dist/index.html" in files
    assert "apps/desktop/package.json" not in files
    assert "SolWeb/src/main.tsx" not in files
    assert ".git/config" not in files
    assert "SolVersion2/.venv/pyvenv.cfg" not in files
    assert "apps/api/.venv/pyvenv.cfg" not in files
    assert "SolWeb/node_modules/pkg/index.js" not in files
    assert "apps/api/sol_api/data/settings.json" not in files
    assert "SolVersion2/data/runtime.db" not in files
    assert "SolVersion2/logs/install.log" not in files
    assert "SolVersion2/tests/test_anything.py" not in files


def test_package_release_fails_when_required_root_missing(tmp_path: Path) -> None:
    module = _load_package_release_module()
    repo = _make_repo(tmp_path)
    (repo / "SolWeb" / "dist" / "index.html").unlink()
    with pytest.raises(module.ReleasePackagingError, match="Missing required release paths"):
        module.package_release(repo, repo / "dist")


def test_default_archive_name_includes_version_and_writes_checksum(tmp_path: Path) -> None:
    module = _load_package_release_module()
    repo = _make_repo(tmp_path)
    result = module.package_release(repo, repo / "dist")
    assert result.archive_path.name == "nexai-1.2.3.zip"
    assert result.checksum_path.name == "nexai-1.2.3.zip.sha256"
    assert result.checksum_path.exists()
    checksum_text = result.checksum_path.read_text(encoding="utf-8")
    assert result.sha256 in checksum_text
    assert "nexai-1.2.3.zip" in checksum_text


def test_manifest_includes_version_and_sha256(tmp_path: Path) -> None:
    module = _load_package_release_module()
    repo = _make_repo(tmp_path)
    result = module.package_release(repo, repo / "dist")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == "1.2.3"
    assert manifest["archive_name"] == "nexai-1.2.3.zip"
    assert manifest["sha256"] == result.sha256
    assert manifest["package_format"] == "zip"
    assert manifest["generated_at"]


def test_validate_archive_catches_forbidden_content(tmp_path: Path) -> None:
    module = _load_package_release_module()
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("install-sol.sh", "")
        archive.writestr("SolVersion2/sol/__init__.py", "")
        archive.writestr("apps/api/sol_api/__init__.py", "")
        archive.writestr("SolWeb/dist/index.html", "")
        archive.writestr("release-manifest.json", "{}")
        archive.writestr(".git/config", "git")
    with pytest.raises(module.ReleasePackagingError, match="forbidden content"):
        module.validate_archive(archive_path)


def test_package_release_creates_expected_archive_layout(tmp_path: Path) -> None:
    module = _load_package_release_module()
    repo = _make_repo(tmp_path)
    result = module.package_release(repo, repo / "dist")
    assert result.archive_path.exists()
    with zipfile.ZipFile(result.archive_path, "r") as archive:
        names = set(archive.namelist())
        assert "install-sol.sh" in names
        assert "SolVersion2/sol/__init__.py" in names
        assert "SolVersion2/sol/version.py" in names
        assert "apps/api/sol_api/__init__.py" in names
        assert "SolWeb/dist/index.html" in names
        assert "release-manifest.json" in names
        assert "apps/desktop/package.json" not in names
        assert "SolWeb/src/main.tsx" not in names
        assert ".git/config" not in names
        assert "SolVersion2/.venv/pyvenv.cfg" not in names
        assert "apps/api/sol_api/data/settings.json" not in names
        assert "SolVersion2/data/runtime.db" not in names
        assert "SolVersion2/logs/install.log" not in names
