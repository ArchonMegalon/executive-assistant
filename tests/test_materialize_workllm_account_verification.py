from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from scripts.materialize_workllm_account_verification import (
    build_account_receipt,
)


def _evidence(tmp_path: Path) -> dict[str, object]:
    screenshot_path = tmp_path / "account-surface.png"
    screenshot_path.write_bytes(b"fixture-screenshot")
    screenshot_path.chmod(0o600)
    return {
        "schema": "executive_assistant.workllm_browser_account_review.v1",
        "site": "girschele-workspace.workllm.io",
        "work_type": "account_review",
        "observed_at": "2026-07-27T21:00:00Z",
        "authenticated": True,
        "account_match": True,
        "account_ref_sha256": hashlib.sha256(
            b"fixture-account"
        ).hexdigest(),
        "data_uploaded": False,
        "irreversible_actions_attempted": [],
        "final_surface_url": (
            "https://girschele-workspace.workllm.io/settings/usage"
        ),
        "screenshot_artifacts": [
            {
                "path": str(screenshot_path),
                "sha256": hashlib.sha256(
                    screenshot_path.read_bytes()
                ).hexdigest(),
            }
        ],
        "plan": {
            "commercial_tier": "Tier 4 / Pro",
            "monthly_ai_credits": 8000,
            "unlimited_users": True,
        },
        "capabilities": {
            "multi_llm_chat": True,
            "deep_research": True,
            "document_chat": True,
            "multimedia_chat": True,
            "organization_memory": True,
            "agents": True,
        },
        "controls": {
            "rbac_visible": True,
            "audit_log_visible": True,
            "usage_reporting_visible": True,
            "export_control_visible": False,
            "deletion_control_visible": False,
            "retention_control_visible": False,
        },
        "agent_surfaces": {
            "knowledge_agents_visible": True,
            "task_agents_visible": True,
            "workflow_agents_visible": True,
        },
        "api_observation": {
            "machine_api_observed": False,
            "service_auth_observed": False,
            "usage_endpoint_observed": False,
            "webhook_signing_observed": False,
            "idempotency_observed": False,
            "model_identity_observed": False,
        },
    }


def test_account_verifier_promotes_only_manual_workbench(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "evidence.json"
    output_path = tmp_path / "receipt.json"
    evidence_path.write_text(
        json.dumps(_evidence(tmp_path), indent=2) + "\n",
        encoding="utf-8",
    )
    evidence_path.chmod(0o600)

    receipt = build_account_receipt(
        evidence_path=evidence_path,
        output_path=output_path,
    )

    assert output_path.is_file()
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert receipt["verdict"] == "VERIFIED_MANUAL_WORKBENCH"
    assert receipt["manual_workbench_verified"] is True
    assert receipt["manual_data_classes"] == ["public"]
    assert receipt["internal_nonsecret_eligible"] is False
    assert receipt["api_lane_eligible"] is False
    assert receipt["organization_memory_eligible"] is False
    assert receipt["authority"]["canonical_write_allowed"] is False
    assert any(
        "organization memory" in reason.lower()
        for reason in receipt["blocking_reasons"]
    )


def test_account_verifier_allows_public_manual_lane_without_provider_admin_controls(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    evidence["controls"] = {
        key: False for key in evidence["controls"]
    }
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    evidence_path.chmod(0o600)

    receipt = build_account_receipt(
        evidence_path=evidence_path,
        output_path=tmp_path / "receipt.json",
    )

    assert receipt["verdict"] == "VERIFIED_MANUAL_WORKBENCH"
    assert receipt["manual_workbench_verified"] is True
    assert receipt["provider_admin_controls_observed"] is False
    assert receipt["manual_data_classes"] == ["public"]
    assert receipt["internal_nonsecret_eligible"] is False


def test_account_verifier_rejects_sensitive_browser_evidence(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    evidence["login_email"] = "owner@example.test"
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    evidence_path.chmod(0o600)

    with pytest.raises(
        SystemExit,
        match="workllm_account_evidence_contains_sensitive_data",
    ):
        build_account_receipt(
            evidence_path=evidence_path,
            output_path=tmp_path / "receipt.json",
        )


def test_account_verifier_rejects_account_mismatch(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    evidence["account_match"] = False
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    evidence_path.chmod(0o600)

    with pytest.raises(
        SystemExit,
        match="workllm_account_context_mismatch",
    ):
        build_account_receipt(
            evidence_path=evidence_path,
            output_path=tmp_path / "receipt.json",
        )


def test_account_verifier_requires_bound_browser_evidence(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    evidence["screenshot_artifacts"] = []
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    evidence_path.chmod(0o600)

    with pytest.raises(
        SystemExit,
        match="workllm_account_screenshot_evidence_missing",
    ):
        build_account_receipt(
            evidence_path=evidence_path,
            output_path=tmp_path / "receipt.json",
        )


def test_account_verifier_rejects_non_tenant_final_surface(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    evidence["final_surface_url"] = "https://example.test/settings/usage"
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    evidence_path.chmod(0o600)

    with pytest.raises(
        SystemExit,
        match="workllm_account_final_surface_invalid",
    ):
        build_account_receipt(
            evidence_path=evidence_path,
            output_path=tmp_path / "receipt.json",
        )


def test_account_verifier_rejects_mismatched_screenshot_artifact(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    evidence_path.chmod(0o600)
    screenshot_path = Path(
        str(evidence["screenshot_artifacts"][0]["path"])
    )
    screenshot_path.write_bytes(b"tampered-after-observation")

    with pytest.raises(
        SystemExit,
        match="workllm_account_screenshot_evidence_invalid",
    ):
        build_account_receipt(
            evidence_path=evidence_path,
            output_path=tmp_path / "receipt.json",
        )
