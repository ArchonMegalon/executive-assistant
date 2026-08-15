from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

from scripts.audit_workllm_goal import (
    _account_receipt_provenance_valid,
    _manual_canary_provenance_valid,
    build_goal_audit,
)


def _write_env(path: Path) -> None:
    path.write_text(
        """\
WORKLLM_BASE_URL=https://workspace.example.test
WORKLLM_EMAIL=fixture@example.test
WORKLLM_PASSWORD=fixture-password
EA_WORKLLM_ACCOUNT_VERIFIED=0
WORKLLM_PROVIDER_VERIFIED=0
EA_WORKLLM_MANUAL_LANE_ENABLED=0
WORKLLM_RUNTIME_ENABLED=0
EA_WORKLLM_API_LANE_ENABLED=0
EA_WORKLLM_KILL_SWITCH=1
""",
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_goal_audit_stays_incomplete_without_account_and_real_canary(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    output_path = tmp_path / "goal-audit.json"
    local_contract_path = tmp_path / "local-contract.json"
    _write_env(env_path)
    local_contract_path.write_text(
        json.dumps(
            {
                "verdict": "CANDIDATE_ONLY",
                "checks": {
                    "local_contract_ready": True,
                    "persistent_credit_audit_review": True,
                    "durable_rollback_override": True,
                },
                "authority": {"canonical_write_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    local_contract_path.chmod(0o600)

    receipt = build_goal_audit(
        env_path=env_path,
        output_path=output_path,
        local_contract_receipt=local_contract_path,
        account_verification_receipt=tmp_path / "missing-account.json",
        manual_canary_receipt=tmp_path / "missing-canary.json",
    )
    serialized = json.dumps(receipt)

    assert output_path.is_file()
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert receipt["goal_ready"] is False
    assert receipt["verdict"] == "INCOMPLETE"
    assert "authenticated_account_capabilities" in receipt["unmet_requirements"]
    assert "manual_lane_canary" in receipt["unmet_requirements"]
    assert (
        receipt["requirements"]["local_sidecar_governance"]["status"]
        == "achieved"
    )
    assert "local_sidecar_governance" not in receipt["unmet_requirements"]
    assert receipt["promotion"]["manual_lane_promoted"] is False
    assert receipt["promotion"]["api_lane_promoted"] is False
    assert "fixture@example.test" not in serialized
    assert "fixture-password" not in serialized


def test_goal_audit_accepts_disabled_api_lane_without_fake_api_proof(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    output_path = tmp_path / "goal-audit.json"
    _write_env(env_path)

    receipt = build_goal_audit(
        env_path=env_path,
        output_path=output_path,
        account_verification_receipt=tmp_path / "missing-account.json",
        manual_canary_receipt=tmp_path / "missing-canary.json",
    )

    assert (
        receipt["requirements"]["unattended_api_boundary"]["status"]
        == "achieved"
    )
    assert receipt["runtime_flags"]["WORKLLM_RUNTIME_ENABLED"] is False
    assert receipt["runtime_flags"]["EA_WORKLLM_API_LANE_ENABLED"] is False


def test_account_goal_evidence_requires_matching_source_digest(
    tmp_path: Path,
) -> None:
    account_ref = hashlib.sha256(b"fixture-account").hexdigest()
    screenshot_path = tmp_path / "browser-state.png"
    screenshot_path.write_bytes(b"browser-state")
    screenshot_path.chmod(0o600)
    screenshot = hashlib.sha256(
        screenshot_path.read_bytes()
    ).hexdigest()
    screenshot_artifacts = [
        {"path": str(screenshot_path), "sha256": screenshot}
    ]
    source = {
        "schema": "executive_assistant.workllm_browser_account_review.v1",
        "authenticated": True,
        "account_match": True,
        "account_ref_sha256": account_ref,
        "data_uploaded": False,
        "irreversible_actions_attempted": [],
        "final_surface_url": (
            "https://girschele-workspace.workllm.io/settings/usage"
        ),
        "screenshot_artifacts": screenshot_artifacts,
    }
    source_path = tmp_path / "account-evidence.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    source_path.chmod(0o600)
    receipt = {
        "account_ref_sha256": account_ref,
        "evidence": {
            "source_path": str(source_path),
            "source_sha256": hashlib.sha256(
                source_path.read_bytes()
            ).hexdigest(),
            "final_surface_url": source["final_surface_url"],
            "screenshot_artifacts": screenshot_artifacts,
            "screenshot_sha256": [screenshot],
        },
        "authority": {
            "canonical_write_allowed": False,
            "repo_write_allowed": False,
            "external_send_allowed": False,
            "publish_allowed": False,
            "approval_allowed": False,
        },
    }

    assert _account_receipt_provenance_valid(receipt) is True

    source["data_uploaded"] = True
    source_path.write_text(json.dumps(source), encoding="utf-8")
    assert _account_receipt_provenance_valid(receipt) is False


def test_goal_audit_rejects_plausible_but_unbound_canary_receipt() -> None:
    forged = {
        "run_count": 20,
        "unique_task_count": 20,
        "receipt_contract_count": 20,
        "source_bound_count": 20,
        "safety_passed_count": 20,
        "reviewed_count": 20,
        "credits_observed_count": 20,
        "provider_observed_count": 20,
        "authority_safe_count": 20,
        "real_provider_run_count": 20,
        "schema_success_rate": 1.0,
        "failures": [],
        "promotion_eligible_candidate": True,
        "canonical_promotion_authority": False,
    }

    assert (
        _manual_canary_provenance_valid(
            forged,
            account_receipt={"account_ref_sha256": "0" * 64},
        )
        is False
    )
