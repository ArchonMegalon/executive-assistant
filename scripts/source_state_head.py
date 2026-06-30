#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path


GENERATED_ONLY_PREFIXES = (
    ".runtime/",
    ".codex-design/product/",
    ".codex-studio/published/",
    "ea/.runtime/",
    "scripts/verify_",
    "tests/",
)
GENERATED_ONLY_EXACT = {
    "scripts/source_state_head.py",
}
FALLBACK_SOURCE_DIR_EXCLUDES = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "data",
    "node_modules",
    "venv",
}
FALLBACK_SOURCE_SUFFIXES = {
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
FALLBACK_SOURCE_EXACT = {
    ".env.example",
    ".env.local.example",
    "Dockerfile",
    "Makefile",
}


def resolve_source_state_head(repo_root: Path, *, generated_only_prefixes: tuple[str, ...] = GENERATED_ONLY_PREFIXES) -> str:
    head = _git_stdout(repo_root, "rev-parse", "HEAD")
    if not head:
        return _read_git_head_from_files(repo_root)

    commits = [line.strip() for line in _git_stdout(repo_root, "rev-list", "--max-count=128", "HEAD").splitlines() if line.strip()]
    if not commits:
        return head

    for commit in commits:
        parent_line = _git_stdout(repo_root, "rev-list", "--parents", "-n", "1", commit)
        parts = [part.strip() for part in parent_line.split() if part.strip()]
        parents = parts[1:]
        if not parents:
            return commit
        changed = [line.strip() for line in _git_stdout(repo_root, "diff", "--name-only", f"{parents[0]}..{commit}").splitlines() if line.strip()]
        if not changed:
            return commit
        if any(not _is_generated_only_path(path, prefixes=generated_only_prefixes) for path in changed):
            return commit

    return commits[-1]


def resolve_source_tree_fingerprint(
    repo_root: Path,
    *,
    generated_only_prefixes: tuple[str, ...] = GENERATED_ONLY_PREFIXES,
) -> str:
    source_head = resolve_source_state_head(repo_root, generated_only_prefixes=generated_only_prefixes)
    if not source_head:
        return ""
    relpaths = [
        line.strip()
        for line in _git_stdout(repo_root, "ls-tree", "-r", "--name-only", source_head).splitlines()
        if line.strip()
    ]
    digest = hashlib.sha256()
    for relpath in sorted(relpaths):
        if _is_generated_only_path(relpath, prefixes=generated_only_prefixes):
            continue
        blob_id = _git_stdout(repo_root, "rev-parse", f"{source_head}:{relpath}")
        if not blob_id:
            continue
        digest.update(relpath.encode("utf-8"))
        digest.update(b"\0")
        digest.update(blob_id.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def resolve_source_worktree_fingerprint(
    repo_root: Path,
    *,
    generated_only_prefixes: tuple[str, ...] = GENERATED_ONLY_PREFIXES,
) -> str:
    relpaths = [
        line.strip()
        for line in _git_stdout(repo_root, "ls-files", "--cached", "--others", "--exclude-standard").splitlines()
        if line.strip()
    ]
    if not relpaths:
        relpaths = _fallback_source_relpaths(repo_root, generated_only_prefixes=generated_only_prefixes)
    if not relpaths:
        return ""

    digest = hashlib.sha256()
    included = 0
    for relpath in sorted(set(relpaths)):
        if _is_generated_only_path(relpath, prefixes=generated_only_prefixes):
            continue
        path = repo_root / relpath
        if not path.is_file():
            continue
        try:
            content_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        digest.update(relpath.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_digest.encode("utf-8"))
        digest.update(b"\0")
        included += 1
    return digest.hexdigest() if included else ""


def source_worktree_metadata(
    repo_root: Path,
    *,
    generated_only_prefixes: tuple[str, ...] = GENERATED_ONLY_PREFIXES,
    dirty_path_limit: int = 40,
) -> dict[str, object]:
    raw_status = _git_stdout_raw(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    source_entries: list[tuple[str, str]] = []
    for line in raw_status.splitlines():
        if not line.strip():
            continue
        status = (line[:2] or "").strip() or "changed"
        raw_path = line[3:].strip() if len(line) > 3 else line.strip()
        paths = _status_paths(raw_path)
        source_paths = [
            path
            for path in paths
            if path and not _is_generated_only_path(path, prefixes=generated_only_prefixes)
        ]
        if not source_paths:
            continue
        source_entries.append((status, source_paths[-1]))

    digest = hashlib.sha256()
    for status, path in sorted(source_entries, key=lambda item: (item[1], item[0])):
        digest.update(status.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")

    dirty_count = len(source_entries)
    dirty_files = [path for _status, path in sorted(source_entries, key=lambda item: (item[1], item[0]))]
    return {
        "source_worktree_dirty": dirty_count > 0,
        "source_dirty_count": dirty_count,
        "source_dirty_files": dirty_files[: max(dirty_path_limit, 0)],
        "source_dirty_omitted_count": max(dirty_count - max(dirty_path_limit, 0), 0),
        "source_dirty_status_sha256": digest.hexdigest() if dirty_count else "",
    }


def _git_stdout(repo_root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    return proc.stdout.strip()


def _git_stdout_raw(repo_root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    return proc.stdout


def _read_git_head_from_files(repo_root: Path) -> str:
    git_dir = _git_dir(repo_root)
    if git_dir is None:
        return ""
    try:
        head_text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if head_text.startswith("ref:"):
        ref_name = head_text.split(":", 1)[1].strip()
        if not ref_name:
            return ""
        try:
            ref_text = (git_dir / ref_name).read_text(encoding="utf-8").strip()
        except OSError:
            ref_text = _read_packed_ref(git_dir, ref_name)
        return _normalize_git_sha(ref_text)
    return _normalize_git_sha(head_text)


def _git_dir(repo_root: Path) -> Path | None:
    git_path = repo_root / ".git"
    if git_path.is_dir():
        return git_path
    if git_path.is_file():
        try:
            text = git_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if text.startswith("gitdir:"):
            raw = text.split(":", 1)[1].strip()
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = repo_root / candidate
            return candidate
    return None


def _read_packed_ref(git_dir: Path, ref_name: str) -> str:
    try:
        lines = (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "^")):
            continue
        parts = stripped.split()
        if len(parts) == 2 and parts[1] == ref_name:
            return parts[0]
    return ""


def _normalize_git_sha(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) == 40 and all(ch in "0123456789abcdef" for ch in normalized):
        return normalized
    return ""


def _fallback_source_relpaths(
    repo_root: Path,
    *,
    generated_only_prefixes: tuple[str, ...],
) -> list[str]:
    relpaths: list[str] = []
    for root, dirnames, filenames in os.walk(repo_root):
        current = Path(root)
        rel_dir = _safe_relative_posix(current, repo_root)
        kept_dirs: list[str] = []
        for dirname in dirnames:
            if dirname in FALLBACK_SOURCE_DIR_EXCLUDES:
                continue
            rel_candidate = f"{rel_dir}/{dirname}" if rel_dir else dirname
            if _is_generated_only_path(f"{rel_candidate}/", prefixes=generated_only_prefixes):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            path = current / filename
            relpath = _safe_relative_posix(path, repo_root)
            if not relpath:
                continue
            if _is_generated_only_path(relpath, prefixes=generated_only_prefixes):
                continue
            if not _fallback_source_file_allowed(relpath):
                continue
            relpaths.append(relpath)
    return sorted(set(relpaths))


def _safe_relative_posix(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return ""


def _fallback_source_file_allowed(relpath: str) -> bool:
    if relpath in FALLBACK_SOURCE_EXACT:
        return True
    name = Path(relpath).name
    if name in FALLBACK_SOURCE_EXACT:
        return True
    if name.startswith(".env") and name not in {".env.example", ".env.local.example"}:
        return False
    return Path(relpath).suffix.lower() in FALLBACK_SOURCE_SUFFIXES


def _is_generated_only_path(path: str, *, prefixes: tuple[str, ...]) -> bool:
    return path in GENERATED_ONLY_EXACT or any(path.startswith(prefix) for prefix in prefixes)


def _status_paths(raw_path: str) -> list[str]:
    if " -> " in raw_path:
        return [part.strip().strip('"') for part in raw_path.split(" -> ") if part.strip()]
    return [raw_path.strip().strip('"')]
