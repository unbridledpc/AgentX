from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sol.config import SolConfig
from sol.core.fs_policy import ValidatedPath, validate_path


class JournalError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _read_limited(path: Path, max_bytes: int) -> bytes:
    size = path.stat().st_size
    if size > max_bytes:
        # Read only a prefix for hashing/diff. We still capture hash of prefix to be explicit.
        with path.open("rb") as fh:
            return fh.read(max_bytes)
    return path.read_bytes()


def _safe_text(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")


def _is_probably_text(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext in {".txt", ".md", ".py", ".json", ".toml", ".yaml", ".yml", ".ini", ".log", ".csv", ".ts", ".tsx", ".js", ".html", ".css"}


@dataclass(frozen=True)
class JournalPaths:
    journal_path: Path
    rollback_dir: Path


class Journal:
    """Journals all file modifications and stores rollback artifacts."""

    def __init__(self, cfg: SolConfig):
        data_dir = cfg.paths.data_dir
        journal_dir = data_dir / "journal"
        rollback_dir = data_dir / "rollback"
        journal_dir.mkdir(parents=True, exist_ok=True)
        rollback_dir.mkdir(parents=True, exist_ok=True)
        self.paths = JournalPaths(journal_path=journal_dir / "ops.jsonl", rollback_dir=rollback_dir)
        self.cfg = cfg

    def _append(self, rec: dict[str, Any]) -> None:
        line = json.dumps(rec, ensure_ascii=False)
        self.paths.journal_path.open("a", encoding="utf-8").write(line + "\n")

    def record_write(
        self,
        *,
        target: str | Path,
        new_text: str,
        reason: str,
    ) -> dict[str, Any]:
        vp = validate_path(target, cfg=self.cfg, for_write=True)
        path = vp.path
        ts = time.time()
        before_bytes = b""
        before_hash = None
        backup_path = None
        diff_text = None

        # Preflight overwrite detection: use os.path.exists (and islink) before writing so overwrites
        # are reliably identified even when Path.exists() may behave unexpectedly for links/junctions.
        exists_before = bool(os.path.exists(str(path)) or os.path.islink(str(path)))
        if exists_before:
            before_bytes = _read_limited(path, self.cfg.fs.max_read_bytes)
            before_hash = _sha256_bytes(before_bytes)
            backup_path = self._backup_file(path, tag="write", ts=ts)

        data = (new_text or "").encode("utf-8")
        if len(data) > self.cfg.fs.max_write_bytes:
            raise JournalError(f"Write too large ({len(data)} bytes), max={self.cfg.fs.max_write_bytes}.")

        # Compute diff if text and small enough.
        if exists_before and _is_probably_text(path):
            before_s = _safe_text(before_bytes).splitlines(keepends=True)
            after_s = (new_text or "").splitlines(keepends=True)
            diff_text = "".join(difflib.unified_diff(before_s, after_s, fromfile=str(path), tofile=str(path)))
            if len(diff_text) > 200_000:
                diff_text = diff_text[:200_000] + "\n...diff truncated...\n"

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        after_hash = _sha256_bytes(_read_limited(path, self.cfg.fs.max_read_bytes))

        rec = {
            "ts": ts,
            "op": "write_text",
            "path": str(path),
            "reason": reason,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "backup_path": str(backup_path) if backup_path else None,
            "diff": diff_text,
        }
        self._append(rec)
        return rec

    def record_delete(self, *, target: str | Path, reason: str) -> dict[str, Any]:
        vp = validate_path(target, cfg=self.cfg, for_write=True)
        path = vp.path
        ts = time.time()
        if not path.exists():
            raise JournalError("Path not found.")

        backup_path = self._backup_file(path, tag="delete", ts=ts, include_dirs=True)

        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

        rec = {
            "ts": ts,
            "op": "delete",
            "path": str(path),
            "reason": reason,
            "backup_path": str(backup_path) if backup_path else None,
        }
        self._append(rec)
        return rec

    def record_move(self, *, src: str | Path, dst: str | Path, reason: str, overwrite: bool = False) -> dict[str, Any]:
        vsrc = validate_path(src, cfg=self.cfg, for_write=True)
        vdst = validate_path(dst, cfg=self.cfg, for_write=True)
        src_p = vsrc.path
        dst_p = vdst.path
        ts = time.time()

        if not src_p.exists():
            raise JournalError("Source not found.")
        if dst_p.exists() and not overwrite:
            raise JournalError("Destination exists (overwrite=false).")

        backup_path = None
        if dst_p.exists():
            backup_path = self._backup_file(dst_p, tag="move_overwrite", ts=ts, include_dirs=True)

        dst_p.parent.mkdir(parents=True, exist_ok=True)
        src_p.replace(dst_p)

        rec = {
            "ts": ts,
            "op": "move",
            "src": str(src_p),
            "dst": str(dst_p),
            "reason": reason,
            "backup_path": str(backup_path) if backup_path else None,
        }
        self._append(rec)
        return rec

    def _backup_file(self, path: Path, *, tag: str, ts: float, include_dirs: bool = False) -> Path | None:
        name = path.name
        stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(ts))
        safe_tag = "".join(ch for ch in tag if ch.isalnum() or ch in ("-", "_")) or "op"
        base = f"{stamp}_{safe_tag}_{name}"

        try:
            if path.is_dir():
                if not include_dirs:
                    return None
                out = self.paths.rollback_dir / f"{base}.zip"
                # make_archive wants basename without extension.
                tmp_base = self.paths.rollback_dir / f"{base}"
                shutil.make_archive(str(tmp_base), "zip", root_dir=str(path))
                tmp_zip = tmp_base.with_suffix(".zip")
                if tmp_zip.exists() and tmp_zip != out:
                    tmp_zip.replace(out)
                return out
            out = self.paths.rollback_dir / base
            shutil.copy2(path, out)
            return out
        except Exception:
            return None
