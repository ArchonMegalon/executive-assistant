#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
import subprocess  # nosec B404
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "deploy_context.generated.json"
DEFAULT_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml")
_ENV_FILE_CACHE: dict[Path, dict[str, str]] = {}


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _first_nonempty(*values: str) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _env_file_values(root: Path | None = None) -> dict[str, str]:
    resolved_root = root or ROOT
    cached = _ENV_FILE_CACHE.get(resolved_root)
    if cached is not None:
        return cached
    values: dict[str, str] = {}
    env_path = resolved_root / ".env"
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            normalized_key = str(key).strip()
            if normalized_key:
                values[normalized_key] = str(value).strip()
    _ENV_FILE_CACHE[resolved_root] = values
    return values


def _env_value(name: str, *, root: Path | None = None) -> str:
    resolved_root = root or ROOT
    value = str(os.environ.get(name) or "").strip()
    if value:
        return value
    return str(_env_file_values(resolved_root).get(name) or "").strip()


def _git(*args: str) -> str:
    completed = subprocess.run(  # nosec B603,B607
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _tracking_branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")


def _public_origin() -> tuple[str, str]:
    for env_name in (
        "EA_DEPLOY_PUBLIC_ORIGIN",
        "EA_PUBLIC_APP_BASE_URL",
        "PROPERTYQUARRY_PUBLIC_BASE_URL",
        "EA_PUBLIC_ORIGIN",
        "PUBLIC_ORIGIN",
    ):
        value = _env_value(env_name).rstrip("/")
        if value:
            return value, env_name
    return "", ""


def _deployment_identity(*, generated_at: str | None = None, commit_sha: str = "") -> tuple[str, str]:
    explicit_source = str(os.environ.get("EA_DEPLOYMENT_ID_SOURCE") or "").strip()
    deployment_id = _first_nonempty(
        str(os.environ.get("EA_DEPLOYMENT_ID") or ""),
        str(os.environ.get("DEPLOYMENT_ID") or ""),
        str(os.environ.get("RENDER_GIT_COMMIT") or ""),
    )
    if explicit_source:
        return deployment_id, explicit_source
    if str(os.environ.get("EA_DEPLOYMENT_ID") or "").strip():
        return deployment_id, "ea_deploy_id_env"
    if str(os.environ.get("DEPLOYMENT_ID") or "").strip():
        return deployment_id, "deploy_platform"
    if str(os.environ.get("RENDER_GIT_COMMIT") or "").strip():
        return deployment_id, "render_git_commit"
    stamp = str(generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")).replace(":", "").replace("-", "").replace(".", "")
    commit_fragment = (str(commit_sha or "").strip()[:12] or "unknowncommit")
    return f"local-{stamp}-{commit_fragment}", "local_fallback"


def build_deploy_context(*, output_path: Path = DEFAULT_OUTPUT, generated_at: str | None = None) -> dict[str, Any]:
    branch = _first_nonempty(
        str(os.environ.get("EA_DEPLOY_BRANCH") or ""),
        _git("rev-parse", "--abbrev-ref", "HEAD"),
    )
    tracking_branch = _first_nonempty(
        str(os.environ.get("EA_DEPLOY_TRACKING_BRANCH") or ""),
        _tracking_branch(),
    )
    commit_sha = _first_nonempty(
        str(os.environ.get("EA_DEPLOY_COMMIT_SHA") or ""),
        _git("rev-parse", "HEAD"),
    )
    normalized_generated_at = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    deployment_id, deployment_id_source = _deployment_identity(generated_at=normalized_generated_at, commit_sha=commit_sha)
    public_origin, public_origin_source = _public_origin()
    project_mode = _first_nonempty(
        str(os.environ.get("EA_DEPLOY_PRIMARY_MODE") or ""),
        _env_value("EA_DEPLOY_PRIMARY_MODE"),
        _env_value("EA_DEPLOY_PROJECT_MODE"),
        "EA_CORE",
    )
    enabled_project_modes = _split_csv(
        _first_nonempty(
            str(os.environ.get("EA_DEPLOY_ENABLED_MODES") or ""),
            _env_value("EA_DEPLOY_ENABLED_MODES"),
            _env_value("EA_DEPLOY_ENABLED_PROJECT_MODES"),
            project_mode,
        )
    )
    compose_files = _split_csv(
        _first_nonempty(
            str(os.environ.get("EA_DEPLOY_COMPOSE_FILES") or ""),
            _env_value("EA_DEPLOY_COMPOSE_FILES"),
            ",".join(DEFAULT_COMPOSE_FILES),
        )
    )
    compose_overrides = _split_csv(
        _first_nonempty(
            str(os.environ.get("EA_DEPLOY_COMPOSE_OVERRIDES") or ""),
            _env_value("EA_DEPLOY_COMPOSE_OVERRIDES"),
        )
    )
    release_label = str(os.environ.get("EA_RELEASE_LABEL") or os.environ.get("RELEASE_LABEL") or _env_value("EA_RELEASE_LABEL") or _env_value("RELEASE_LABEL") or "").strip()
    if not release_label:
        release_label = deployment_id or (commit_sha[:12] if commit_sha else "")
    payload: dict[str, Any] = {
        "contract_name": "ea.deploy_context.v1",
        "generated_by": "scripts/materialize_deploy_context.py",
        "generated_at": normalized_generated_at,
        "repository": str(os.environ.get("EA_DEPLOY_REPOSITORY") or ROOT.name).strip(),
        "deployment_id": deployment_id,
        "deployment_id_source": deployment_id_source,
        "public_origin": public_origin,
        "public_origin_source": str(os.environ.get("EA_DEPLOY_PUBLIC_ORIGIN_SOURCE") or public_origin_source).strip(),
        "branch": branch,
        "tracking_branch": tracking_branch,
        "commit_sha": commit_sha,
        "release_label": release_label,
        "project_mode": project_mode,
        "enabled_project_modes": enabled_project_modes,
        "compose_files": compose_files,
        "compose_overrides": compose_overrides,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    if any(arg in {"--help", "-h"} for arg in os.sys.argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/materialize_deploy_context.py [--output PATH] [--pretty]\n\n"
            "Write the deploy-context artifact consumed by the release manifest materializer."
        )
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "--out", dest="output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", dest="generated_at", default="")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    payload = build_deploy_context(
        output_path=args.output,
        generated_at=str(args.generated_at or "").strip() or None,
    )
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
