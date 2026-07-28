from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app.services.workllm_governance import GovernedWorkLLMManualLane
from app.services.workllm_sidecar import WorkLLMConfig, WorkLLMSidecar

from scripts.evaluate_workllm_manual_canary import (
    build_manual_canary_receipt,
)
from scripts.materialize_workllm_account_verification import (
    build_account_receipt,
)


def _account_receipt(path: Path) -> str:
    account_ref = hashlib.sha256(b"fixture-account").hexdigest()
    screenshot_path = path.parent / "account-surface.png"
    screenshot_path.write_bytes(b"fixture-account-surface")
    screenshot_path.chmod(0o600)
    evidence_path = path.parent / "account-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema": (
                    "executive_assistant.workllm_browser_account_review.v1"
                ),
                "site": "girschele-workspace.workllm.io",
                "work_type": "account_review",
                "observed_at": "2026-07-28T09:00:00Z",
                "authenticated": True,
                "account_match": True,
                "account_ref_sha256": account_ref,
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
        ),
        encoding="utf-8",
    )
    evidence_path.chmod(0o600)
    build_account_receipt(
        evidence_path=evidence_path,
        output_path=path,
    )
    return account_ref


def _reviewed_run(
    *,
    root: Path,
    index: int,
    account_ref: str,
) -> dict[str, str]:
    config = WorkLLMConfig(
        workspace_url="girschele-workspace.workllm.io",
        account_verified=True,
        manual_lane_enabled=True,
        kill_switch_engaged=False,
        receipt_root=root / "runs",
        control_state_file=root / "control-state.json",
    )
    sidecar = WorkLLMSidecar(config)
    lane = GovernedWorkLLMManualLane(
        sidecar,
        governance_root=root / "governance",
    )
    task_id = f"canary-{index:02d}"
    packet = sidecar.prepare_task_packet(
        lane="research_synthesis",
        data_classification="public",
        prepared_context=f"Prepared context {index}.",
        source_manifest=[
            {
                "ref": "docs/approved-design.md",
                "sha256": hashlib.sha256(b"approved").hexdigest(),
            }
        ],
        prompt_template_id="canary",
        prompt_template_version="1",
        prompt_text="Return findings.",
        output_schema={
            "type": "object",
            "required": ["findings"],
            "properties": {"findings": {"type": "array"}},
        },
        max_credits=5,
        task_id=task_id,
        correlation_id=f"corr-{task_id}",
    )
    output_surface_path = root / f"surface-{index:02d}.png"
    output_surface_path.write_bytes(
        f"provider-output-{index}".encode()
    )
    output_surface_path.chmod(0o600)
    surface_path = root / f"surface-{index:02d}.json"
    surface_path.write_text(
        json.dumps(
            {
                "schema": (
                    "executive_assistant.workllm_browser_run_receipt.v1"
                ),
                "site": "girschele-workspace.workllm.io",
                "work_type": "research",
                "account_ref_sha256": account_ref,
                "request_sha256": packet.request_sha256,
                "prepared_packet_only": True,
                "output_captured": True,
                "observed_at": "2026-07-28T10:00:00Z",
                "provider_output_surface_sha256": hashlib.sha256(
                    output_surface_path.read_bytes()
                ).hexdigest(),
                "irreversible_actions_attempted": [],
                "stop_condition": "comparison_ready_for_user_decision",
            }
        ),
        encoding="utf-8",
    )
    surface_path.chmod(0o600)
    surface_sha256 = hashlib.sha256(surface_path.read_bytes()).hexdigest()
    lane.stage_packet(
        packet,
        actor_ref="fixture-operator",
        occurred_at="2026-07-28T09:57:00Z",
    )
    lane.authorize(
        packet,
        actor_ref="fixture-operator",
        authorized_at="2026-07-28T09:58:00Z",
    )
    captured = lane.capture(
        packet,
        output_text=f"Candidate result {index}.",
        actor_ref="fixture-operator",
        observed_models=("model-a",),
        credits_consumed=1,
        provider_surface_receipt_sha256=surface_sha256,
        captured_at="2026-07-28T09:59:00Z",
    )
    reviewed = lane.review(
        captured["receipt"],
        actor_ref="operator-1",
        decision="accepted_candidate",
        schema_valid=True,
        safety_valid=True,
        reviewed_at="2026-07-28T10:00:00Z",
    )
    run_path = Path(str(reviewed["receipt_path"]))
    return {
        "run_receipt": str(run_path),
        "provider_surface_receipt": str(surface_path),
        "provider_output_surface_artifact": str(output_surface_path),
    }


def _manifest(tmp_path: Path, *, run_count: int) -> Path:
    account_path = tmp_path / "account.json"
    account_ref = _account_receipt(account_path)
    runs = [
        _reviewed_run(root=tmp_path, index=index, account_ref=account_ref)
        for index in range(run_count)
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": (
                    "executive_assistant.workllm_canary_manifest.v1"
                ),
                "mode": "manual_browser",
                "account_verification_receipt": account_path.name,
                "governance": {
                    "audit_ledger": str(
                        tmp_path / "governance" / "audit.jsonl"
                    ),
                    "credit_ledger": str(
                        tmp_path
                        / "governance"
                        / "credit_ledger.json"
                    ),
                },
                "runs": runs,
            }
        ),
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)
    return manifest_path


def test_canary_materializer_requires_twenty_bound_real_runs(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path, run_count=20)

    receipt = build_manual_canary_receipt(
        manifest_path=manifest_path,
        output_path=tmp_path / "canary.json",
    )

    assert receipt["run_count"] == 20
    assert receipt["real_provider_run_count"] == 20
    assert receipt["provider_observed_count"] == 20
    assert receipt["promotion_eligible_candidate"] is True
    assert receipt["canonical_promotion_authority"] is False


def test_canary_materializer_keeps_nineteen_runs_incomplete(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path, run_count=19)

    receipt = build_manual_canary_receipt(
        manifest_path=manifest_path,
        output_path=tmp_path / "canary.json",
    )

    assert receipt["promotion_eligible_candidate"] is False
    assert "minimum_run_count_not_met" in receipt["failures"]


def test_canary_materializer_rejects_surface_digest_mismatch(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path, run_count=20)
    surface_path = tmp_path / "surface-00.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    surface["output_captured"] = False
    surface_path.write_text(json.dumps(surface), encoding="utf-8")

    with pytest.raises(
        SystemExit,
        match="workllm_provider_surface_output_missing:0",
    ):
        build_manual_canary_receipt(
            manifest_path=manifest_path,
            output_path=tmp_path / "canary.json",
        )


def test_canary_materializer_rejects_unbound_output_surface(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path, run_count=20)
    surface_path = tmp_path / "surface-00.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    surface.pop("provider_output_surface_sha256")
    surface_path.write_text(json.dumps(surface), encoding="utf-8")

    with pytest.raises(
        SystemExit,
        match="workllm_provider_output_surface_evidence_missing:0",
    ):
        build_manual_canary_receipt(
            manifest_path=manifest_path,
            output_path=tmp_path / "canary.json",
        )


def test_canary_materializer_rejects_tampered_output_surface_artifact(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path, run_count=20)
    output_surface_path = tmp_path / "surface-00.png"
    output_surface_path.write_bytes(b"tampered-provider-output")

    with pytest.raises(
        SystemExit,
        match="workllm_provider_output_surface_digest_mismatch:0",
    ):
        build_manual_canary_receipt(
            manifest_path=manifest_path,
            output_path=tmp_path / "canary.json",
        )


def test_canary_materializer_rejects_credit_ledger_mismatch(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path, run_count=20)
    credit_path = tmp_path / "governance" / "credit_ledger.json"
    credit = json.loads(credit_path.read_text(encoding="utf-8"))
    reservation = credit["reservations"]["canary-00"]
    reservation["consumed_credits"] = 2
    credit_path.write_text(json.dumps(credit), encoding="utf-8")
    credit_path.chmod(0o600)

    with pytest.raises(
        SystemExit,
        match="workllm_canary_credit_evidence_invalid:0",
    ):
        build_manual_canary_receipt(
            manifest_path=manifest_path,
            output_path=tmp_path / "canary.json",
        )
