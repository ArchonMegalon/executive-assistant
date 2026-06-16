#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path


GENERATED_ONLY_PREFIXES = (
    ".codex-design/product/",
    ".codex-studio/published/",
)


def resolve_source_state_head(repo_root: Path, *, generated_only_prefixes: tuple[str, ...] = GENERATED_ONLY_PREFIXES) -> str:
    head = _git_stdout(repo_root, "rev-parse", "HEAD")
    if not head:
        return ""

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


def _is_generated_only_path(path: str, *, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)
