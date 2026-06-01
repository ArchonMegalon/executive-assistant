#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_ARTIFACTS = (
    Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"),
    Path(".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"),
    Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"),
)
VOLATILE_KEYS = {
    "generated_at",
    "as_of",
    "created_at",
    "mtime_utc",
    "size_bytes",
    "sha256",
    "duration_seconds",
    "git_branch",
    "git_head",
    "source_path",
    "resolved_path",
    "git_repo_root",
    "command",
    "cwd",
    "output_excerpt",
    "python_bin",
    "review_due",
}


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in VOLATILE_KEYS or str(key).endswith("_git_head"):
                continue
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _load_worktree(path: Path) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _load_head(path: Path) -> Any:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{path.as_posix()}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    failures: list[str] = []
    semantically_clean: list[Path] = []
    for path in GENERATED_ARTIFACTS:
        try:
            head_payload = _load_head(path)
            worktree_payload = _load_worktree(path)
        except Exception as exc:
            failures.append(f"{path}: unable to load generated artifact: {exc}")
            continue
        if _normalize(head_payload) != _normalize(worktree_payload):
            failures.append(f"{path}: semantic drift after materialization")
        else:
            semantically_clean.append(path)

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    subprocess.run(
        ["git", "-C", str(ROOT), "restore", "--", *(path.as_posix() for path in semantically_clean)],
        check=True,
    )
    print("generated release artifacts are semantically clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
