from __future__ import annotations

import fcntl
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

import scripts.deploy_ea_memorial as deploy_module
from scripts.deploy_ea_memorial import (
    OWNER_BREAK_GLASS_ACK,
    OWNER_BREAK_GLASS_AUTHORIZER,
    OWNER_BREAK_GLASS_REASON,
    OWNER_BREAK_GLASS_TOKEN,
    DeployError,
    MemorialDeployLane,
)


REVISION = "a" * 40
DEPLOYMENT_ID = "manfred-breakglass-20260716"
AUTHORIZATION_ID = "owner-directive-20260716-publish-now"


def _lane(tmp_path: Path, **overrides: str) -> MemorialDeployLane:
    env = {
        "EA_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "EA_MEMORIAL_OWNER_BREAK_GLASS": OWNER_BREAK_GLASS_TOKEN,
        "EA_MEMORIAL_OWNER_BREAK_GLASS_ACK": OWNER_BREAK_GLASS_ACK,
        "EA_MEMORIAL_OWNER_BREAK_GLASS_AUTHORIZATION_ID": AUTHORIZATION_ID,
        "EA_MEMORIAL_OWNER_BREAK_GLASS_AUTHORIZER": OWNER_BREAK_GLASS_AUTHORIZER,
        "EA_MEMORIAL_OWNER_BREAK_GLASS_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "EA_MEMORIAL_OWNER_BREAK_GLASS_REASON": OWNER_BREAK_GLASS_REASON,
        "EA_MEMORIAL_OWNER_BREAK_GLASS_SOURCE_REVISION": REVISION,
        **overrides,
    }
    lane = MemorialDeployLane(
        root=tmp_path,
        env=env,
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "global.lock",
        vexp_sentinel_state_path=tmp_path / "sentinel-state.json",
        durable_root_check=lambda _path: None,
    )
    lane._git_head = lambda: REVISION  # type: ignore[method-assign]
    return lane


def test_owner_break_glass_is_revision_and_deployment_bound_and_honestly_receipted(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)

    evidence = lane._require_vexp_certification_token_coverage(
        "immediately_before_api_mutation"
    )

    assert evidence["status"] == "fail"
    assert evidence["reason"] == "sentinel_state_untrusted"
    assert evidence["enforcement_decision"] == "owner_exception"
    assert evidence["observed_vexp_status"] == "fail"
    assert evidence["certification_bypassed"] is True
    assert evidence["certification_result_forged"] is False
    assert evidence["state_source"]["trusted_private_file"] is False
    assert evidence["state_source"]["credential_material_included"] is False
    authorization = evidence["owner_authorization"]
    assert authorization["authorization_id"] == AUTHORIZATION_ID
    assert authorization["deployment_id"] == DEPLOYMENT_ID
    assert authorization["source_revision"] == REVISION
    assert authorization["waived_requirement"] == "vexp_seven_day_certification"
    assert authorization["certification_result_forged"] is False

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["certification_policy_override"] == authorization
    check = receipt["checks"][-1]
    assert check["name"] == ("vexp_token_coverage_immediately_before_api_mutation")
    assert check["status"] == "owner_exception"
    assert check["observed_vexp_status"] == "fail"
    assert check["certification_bypassed"] is True
    assert check["certification_result_forged"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"EA_MEMORIAL_OWNER_BREAK_GLASS": "yes"},
        {"EA_MEMORIAL_OWNER_BREAK_GLASS": f" {OWNER_BREAK_GLASS_TOKEN}"},
        {"EA_MEMORIAL_OWNER_BREAK_GLASS_AUTHORIZATION_ID": "short"},
        {"EA_MEMORIAL_OWNER_BREAK_GLASS_AUTHORIZER": "owner"},
        {"EA_MEMORIAL_OWNER_BREAK_GLASS_DEPLOYMENT_ID": "another-deploy"},
        {"EA_MEMORIAL_OWNER_BREAK_GLASS_SOURCE_REVISION": "not-a-revision"},
        {"EA_MEMORIAL_OWNER_BREAK_GLASS_EXTRA": "unexpected"},
    ],
)
def test_owner_break_glass_partial_or_malformed_authorization_fails_closed(
    tmp_path: Path, overrides: dict[str, str]
) -> None:
    with pytest.raises(
        DeployError, match="memorial_owner_break_glass_authorization_invalid"
    ):
        _lane(tmp_path, **overrides)


def test_owner_break_glass_rejects_source_revision_drift(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane._git_head = lambda: "b" * 40  # type: ignore[method-assign]

    with pytest.raises(
        DeployError, match="memorial_owner_break_glass_source_revision_mismatch"
    ):
        lane._require_vexp_certification_token_coverage("preflight_entry")


def test_owner_break_glass_partial_contract_fails_during_construction(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        DeployError, match="memorial_owner_break_glass_authorization_invalid"
    ):
        MemorialDeployLane(
            root=tmp_path,
            env={
                "EA_DEPLOYMENT_ID": DEPLOYMENT_ID,
                "EA_MEMORIAL_OWNER_BREAK_GLASS": OWNER_BREAK_GLASS_TOKEN,
            },
            receipt_dir=tmp_path / "receipts",
            global_lock_path=tmp_path / "global.lock",
            durable_root_check=lambda _path: None,
        )


def test_owner_break_glass_environment_is_not_propagated_to_child_commands(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)

    assert not any(
        key.startswith("EA_MEMORIAL_OWNER_BREAK_GLASS") for key in lane.release_env
    )
    lane.runner = Mock()
    lane.runner.run.return_value = subprocess.CompletedProcess([], 0, "", "")

    lane._run(["true"])

    child_env = lane.runner.run.call_args.kwargs["env"]
    assert not any(key.startswith("EA_MEMORIAL_OWNER_BREAK_GLASS") for key in child_env)


def test_owner_break_glass_rejects_root_or_cross_uid_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deploy_module.os, "getresuid", lambda: (0, 0, 0))

    with pytest.raises(
        DeployError, match="memorial_owner_break_glass_authority_mismatch"
    ):
        _lane(tmp_path)


def test_owner_break_glass_still_obeys_global_deployment_lock(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    with lane.global_lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(
            DeployError, match="memorial_api_deployment_already_running"
        ):
            lane.deploy()


def test_owner_break_glass_full_deploy_keeps_every_non_vexp_gate(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    context = {
        "previous": {
            "working_dir": str(tmp_path / "previous"),
            "image_id": f"sha256:{'1' * 64}",
            "compose_config_files": [str(tmp_path / "docker-compose.yml")],
        },
        "candidate": {
            "reference": f"ea-runtime:manfred-{REVISION}",
            "image_id": f"sha256:{'2' * 64}",
        },
        "source_revision": REVISION,
        "public_origin": "https://myexternalbrain.com",
        "authority": {"authority_posture": "public_release_authorized"},
        "candidate_promotion": {"projection": {}},
        "deployment_input_seal": {"sha256": "3" * 64},
        "non_memorial_controls": {},
        "target_mounts": [],
    }

    def preflight() -> dict[str, object]:
        lane._require_vexp_certification_token_coverage("preflight_entry")
        return context

    lane.preflight = Mock(side_effect=preflight)  # type: ignore[method-assign]
    lane._require_deployment_input_seal = Mock()  # type: ignore[method-assign]
    lane._ensure_redis = Mock()  # type: ignore[method-assign]
    lane._protect_previous_image = Mock(  # type: ignore[method-assign]
        return_value="ea-runtime:rollback-owner-exception"
    )
    lane._recreate_api = Mock()  # type: ignore[method-assign]
    lane._wait_container = Mock(return_value={})  # type: ignore[method-assign]
    lane._verify_forward_api = Mock(return_value={})  # type: ignore[method-assign]
    lane._verify_deployed_surface = Mock()  # type: ignore[method-assign]
    lane._verify_candidate_origins = Mock()  # type: ignore[method-assign]
    lane._verify_non_memorial_controls = Mock()  # type: ignore[method-assign]
    lane._materialize_and_verify_release_evidence = Mock(  # type: ignore[method-assign]
        return_value={"status": "pass"}
    )

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert receipt["governance_posture"] == "owner_vexp_exception"
    assert receipt["all_non_vexp_gates_enforced"] is True
    exception_checks = [
        check
        for check in receipt["checks"]
        if str(check.get("name") or "").startswith("vexp_token_coverage_")
    ]
    assert [check["name"] for check in exception_checks] == [
        "vexp_token_coverage_preflight_entry",
        "vexp_token_coverage_before_redis_mutation",
        "vexp_token_coverage_before_rollback_protection",
        "vexp_token_coverage_immediately_before_api_mutation",
        "vexp_token_coverage_before_postdeploy_evidence",
        "vexp_token_coverage_before_promotion_success",
    ]
    assert all(check["status"] == "owner_exception" for check in exception_checks)
    assert all(
        check["certification_result_forged"] is False
        and check["non_vexp_gates_bypassed"] is False
        for check in exception_checks
    )
    lane._require_deployment_input_seal.assert_called()
    lane._ensure_redis.assert_called_once()
    lane._protect_previous_image.assert_called_once()
    lane._recreate_api.assert_called_once()
    lane._verify_deployed_surface.assert_called_once()
    lane._verify_candidate_origins.assert_called_once()
    lane._verify_non_memorial_controls.assert_called_once()
    lane._materialize_and_verify_release_evidence.assert_called_once()


def test_owner_break_glass_never_claims_completed_certification_from_token_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = _lane(tmp_path)
    monkeypatch.setattr(
        deploy_module,
        "_read_trusted_vexp_sentinel_state",
        lambda _path: ({"version": 6}, {"sha256": "4" * 64, "mtime_ns": 1}),
    )
    monkeypatch.setattr(
        deploy_module,
        "_vexp_certification_token_coverage",
        lambda *_args, **_kwargs: {
            "schema": deploy_module.VEXP_TOKEN_COVERAGE_SCHEMA,
            "status": "pass",
            "reason": "fresh_token_coverage_sufficient",
            "state_sha256": "4" * 64,
        },
    )

    evidence = lane._require_vexp_certification_token_coverage("preflight_entry")

    assert evidence["status"] == "pass"
    assert evidence["enforcement_decision"] == "owner_exception"
    assert lane.receipt["vexp_certification_completed"] is False
    assert lane.receipt["observed_vexp_token_coverage_passed"] is True
    assert lane.receipt["checks"][-1]["status"] == "owner_exception"
