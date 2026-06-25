#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / ".codex-studio" / "published" / "deploy_context.generated.json"
ALLOWED_DEPLOYMENT_ID_SOURCES = {
    "deploy_context",
    "deploy_platform",
    "deploy_script_generated",
    "ea_deploy_id_env",
    "explicit",
    "local_fallback",
    "render_git_commit",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json:{path}")
    return payload


def verify(*, deploy_context: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if str(deploy_context.get("contract_name") or "").strip() != "ea.deploy_context.v1":
        issues.append("deploy_context_contract_invalid")

    deployment_id = str(deploy_context.get("deployment_id") or "").strip()
    deployment_id_source = str(deploy_context.get("deployment_id_source") or "").strip()
    public_origin = str(deploy_context.get("public_origin") or "").strip()
    public_origin_source = str(deploy_context.get("public_origin_source") or "").strip()
    repository = str(deploy_context.get("repository") or "").strip()
    branch = str(deploy_context.get("branch") or "").strip()
    tracking_branch = str(deploy_context.get("tracking_branch") or "").strip()
    commit_sha = str(deploy_context.get("commit_sha") or "").strip()
    release_label = str(deploy_context.get("release_label") or "").strip()
    project_mode = str(deploy_context.get("project_mode") or "").strip()
    enabled_project_modes = [str(item).strip() for item in list(deploy_context.get("enabled_project_modes") or []) if str(item).strip()]
    compose_files = [str(item).strip() for item in list(deploy_context.get("compose_files") or []) if str(item).strip()]

    required = {
        "deployment_id": deployment_id,
        "deployment_id_source": deployment_id_source,
        "public_origin": public_origin,
        "public_origin_source": public_origin_source,
        "repository": repository,
        "branch": branch,
        "tracking_branch": tracking_branch,
        "commit_sha": commit_sha,
        "release_label": release_label,
        "project_mode": project_mode,
    }
    for key, value in required.items():
        if not value:
            issues.append(f"missing_{key}")
    if deployment_id_source and deployment_id_source not in ALLOWED_DEPLOYMENT_ID_SOURCES:
        issues.append("invalid_deployment_id_source")
    if deployment_id.startswith("local-") and deployment_id_source and deployment_id_source != "local_fallback":
        issues.append("deployment_id_source_mismatch")
    if deployment_id_source == "local_fallback":
        issues.append("deployment_id_local_fallback")
    if not enabled_project_modes:
        issues.append("enabled_project_modes_empty")
    if project_mode and enabled_project_modes and project_mode not in enabled_project_modes:
        issues.append("project_mode_not_in_enabled_project_modes")
    if not compose_files:
        issues.append("compose_files_empty")

    return {
        "contract_name": "ea.deploy_context_gate.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "deployment_id": deployment_id,
        "deployment_id_source": deployment_id_source,
        "public_origin": public_origin,
        "public_origin_source": public_origin_source,
        "repository": repository,
        "branch": branch,
        "tracking_branch": tracking_branch,
        "commit_sha": commit_sha,
        "release_label": release_label,
        "project_mode": project_mode,
        "enabled_project_modes": enabled_project_modes,
        "compose_files": compose_files,
        "compose_overrides": [str(item).strip() for item in list(deploy_context.get("compose_overrides") or []) if str(item).strip()],
    }


def main() -> int:
    if any(arg in {"--help", "-h"} for arg in __import__("sys").argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/verify_deploy_context.py [--input PATH] [--pretty]\n\n"
            "Verify the deploy-context artifact consumed by release-manifest materialization."
        )
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "--deploy-context", dest="input_path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    payload = verify(deploy_context=_load_json(args.input_path))
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
