#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

try:
    from scripts.verify_deploy_context import verify as verify_deploy_context
    from scripts.verify_release_authority import _derive_authority_posture
    from scripts.verify_release_authority import validate_release_authority
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from verify_deploy_context import verify as verify_deploy_context
    from verify_release_authority import _derive_authority_posture
    from verify_release_authority import validate_release_authority


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "release_authority_status.generated.json"
DEFAULT_RELEASE_MANIFEST = ROOT / ".codex-studio" / "published" / "release_manifest.generated.json"
DEFAULT_DEPLOY_CONTEXT = ROOT / ".codex-studio" / "published" / "deploy_context.generated.json"
DEFAULT_PROJECT_MODES = ROOT / ".codex-design" / "product" / "PROJECT_MODES.generated.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _write_json_stable(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = None
        if existing == payload:
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")


def _declared_project_modes(project_modes: dict[str, Any]) -> list[str]:
    declared: list[str] = []
    for item in list(project_modes.get("modes") or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key and key not in declared:
            declared.append(key)
    return declared


def _enabled_modes_summary(project_mode: str, enabled_project_modes: list[str]) -> str:
    normalized_mode = str(project_mode or "").strip()
    normalized_enabled = [str(item).strip() for item in enabled_project_modes if str(item).strip()]
    if not normalized_enabled:
        return ""
    if len(normalized_enabled) == 1 and normalized_enabled[0] == normalized_mode:
        return ""
    return ", ".join(normalized_enabled[:4])


def _next_action_for_posture(posture: str, *, issues: list[str] | None = None) -> str:
    issue_set = {str(item).strip() for item in list(issues or []) if str(item).strip()}
    if posture == "missing_manifest":
        return "Materialize the release manifest from the running deploy before trusting release claims."
    if posture == "missing_public_origin":
        return "Set the deployed public base URL and rematerialize the release manifest so release authority points at a runtime origin."
    if posture == "stale_deploy_context":
        return "Rematerialize deploy context and the release manifest from the currently deployed commit before trusting release authority."
    if posture == "local_only_deploy_id":
        if "dirty_worktree" in issue_set:
            return "Deploy from a clean committed tree with an explicit deployment ID from the real deploy system, then rematerialize the release manifest."
        return "Set an explicit deployment ID from the real deploy system and rematerialize the release manifest."
    if posture == "dirty_worktree":
        return "Build from a clean committed tree before treating this runtime as release authority."
    if posture == "compose_topology_missing":
        return "Materialize the release manifest through the deploy path so the compose topology is recorded."
    if posture in {"watch", "verifier_error"}:
        return "Resolve release authority issues before using this runtime as the shipping source of truth."
    return "No action required."


def build_status(
    *,
    release_manifest_path: Path = DEFAULT_RELEASE_MANIFEST,
    deploy_context_path: Path = DEFAULT_DEPLOY_CONTEXT,
    project_modes_path: Path = DEFAULT_PROJECT_MODES,
    generated_at: str | None = None,
) -> dict[str, Any]:
    manifest = _load_json(release_manifest_path)
    deploy_context = _load_json(deploy_context_path)
    project_modes = _load_json(project_modes_path)
    declared_modes = _declared_project_modes(project_modes)
    deploy_context_gate = verify_deploy_context(deploy_context=deploy_context)

    if not manifest:
        gate = {
            "contract_name": "ea.release_authority_gate.v1",
            "status": "fail",
            "authority_posture": "missing_manifest",
            "issues": ["release_manifest_missing"],
            "manifest_path": str(release_manifest_path),
            "deploy_context_path": str(deploy_context_path),
            "project_modes_path": str(project_modes_path),
        }
        return {
            "contract_name": "ea.release_authority_status.v1",
            "generated_at": generated_at or _utc_now(),
            "state": "missing",
            "summary": "Release authority is missing for the current runtime.",
            "authority_posture": "missing_manifest",
            "next_action": _next_action_for_posture("missing_manifest"),
            "authority_basis": "Release authority basis has not been recorded.",
            "manifest_path": str(release_manifest_path),
            "deploy_context_path": str(deploy_context_path),
            "project_modes_path": str(project_modes_path),
            "issues": ["release_manifest_missing"],
            "repository": "",
            "branch": "",
            "tracking_branch": "",
            "commit_sha": "",
            "deployment_id": "",
            "deployment_id_source": "",
            "public_origin": "",
            "public_origin_source": "",
            "release_label": "",
            "project_mode": "",
            "enabled_project_modes": [],
            "compose_files": [],
            "compose_overrides": [],
            "declared_project_modes": declared_modes,
            "artifact_count": 0,
            "artifact_set_preview": [],
            "deploy_context_gate": deploy_context_gate,
            "gate": gate,
        }

    issues = validate_release_authority(release_manifest=manifest, project_modes=project_modes)
    posture = _derive_authority_posture(issues)
    state = "clear" if not issues else "watch"

    repository = str(manifest.get("repository") or "").strip()
    branch = str(manifest.get("branch") or "").strip()
    tracking_branch = str(manifest.get("tracking_branch") or "").strip()
    commit_sha = str(manifest.get("commit_sha") or "").strip()
    deployment_id = str(manifest.get("deployment_id") or "").strip()
    deployment_id_source = str(manifest.get("deployment_id_source") or "").strip()
    public_origin = str(manifest.get("public_origin") or "").strip()
    public_origin_source = str(manifest.get("public_origin_source") or "").strip()
    release_label = str(manifest.get("release_label") or "").strip()
    project_mode = str(manifest.get("project_mode") or "").strip()
    enabled_project_modes = [
        str(item).strip()
        for item in list(manifest.get("enabled_project_modes") or [])
        if str(item).strip()
    ]
    compose_files = [
        str(item).strip()
        for item in list(manifest.get("compose_files") or [])
        if str(item).strip()
    ]
    compose_overrides = [
        str(item).strip()
        for item in list(manifest.get("compose_overrides") or [])
        if str(item).strip()
    ]
    artifact_set = [
        str(item).strip()
        for item in list(manifest.get("artifact_set") or [])
        if str(item).strip()
    ]

    summary = "Release authority is recorded for the current runtime."
    if state == "watch":
        summary = "Release authority is present but still has gaps to resolve."
    authority_basis = " · ".join(
        item
        for item in (
            f"{branch}@{tracking_branch}" if branch and tracking_branch else branch or tracking_branch,
            commit_sha[:12] if commit_sha else "",
            project_mode,
            _enabled_modes_summary(project_mode, enabled_project_modes),
            ", ".join(compose_overrides[:4]) if compose_overrides else ", ".join(compose_files[:4]),
        )
        if item
    ).strip() or "Release authority basis has not been recorded."

    gate = {
        "contract_name": "ea.release_authority_gate.v1",
        "status": "pass" if not issues else "fail",
        "authority_posture": posture,
        "issues": list(issues),
        "manifest_path": str(release_manifest_path),
        "deploy_context_path": str(deploy_context_path),
        "project_modes_path": str(project_modes_path),
        "repository": repository,
        "branch": branch,
        "tracking_branch": tracking_branch,
        "commit_sha": commit_sha,
        "deployment_id": deployment_id,
        "deployment_id_source": deployment_id_source,
        "public_origin": public_origin,
        "public_origin_source": public_origin_source,
        "project_mode": project_mode,
        "enabled_project_modes": enabled_project_modes,
        "compose_files": compose_files,
        "compose_overrides": compose_overrides,
        "dirty_worktree": bool(manifest.get("dirty_worktree")),
        "source_worktree_dirty": bool(manifest.get("source_worktree_dirty", manifest.get("dirty_worktree"))),
        "source_dirty_count": int(manifest.get("source_dirty_count") or 0),
        "source_dirty_files": [
            str(item).strip()
            for item in list(manifest.get("source_dirty_files") or [])
            if str(item).strip()
        ],
        "source_dirty_omitted_count": int(manifest.get("source_dirty_omitted_count") or 0),
        "source_dirty_status_sha256": str(manifest.get("source_dirty_status_sha256") or "").strip(),
        "deploy_context_generated_at": str(manifest.get("deploy_context_generated_at") or "").strip(),
        "deploy_context_branch": str(manifest.get("deploy_context_branch") or "").strip(),
        "deploy_context_tracking_branch": str(manifest.get("deploy_context_tracking_branch") or "").strip(),
        "deploy_context_commit_sha": str(manifest.get("deploy_context_commit_sha") or "").strip(),
    }

    return {
        "contract_name": "ea.release_authority_status.v1",
        "generated_at": generated_at or _utc_now(),
        "state": state,
        "summary": summary,
        "authority_posture": posture,
        "next_action": _next_action_for_posture(posture, issues=issues),
        "authority_basis": authority_basis,
        "manifest_path": str(release_manifest_path),
        "deploy_context_path": str(deploy_context_path),
        "project_modes_path": str(project_modes_path),
        "issues": list(issues),
        "repository": repository,
        "branch": branch,
        "tracking_branch": tracking_branch,
        "commit_sha": commit_sha,
        "dirty_worktree": bool(manifest.get("dirty_worktree")),
        "source_worktree_dirty": bool(manifest.get("source_worktree_dirty", manifest.get("dirty_worktree"))),
        "source_dirty_count": int(manifest.get("source_dirty_count") or 0),
        "source_dirty_files": [
            str(item).strip()
            for item in list(manifest.get("source_dirty_files") or [])
            if str(item).strip()
        ],
        "source_dirty_omitted_count": int(manifest.get("source_dirty_omitted_count") or 0),
        "source_dirty_status_sha256": str(manifest.get("source_dirty_status_sha256") or "").strip(),
        "deployment_id": deployment_id,
        "deployment_id_source": deployment_id_source,
        "public_origin": public_origin,
        "public_origin_source": public_origin_source,
        "deploy_context_generated_at": str(manifest.get("deploy_context_generated_at") or "").strip(),
        "deploy_context_branch": str(manifest.get("deploy_context_branch") or "").strip(),
        "deploy_context_tracking_branch": str(manifest.get("deploy_context_tracking_branch") or "").strip(),
        "deploy_context_commit_sha": str(manifest.get("deploy_context_commit_sha") or "").strip(),
        "git_remote_origin": str(manifest.get("git_remote_origin") or "").strip(),
        "release_label": release_label,
        "project_mode": project_mode,
        "enabled_project_modes": enabled_project_modes,
        "compose_files": compose_files,
        "compose_overrides": compose_overrides,
        "artifact_count": len(artifact_set),
        "artifact_set_preview": artifact_set[:8],
        "declared_project_modes": declared_modes,
        "deploy_context_gate": deploy_context_gate,
        "gate": gate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the published release-authority status artifact from the current manifest and gate.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--release-manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument("--deploy-context", type=Path, default=DEFAULT_DEPLOY_CONTEXT)
    parser.add_argument("--project-modes", type=Path, default=DEFAULT_PROJECT_MODES)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    payload = build_status(
        release_manifest_path=args.release_manifest,
        deploy_context_path=args.deploy_context,
        project_modes_path=args.project_modes,
    )
    _write_json_stable(args.output, payload)
    if args.pretty:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
