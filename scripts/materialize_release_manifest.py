from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "release_manifest.generated.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _artifacts() -> list[str]:
    published_root = ROOT / ".codex-studio" / "published"
    if not published_root.is_dir():
        return []
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in published_root.rglob("*")
        if path.is_file()
    )


def build_manifest(*, output_path: Path = DEFAULT_OUTPUT, generated_at: str | None = None) -> dict[str, object]:
    remote_origin = _git("remote", "get-url", "origin")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    commit_sha = _git("rev-parse", "HEAD")
    release_label = str(
        os.environ.get("EA_RELEASE_LABEL")
        or os.environ.get("RELEASE_LABEL")
        or (commit_sha[:12] if commit_sha else "")
    ).strip()
    deployment_id = str(
        os.environ.get("EA_DEPLOYMENT_ID")
        or os.environ.get("DEPLOYMENT_ID")
        or os.environ.get("RENDER_GIT_COMMIT")
        or ""
    ).strip()
    manifest = {
        "contract_name": "ea.release_manifest.v1",
        "generated_at": generated_at or _now_iso(),
        "generated_by": "scripts/materialize_release_manifest.py",
        "repository": ROOT.name,
        "branch": branch,
        "commit_sha": commit_sha,
        "deployment_id": deployment_id,
        "public_origin": remote_origin,
        "artifact_set": _artifacts(),
        "release_label": release_label,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "--out", dest="output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    manifest = build_manifest(output_path=args.output)
    if args.pretty:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
