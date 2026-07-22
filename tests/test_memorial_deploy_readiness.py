from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_memorial_deploy_readiness_passes_when_release_authority_and_runtime_are_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
                "state": "clear",
                "issues": [],
                "next_action": "maintain_release_authority",
                "authority_posture": "authoritative_runtime",
                "gate": {"status": "pass", "issues": []},
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
    assert payload["release_authority"]["state"] == "clear"
    assert payload["release_authority"]["gate_status"] == "pass"


def test_memorial_deploy_readiness_fails_closed_when_release_authority_and_runtime_are_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
                "issues": [
                    "deployment_id_local_fallback",
                    "dirty_worktree",
                ],
                "next_action": "Rematerialize deploy context and the release manifest from the currently deployed commit before trusting release authority.",
                "authority_posture": "stale_deploy_context",
                "gate": {"status": "fail"},
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
    assert payload["release_authority"]["status"] == "fail"


def test_memorial_deploy_readiness_reads_release_authority_state_field_when_status_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
                "gate": {"status": "fail"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(readiness, "MEMORIAL_STATUS_PATH", memorial_status)
    monkeypatch.setattr(readiness, "RELEASE_AUTHORITY_PATH", release_authority)

    payload = readiness.build_payload()

    assert payload["status"] == "fail"
    assert payload["release_authority"]["status"] == "fail"
    assert payload["release_authority"]["state"] == "watch"
    assert payload["release_authority"]["authority_posture"] == "local_only_deploy_id"
    assert payload["next_action"] == "clear_release_authority_for_memorial_deploy"


@pytest.mark.parametrize(
    ("authority", "expected_issues"),
    [
        (
            {
                "state": "watch",
                "status": "pass",
                "issues": [],
                "gate": {"status": "pass"},
            },
            ["release_authority_blocked"],
        ),
        (
            {"state": "clear", "issues": [], "gate": {"status": "fail"}},
            ["release_authority_blocked"],
        ),
        (
            {
                "state": "clear",
                "issues": ["dirty_worktree"],
                "gate": {"status": "pass"},
            },
            ["dirty_worktree"],
        ),
        (
            {
                "state": "clear",
                "issues": [],
                "gate": {"status": "pass", "issues": ["stale_deploy_context"]},
            },
            ["stale_deploy_context"],
        ),
    ],
)
def test_memorial_deploy_readiness_fails_closed_for_incomplete_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority: dict[str, object],
    expected_issues: list[str],
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
    release_authority.write_text(json.dumps(authority), encoding="utf-8")
    monkeypatch.setattr(readiness, "MEMORIAL_STATUS_PATH", memorial_status)
    monkeypatch.setattr(readiness, "RELEASE_AUTHORITY_PATH", release_authority)

    payload = readiness.build_payload()

    assert payload["status"] == "fail"
    assert payload["issues"] == expected_issues
    assert payload["release_authority"]["status"] == "fail"


def test_memorial_make_target_uses_joint_lane_and_orders_authority_readiness() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    deploy_alias = makefile.split("deploy-ea-memorial:", 1)[1].split("\n\n", 1)[0]
    joint_target = makefile.split("deploy-ea-memorial-joint:\n", 1)[1].split(
        "\n\n", 1
    )[0]
    readiness_target = makefile.split(
        "verify-memorial-deploy-readiness: refresh-release-authority-status\n",
        1,
    )[1].split("\n\n", 1)[0]

    assert "deploy-ea-memorial-joint" in deploy_alias
    assert "EA_DEPLOYMENT_ID" in joint_target
    assert "EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT" in joint_target
    assert "scripts/deploy_ea_memorial_joint.py" in joint_target
    assert "scripts/deploy.sh" not in deploy_alias + joint_target
    assert readiness_target.index(
        "scripts/materialize_memorial_operator_status.py"
    ) < readiness_target.index("scripts/verify_memorial_deploy_readiness.py")


def test_memorial_release_docs_require_attached_upstream_worktree() -> None:
    checklist = (ROOT / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "MEMORIAL_FLAGSHIP_RUNBOOK.md").read_text(
        encoding="utf-8"
    )

    assert "never deploy from detached `HEAD`" in checklist
    assert 'git worktree add -b "$release_branch" "$release_root" HEAD' in runbook
    assert 'branch --set-upstream-to=origin/main "$release_branch"' in runbook
    assert 'release_root="/docker/EA-releases/' in runbook
    assert 'release_root="/tmp/' not in runbook
