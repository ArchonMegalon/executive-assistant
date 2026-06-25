from __future__ import annotations

import json
from pathlib import Path


def test_memorial_deploy_readiness_passes_when_release_authority_and_runtime_are_ready(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.verify_memorial_deploy_readiness as readiness

    memorial_status = tmp_path / "memorial_status.json"
    release_authority = tmp_path / "release_authority.json"
    memorial_status.write_text(
        json.dumps(
            {
                "public_runtime_mode_detail": {
                    "status": "pass",
                    "reason": "memorial_runtime_declared",
                    "next_action": "maintain_memorial_public_runtime",
                    "project_mode": "MEMORIAL",
                    "enabled_project_modes": ["MEMORIAL"],
                }
            }
        ),
        encoding="utf-8",
    )
    release_authority.write_text(
        json.dumps(
            {
                "status": "pass",
                "issues": [],
                "next_action": "maintain_release_authority",
                "authority_posture": "authoritative_runtime",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(readiness, "MEMORIAL_STATUS_PATH", memorial_status)
    monkeypatch.setattr(readiness, "RELEASE_AUTHORITY_PATH", release_authority)

    payload = readiness.build_payload()

    assert payload["contract_name"] == "ea.memorial_deploy_readiness.v1"
    assert payload["status"] == "pass"
    assert payload["issues"] == []
    assert payload["next_action"] == "deploy_ea_memorial"
    assert payload["memorial_public_runtime"]["status"] == "pass"
    assert payload["release_authority"]["status"] == "pass"


def test_memorial_deploy_readiness_fails_closed_when_release_authority_and_runtime_are_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.verify_memorial_deploy_readiness as readiness

    memorial_status = tmp_path / "memorial_status.json"
    release_authority = tmp_path / "release_authority.json"
    memorial_status.write_text(
        json.dumps(
            {
                "public_runtime_mode_detail": {
                    "status": "blocked",
                    "reason": "public_origin_not_deployed_in_memorial_mode",
                    "next_action": "deploy_ea_memorial",
                    "project_mode": "EA_CORE",
                    "enabled_project_modes": ["EA_CORE"],
                }
            }
        ),
        encoding="utf-8",
    )
    release_authority.write_text(
        json.dumps(
            {
                "status": "missing",
                "issues": [
                    "deployment_id_local_fallback",
                    "dirty_worktree",
                ],
                "next_action": "Rematerialize deploy context and the release manifest from the currently deployed commit before trusting release authority.",
                "authority_posture": "stale_deploy_context",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(readiness, "MEMORIAL_STATUS_PATH", memorial_status)
    monkeypatch.setattr(readiness, "RELEASE_AUTHORITY_PATH", release_authority)

    payload = readiness.build_payload()

    assert payload["status"] == "fail"
    assert payload["issues"] == [
        "deployment_id_local_fallback",
        "dirty_worktree",
        "public_origin_not_deployed_in_memorial_mode",
    ]
    assert payload["next_action"] == "clear_release_authority_for_memorial_deploy"
    assert payload["memorial_public_runtime"]["status"] == "blocked"
    assert payload["release_authority"]["status"] == "missing"


def test_memorial_deploy_readiness_reads_release_authority_state_field_when_status_is_absent(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.verify_memorial_deploy_readiness as readiness

    memorial_status = tmp_path / "memorial_status.json"
    release_authority = tmp_path / "release_authority.json"
    memorial_status.write_text(
        json.dumps(
            {
                "public_runtime_mode_detail": {
                    "status": "blocked",
                    "reason": "public_origin_not_deployed_in_memorial_mode",
                    "next_action": "deploy_ea_memorial",
                    "project_mode": "EA_CORE",
                    "enabled_project_modes": ["EA_CORE"],
                }
            }
        ),
        encoding="utf-8",
    )
    release_authority.write_text(
        json.dumps(
            {
                "state": "watch",
                "issues": ["deployment_id_local_fallback", "dirty_worktree"],
                "next_action": "clear_release_authority_for_memorial_deploy",
                "authority_posture": "local_only_deploy_id",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(readiness, "MEMORIAL_STATUS_PATH", memorial_status)
    monkeypatch.setattr(readiness, "RELEASE_AUTHORITY_PATH", release_authority)

    payload = readiness.build_payload()

    assert payload["status"] == "fail"
    assert payload["release_authority"]["status"] == "watch"
    assert payload["release_authority"]["authority_posture"] == "local_only_deploy_id"
    assert payload["next_action"] == "clear_release_authority_for_memorial_deploy"
