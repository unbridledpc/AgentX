from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RELEASE_ROOT_FILES = (
    "install-sol.sh",
    "README.md",
    "LICENSE",
    "RELEASE.md",
)

RELEASE_ROOT_DIRS = (
    "SolVersion2",
    "SolWeb",
    "apps",
)

REQUIRED_PATHS = (
    "install-sol.sh",
    "SolVersion2/sol",
    "apps/api",
    "SolWeb",
    "SolWeb/dist/index.html",
)

REQUIRED_ARCHIVE_PATHS = (
    "install-sol.sh",
    "SolVersion2/sol/__init__.py",
    "apps/api/sol_api/__init__.py",
    "SolWeb/dist/index.html",
    "release-manifest.json",
)

FORBIDDEN_ARCHIVE_PREFIXES = (
    ".git/",
    ".venv/",
    "node_modules/",
    "SolVersion2/data/",
    "SolVersion2/logs/",
    "SolVersion2/tests/",
    "apps/api/tests/",
    "apps/api/sol_api/data/",
    "SolWeb/src/",
)

FORBIDDEN_ARCHIVE_CONTAINS = (
    "/.venv/",
    "/node_modules/",
    ".egg-info/",
)

EXCLUDED_DIR_NAMES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
}

EXCLUDED_EXACT_DIRS = {
    "SolVersion2/.venv",
    "SolVersion2/build",
    "SolVersion2/data",
    "SolVersion2/logs",
    "SolVersion2/solversion2.egg-info",
    "SolVersion2/tests",
    "apps/desktop",
    "apps/api/.venv",
    "apps/api/sol_api/data",
    "apps/api/tests",
    "SolWeb/src",
}

EXCLUDED_EXACT_FILES = {
    ".DS_Store",
    "Thumbs.db",
}

EXCLUDED_CONTAINS = (
    ".egg-info/",
)


class ReleasePackagingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseBuildResult:
    archive_path: Path
    manifest_path: Path
    checksum_path: Path
    version: str
    sha256: str
    file_count: int
    total_size: int
    warnings: tuple[str, ...]


def _normalize(path: Path) -> str:
    return path.as_posix().strip("/")


def discover_version(repo_root: Path) -> str:
    version_path = repo_root / "SolVersion2" / "sol" / "version.py"
    if not version_path.exists():
        raise ReleasePackagingError(f"Missing version source: {version_path}")
    namespace: dict[str, Any] = {}
    exec(version_path.read_text(encoding="utf-8"), namespace)
    version = str(namespace.get("__version__") or "").strip()
    if not version:
        raise ReleasePackagingError(f"Unable to discover __version__ from {version_path}")
    return version


def _default_archive_name(version: str) -> str:
    return f"nexai-{version}.zip"


def _relative_paths(repo_root: Path) -> list[Path]:
    entries: list[Path] = []
    for root_name in RELEASE_ROOT_FILES:
        candidate = repo_root / root_name
        if candidate.is_file():
            entries.append(candidate.relative_to(repo_root))
    for root_name in RELEASE_ROOT_DIRS:
        candidate = repo_root / root_name
        if not candidate.exists():
            continue
        for current_root, dir_names, file_names in os.walk(candidate, topdown=True):
            current_path = Path(current_root)
            rel_root = current_path.relative_to(repo_root)
            kept_dirs: list[str] = []
            for dir_name in sorted(dir_names):
                rel_dir = rel_root / dir_name
                if should_exclude(rel_dir, is_dir=True):
                    continue
                kept_dirs.append(dir_name)
                entries.append(rel_dir)
            dir_names[:] = kept_dirs
            for file_name in sorted(file_names):
                rel_file = rel_root / file_name
                if should_exclude(rel_file, is_dir=False):
                    continue
                entries.append(rel_file)
    return sorted({p for p in entries if p})


def should_exclude(rel_path: Path, *, is_dir: bool) -> bool:
    normalized = _normalize(rel_path)
    name = rel_path.name
    if not normalized:
        return False
    if normalized in EXCLUDED_EXACT_DIRS:
        return True
    if any(normalized.startswith(prefix + "/") for prefix in EXCLUDED_EXACT_DIRS):
        return True
    if name in EXCLUDED_EXACT_FILES:
        return True
    if any(token in f"{normalized}/" for token in EXCLUDED_CONTAINS):
        return True
    if is_dir and name in EXCLUDED_DIR_NAMES:
        if normalized == "SolWeb/dist":
            return False
        return True
    if any(part in EXCLUDED_DIR_NAMES for part in rel_path.parts):
        if normalized.startswith("SolWeb/dist/") or normalized == "SolWeb/dist":
            return False
        return True
    if rel_path.suffix in EXCLUDED_SUFFIXES:
        return True
    return False


def validate_repo_layout(repo_root: Path) -> None:
    missing = [item for item in REQUIRED_PATHS if not (repo_root / item).exists()]
    if missing:
        raise ReleasePackagingError(f"Missing required release paths: {', '.join(missing)}")


def collect_release_files(repo_root: Path) -> list[Path]:
    validate_repo_layout(repo_root)
    files = [path for path in _relative_paths(repo_root) if (repo_root / path).is_file()]
    if not files:
        raise ReleasePackagingError("Release packaging found no files to include.")
    return files


def _build_warnings(repo_root: Path) -> list[str]:
    warnings: list[str] = []
    dist_index = repo_root / "SolWeb" / "dist" / "index.html"
    src_root = repo_root / "SolWeb" / "src"
    if dist_index.exists() and src_root.exists():
        newest_src = max((path.stat().st_mtime for path in src_root.rglob("*") if path.is_file()), default=0.0)
        if newest_src and dist_index.stat().st_mtime < newest_src:
            warnings.append("SolWeb/dist appears older than SolWeb/src. Rebuild the frontend before shipping if needed.")
    return warnings


def _compile_python_files(release_root: Path) -> None:
    for path in sorted(release_root.rglob("*.py")):
        py_compile.compile(str(path), doraise=True)


def _manifest_payload(
    *,
    version: str,
    archive_name: str,
    sha256: str | None,
    file_count: int,
    total_size: int,
    warnings: list[str],
    files: list[str],
) -> dict[str, Any]:
    return {
        "version": version,
        "archive_name": archive_name,
        "sha256": sha256,
        "file_count": file_count,
        "total_size": total_size,
        "included_roots": list(RELEASE_ROOT_DIRS),
        "excluded_categories": [
            ".git",
            "virtualenvs",
            "node_modules",
            "pytest caches",
            "python caches",
            "egg-info",
            "runtime data/logs",
            "editor junk",
            "os junk",
            "tests",
            "frontend source",
        ],
        "warnings": warnings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_format": "zip",
        "files": files,
    }


def build_release_tree(repo_root: Path, release_root: Path, *, version: str, archive_name: str) -> dict[str, Any]:
    files = collect_release_files(repo_root)
    total_size = 0
    for rel_path in files:
        src = repo_root / rel_path
        dst = release_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        total_size += src.stat().st_size
    _compile_python_files(release_root)
    manifest = _manifest_payload(
        version=version,
        archive_name=archive_name,
        sha256=None,
        file_count=len(files),
        total_size=total_size,
        warnings=_build_warnings(repo_root),
        files=[path.as_posix() for path in files],
    )
    return manifest


def _write_manifest(target_path: Path, manifest: dict[str, Any]) -> Path:
    target_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target_path


def _zip_write_deterministic(archive: zipfile.ZipFile, path: Path, arcname: str) -> None:
    info = zipfile.ZipInfo(arcname)
    info.date_time = (2020, 1, 1, 0, 0, 0)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    data = path.read_bytes()
    archive.writestr(info, data)


def create_release_archive(release_root: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as archive:
        for path in sorted(release_root.rglob("*")):
            if not path.is_file():
                continue
            _zip_write_deterministic(archive, path, path.relative_to(release_root).as_posix())
    return output_path


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sha256_file(archive_path: Path, sha256_hex: str) -> Path:
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{sha256_hex}  {archive_path.name}\n", encoding="utf-8")
    return checksum_path


def validate_archive(archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        missing = [name for name in REQUIRED_ARCHIVE_PATHS if name not in names]
        if missing:
            raise ReleasePackagingError(f"Archive missing required paths: {', '.join(missing)}")
        forbidden: list[str] = []
        for name in names:
            if name.startswith(FORBIDDEN_ARCHIVE_PREFIXES):
                forbidden.append(name)
                continue
            if any(token in name for token in FORBIDDEN_ARCHIVE_CONTAINS):
                forbidden.append(name)
        if forbidden:
            preview = ", ".join(sorted(forbidden)[:10])
            raise ReleasePackagingError(f"Archive contains forbidden content: {preview}")


def package_release(repo_root: Path, output_dir: Path, *, archive_name: str | None = None) -> ReleaseBuildResult:
    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    version = discover_version(repo_root)
    resolved_archive_name = archive_name or _default_archive_name(version)
    with tempfile.TemporaryDirectory(prefix="nexai-release-") as tmp_dir:
        release_root = Path(tmp_dir) / "nexai-release"
        release_root.mkdir(parents=True, exist_ok=True)
        manifest = build_release_tree(repo_root, release_root, version=version, archive_name=resolved_archive_name)
        _write_manifest(release_root / "release-manifest.json", manifest)
        archive_path = create_release_archive(release_root, output_dir / resolved_archive_name)
        validate_archive(archive_path)
        sha256_hex = compute_sha256(archive_path)
        final_manifest = _manifest_payload(
            version=version,
            archive_name=resolved_archive_name,
            sha256=sha256_hex,
            file_count=int(manifest["file_count"]),
            total_size=int(manifest["total_size"]),
            warnings=[str(item) for item in manifest.get("warnings", [])],
            files=[str(item) for item in manifest.get("files", [])],
        )
        manifest_path = _write_manifest(output_dir / "release-manifest.json", final_manifest)
        checksum_path = write_sha256_file(archive_path, sha256_hex)
        return ReleaseBuildResult(
            archive_path=archive_path,
            manifest_path=manifest_path,
            checksum_path=checksum_path,
            version=version,
            sha256=sha256_hex,
            file_count=int(final_manifest["file_count"]),
            total_size=int(final_manifest["total_size"]),
            warnings=tuple(str(item) for item in final_manifest.get("warnings", [])),
        )


def _print_report(result: ReleaseBuildResult) -> None:
    print("Release Packaging Summary")
    print(f"Output: {result.archive_path}")
    print(f"Version: {result.version}")
    print(f"SHA256: {result.sha256}")
    print(f"Files: {result.file_count}")
    print(f"Total size: {result.total_size} bytes")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a clean deterministic NexAI release archive.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]), help="Repository root")
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[1] / "dist"), help="Directory for the final archive")
    parser.add_argument("--archive-name", default=None, help="Output archive filename")
    args = parser.parse_args(argv)
    result = package_release(Path(args.repo_root), Path(args.output_dir), archive_name=args.archive_name)
    _print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
