#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_MANIFEST = ROOT / ".codex-studio/published/release_manifest.generated.json"
DEFAULT_PROJECT_MODES = ROOT / ".codex-design/product/PROJECT_MODES.generated.json"
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json:{path}")
    return payload


def _normalize_mode(raw: str) -> str:
    return str(raw or "").strip().upper().replace("-", "_")


def _derive_authority_posture(issues: list[str]) -> str:
    issue_set = set(issues)
    if "release_manifest_missing" in issue_set:
        return "missing_manifest"
    if {"public_origin_missing", "public_origin_source_missing", "public_origin_not_runtime_origin"} & issue_set:
        return "missing_public_origin"
    if {
        "deploy_context_missing",
        "deploy_context_generated_at_missing",
        "deploy_context_branch_missing",
        "deploy_context_tracking_branch_missing",
        "deploy_context_commit_missing",
        "deploy_context_branch_mismatch",
        "deploy_context_commit_mismatch",
        "deploy_context_tracking_branch_mismatch",
    } & issue_set:
        return "stale_deploy_context"
    if "deployment_id_local_fallback" in issue_set:
        return "local_only_deploy_id"
    if "dirty_worktree" in issue_set:
        return "dirty_worktree"
    if "compose_files_missing" in issue_set:
        return "compose_topology_missing"
    if {
        "source_remote_ref_missing",
        "source_remote_ref_invalid",
        "source_remote_ref_tracking_branch_mismatch",
        "source_remote_ref_commit_sha_missing",
        "source_remote_ref_commit_sha_invalid",
        "source_remote_ref_evidence_invalid",
        "source_commit_not_reachable_from_remote_ref",
    } & issue_set:
        return "source_not_remote"
    if issues:
        return "watch"
    return "authoritative_runtime"


def validate_release_authority(
    *,
    release_manifest: dict[str, Any],
    project_modes: dict[str, Any],
    require_public_origin: bool = True,
    require_explicit_deployment: bool = True,
    require_clean_worktree: bool = True,
    require_tracking_branch: bool = True,
    require_source_remote_ref: bool = True,
    require_compose_files: bool = True,
) -> list[str]:
    issues: list[str] = []
    if not release_manifest:
        return ["release_manifest_missing"]
    if str(release_manifest.get("contract_name") or "").strip() != "ea.release_manifest.v1":
        issues.append("release_manifest_contract_invalid")

    repository = str(release_manifest.get("repository") or "").strip()
    branch = str(release_manifest.get("branch") or "").strip()
    tracking_branch = str(release_manifest.get("tracking_branch") or "").strip()
    commit_sha = str(release_manifest.get("commit_sha") or "").strip()
    source_remote_ref = str(release_manifest.get("source_remote_ref") or "").strip()
    source_remote_ref_commit_sha = str(
        release_manifest.get("source_remote_ref_commit_sha") or ""
    ).strip()
    source_remote_ref_evidence = str(
        release_manifest.get("source_remote_ref_evidence") or ""
    ).strip()
    source_commit_reachable_from_remote_ref = release_manifest.get(
        "source_commit_reachable_from_remote_ref"
    )
    deployment_id = str(release_manifest.get("deployment_id") or "").strip()
    deployment_id_source = str(release_manifest.get("deployment_id_source") or "").strip()
    public_origin = str(release_manifest.get("public_origin") or "").strip()
    public_origin_source = str(release_manifest.get("public_origin_source") or "").strip()
    git_remote_origin = str(release_manifest.get("git_remote_origin") or "").strip()
    release_label = str(release_manifest.get("release_label") or "").strip()
    deploy_context_generated_at = str(release_manifest.get("deploy_context_generated_at") or "").strip()
    deploy_context_branch = str(release_manifest.get("deploy_context_branch") or "").strip()
    deploy_context_tracking_branch = str(release_manifest.get("deploy_context_tracking_branch") or "").strip()
    deploy_context_commit_sha = str(release_manifest.get("deploy_context_commit_sha") or "").strip()
    project_mode = _normalize_mode(str(release_manifest.get("project_mode") or ""))
    enabled_project_modes = [
        _normalize_mode(str(item))
        for item in list(release_manifest.get("enabled_project_modes") or [])
        if _normalize_mode(str(item))
    ]
    compose_files = [str(item).strip() for item in list(release_manifest.get("compose_files") or []) if str(item).strip()]
    artifact_set = [str(item).strip() for item in list(release_manifest.get("artifact_set") or []) if str(item).strip()]
    dirty_worktree = bool(release_manifest.get("dirty_worktree"))
    source_worktree_dirty = bool(release_manifest.get("source_worktree_dirty", dirty_worktree))

    declared_modes = {
        _normalize_mode(str(item.get("key") or ""))
        for item in list(project_modes.get("modes") or [])
        if isinstance(item, dict) and _normalize_mode(str(item.get("key") or ""))
    }

    required_fields = {
        "repository": repository,
        "branch": branch,
        "commit_sha": commit_sha,
        "deployment_id": deployment_id,
        "release_label": release_label,
        "project_mode": project_mode,
    }
    for key, value in required_fields.items():
        if not value:
            issues.append(f"missing_{key}")
    if not enabled_project_modes:
        issues.append("enabled_project_modes_empty")
    if not artifact_set:
        issues.append("artifact_set_empty")
    if require_tracking_branch and not tracking_branch:
        issues.append("tracking_branch_missing")
    if require_source_remote_ref:
        if not source_remote_ref:
            issues.append("source_remote_ref_missing")
        elif not source_remote_ref.startswith("refs/remotes/"):
            issues.append("source_remote_ref_invalid")
        elif tracking_branch and source_remote_ref.removeprefix("refs/remotes/") != tracking_branch:
            issues.append("source_remote_ref_tracking_branch_mismatch")
        if not source_remote_ref_commit_sha:
            issues.append("source_remote_ref_commit_sha_missing")
        elif not _GIT_COMMIT_RE.fullmatch(source_remote_ref_commit_sha):
            issues.append("source_remote_ref_commit_sha_invalid")
        if source_remote_ref_evidence != "local_remote_tracking_ref":
            issues.append("source_remote_ref_evidence_invalid")
        if source_commit_reachable_from_remote_ref is not True:
            issues.append("source_commit_not_reachable_from_remote_ref")
    if require_compose_files and not compose_files:
        issues.append("compose_files_missing")
    if require_public_origin:
        if not public_origin:
            issues.append("public_origin_missing")
        if public_origin_source in {"missing", ""}:
            issues.append("public_origin_source_missing")
        if public_origin_source == "missing" and git_remote_origin:
            issues.append("public_origin_not_runtime_origin")
    if project_mode and declared_modes and project_mode not in declared_modes:
        issues.append("project_mode_not_declared")
    undeclared_modes = [mode for mode in enabled_project_modes if declared_modes and mode not in declared_modes]
    if undeclared_modes:
        issues.append("enabled_project_modes_not_declared")
    if require_explicit_deployment and (deployment_id_source == "local_fallback" or deployment_id.startswith("local-")):
        issues.append("deployment_id_local_fallback")
    if require_explicit_deployment and deployment_id and "deployment_id_local_fallback" not in issues:
        if not any((deploy_context_generated_at, deploy_context_branch, deploy_context_tracking_branch, deploy_context_commit_sha)):
            issues.append("deploy_context_missing")
        else:
            if not deploy_context_generated_at:
                issues.append("deploy_context_generated_at_missing")
            if not deploy_context_branch:
                issues.append("deploy_context_branch_missing")
            if require_tracking_branch and not deploy_context_tracking_branch:
                issues.append("deploy_context_tracking_branch_missing")
            if not deploy_context_commit_sha:
                issues.append("deploy_context_commit_missing")
    local_only_deployment = deployment_id_source == "local_fallback" or deployment_id.startswith("local-")
    if not local_only_deployment:
        if deploy_context_branch and branch and deploy_context_branch != branch:
            issues.append("deploy_context_branch_mismatch")
        if deploy_context_commit_sha and commit_sha and deploy_context_commit_sha != commit_sha:
            issues.append("deploy_context_commit_mismatch")
        if deploy_context_tracking_branch and tracking_branch and deploy_context_tracking_branch != tracking_branch:
            issues.append("deploy_context_tracking_branch_mismatch")
    if require_clean_worktree and source_worktree_dirty:
        issues.append("dirty_worktree")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument("--project-modes", type=Path, default=DEFAULT_PROJECT_MODES)
    parser.add_argument("--allow-missing-public-origin", action="store_true")
    parser.add_argument("--allow-local-deployment-id", action="store_true")
    parser.add_argument("--allow-dirty-worktree", action="store_true")
    parser.add_argument("--allow-missing-tracking-branch", action="store_true")
    parser.add_argument("--allow-missing-compose-files", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    release_manifest = _load_json(args.release_manifest)
    project_modes = _load_json(args.project_modes)
    issues = validate_release_authority(
        release_manifest=release_manifest,
        project_modes=project_modes,
        require_public_origin=not args.allow_missing_public_origin,
        require_explicit_deployment=not args.allow_local_deployment_id,
        require_clean_worktree=not args.allow_dirty_worktree,
        require_tracking_branch=not args.allow_missing_tracking_branch,
        require_source_remote_ref=not args.allow_missing_tracking_branch,
        require_compose_files=not args.allow_missing_compose_files,
    )
    payload = {
        "contract_name": "ea.release_authority_gate.v1",
        "status": "pass" if not issues else "fail",
        "authority_posture": _derive_authority_posture(issues),
        "issues": issues,
        "manifest_path": str(args.release_manifest),
        "project_modes_path": str(args.project_modes),
        "repository": str(release_manifest.get("repository") or "").strip(),
        "branch": str(release_manifest.get("branch") or "").strip(),
        "tracking_branch": str(release_manifest.get("tracking_branch") or "").strip(),
        "commit_sha": str(release_manifest.get("commit_sha") or "").strip(),
        "source_remote_ref": str(release_manifest.get("source_remote_ref") or "").strip(),
        "source_remote_ref_commit_sha": str(
            release_manifest.get("source_remote_ref_commit_sha") or ""
        ).strip(),
        "source_remote_ref_evidence": str(
            release_manifest.get("source_remote_ref_evidence") or ""
        ).strip(),
        "source_commit_reachable_from_remote_ref": (
            release_manifest.get("source_commit_reachable_from_remote_ref") is True
        ),
        "deployment_id": str(release_manifest.get("deployment_id") or "").strip(),
        "deployment_id_source": str(release_manifest.get("deployment_id_source") or "").strip(),
        "public_origin": str(release_manifest.get("public_origin") or "").strip(),
        "public_origin_source": str(release_manifest.get("public_origin_source") or "").strip(),
        "deploy_context_generated_at": str(release_manifest.get("deploy_context_generated_at") or "").strip(),
        "deploy_context_branch": str(release_manifest.get("deploy_context_branch") or "").strip(),
        "deploy_context_tracking_branch": str(release_manifest.get("deploy_context_tracking_branch") or "").strip(),
        "deploy_context_commit_sha": str(release_manifest.get("deploy_context_commit_sha") or "").strip(),
        "project_mode": _normalize_mode(str(release_manifest.get("project_mode") or "")),
        "enabled_project_modes": [
            _normalize_mode(str(item))
            for item in list(release_manifest.get("enabled_project_modes") or [])
            if _normalize_mode(str(item))
        ],
        "compose_files": [str(item).strip() for item in list(release_manifest.get("compose_files") or []) if str(item).strip()],
        "compose_overrides": [str(item).strip() for item in list(release_manifest.get("compose_overrides") or []) if str(item).strip()],
        "dirty_worktree": bool(release_manifest.get("dirty_worktree")),
        "source_worktree_dirty": bool(release_manifest.get("source_worktree_dirty", release_manifest.get("dirty_worktree"))),
        "source_dirty_count": int(release_manifest.get("source_dirty_count") or 0),
        "source_dirty_files": [
            str(item).strip()
            for item in list(release_manifest.get("source_dirty_files") or [])
            if str(item).strip()
        ],
        "source_dirty_omitted_count": int(release_manifest.get("source_dirty_omitted_count") or 0),
        "source_dirty_status_sha256": str(release_manifest.get("source_dirty_status_sha256") or "").strip(),
    }
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
