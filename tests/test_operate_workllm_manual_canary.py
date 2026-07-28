from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.materialize_workllm_account_verification import (
    build_account_receipt,
)
from scripts.operate_workllm_manual_canary import (
    authorize_case,
    cancel_case,
    capture_case,
    engage_rollback,
    finalize_canary,
    rebind_surface_evidence,
    review_case,
    stage_browser_capture,
)
from scripts.prepare_workllm_manual_canary import (
    DEFAULT_CORPUS,
    prepare_manual_canary,
)


def _write_account_receipt(tmp_path: Path) -> tuple[Path, str]:
    account_ref = hashlib.sha256(b"fixture-account").hexdigest()
    screenshot_path = tmp_path / "account-surface.png"
    screenshot_path.write_bytes(b"account-surface")
    screenshot_path.chmod(0o600)
    evidence_path = tmp_path / "account-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema": (
                    "executive_assistant.workllm_browser_account_review.v1"
                ),
                "site": "girschele-workspace.workllm.io",
                "work_type": "account_review",
                "observed_at": "2026-07-28T05:00:00Z",
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
    account_path = tmp_path / "account-receipt.json"
    build_account_receipt(
        evidence_path=evidence_path,
        output_path=account_path,
    )
    return account_path, account_ref


def _write_env(path: Path, *, result_root: Path) -> None:
    path.write_text(
        "\n".join(
            (
                (
                    "WORKLLM_BASE_URL="
                    "https://girschele-workspace.workllm.io"
                ),
                "EA_WORKLLM_ACCOUNT_VERIFIED=1",
                "WORKLLM_PROVIDER_VERIFIED=0",
                "EA_WORKLLM_MANUAL_LANE_ENABLED=1",
                "WORKLLM_RUNTIME_ENABLED=0",
                "EA_WORKLLM_API_LANE_ENABLED=0",
                "EA_WORKLLM_KILL_SWITCH=0",
                f"EA_WORKLLM_RECEIPT_ROOT={result_root}",
                (
                    "EA_WORKLLM_CONTROL_STATE_FILE="
                    f"{result_root / 'control_state.json'}"
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_operator_runs_authorize_capture_review_without_false_finalize(
    tmp_path: Path,
) -> None:
    result_root = tmp_path / "runtime" / "workllm"
    preparation = prepare_manual_canary(
        corpus_path=DEFAULT_CORPUS,
        runtime_root=result_root / "canary-prepared",
        output_path=tmp_path / "preparation.json",
        batch_id="fixture-canary-v1",
        created_at="2026-07-28T05:00:00Z",
    )
    plan_path = Path(str(preparation["execution_plan_path"]))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    task = plan["tasks"][0]
    account_path, account_ref = _write_account_receipt(tmp_path)
    env_path = tmp_path / ".env"
    _write_env(env_path, result_root=result_root)

    authorization = authorize_case(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        actor_ref="fixture-operator",
        occurred_at="2026-07-28T05:01:00Z",
    )

    provider_output_path = Path(task["provider_output_capture_path"])
    provider_output_path.write_text(
        json.dumps(
            {
                "summary": "Candidate summary.",
                "findings": ["One finding."],
                "contradictions": [],
                "uncertainties": ["One uncertainty."],
                "recommendation": "Measure one reversible step.",
                "authority_statement": "Candidate only; no action taken.",
            }
        ),
        encoding="utf-8",
    )
    provider_output_path.chmod(0o600)
    surface_artifact_path = Path(
        task["provider_output_surface_artifact_path"]
    )
    surface_artifact_path.write_bytes(b"fixture-browser-surface")
    surface_artifact_path.chmod(0o600)
    surface_path = Path(task["provider_surface_receipt_path"])
    surface_path.write_text(
        json.dumps(
            {
                "schema": (
                    "executive_assistant.workllm_browser_run_receipt.v1"
                ),
                "site": "girschele-workspace.workllm.io",
                "work_type": "research",
                "account_ref_sha256": account_ref,
                "request_sha256": task["request_sha256"],
                "prepared_packet_only": True,
                "output_captured": True,
                "observed_at": "2026-07-28T05:02:00Z",
                "provider_output_surface_sha256": hashlib.sha256(
                    surface_artifact_path.read_bytes()
                ).hexdigest(),
                "irreversible_actions_attempted": [],
                "stop_condition": "comparison_ready_for_user_decision",
            }
        ),
        encoding="utf-8",
    )
    surface_path.chmod(0o600)

    capture = capture_case(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        actor_ref="fixture-operator",
        provider_output_path=provider_output_path,
        provider_surface_receipt_path=surface_path,
        provider_output_surface_artifact_path=surface_artifact_path,
        observed_models=["fixture-model"],
        credits_consumed=1,
        provider_job_ref="",
        captured_at="2026-07-28T05:02:00Z",
    )
    review = review_case(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        actor_ref="fixture-reviewer",
        decision="accepted_candidate",
        schema_status="passed",
        safety_status="passed",
        reviewed_at="2026-07-28T05:03:00Z",
    )

    assert authorization["credit_reservation_status"] == "reserved"
    assert authorization["provider_interaction_observed"] is False
    assert capture["credits_consumed"] == 1
    assert capture["observed_models"] == ["fixture-model"]
    assert review["candidate_accepted"] is True
    assert review["canonical_promotion_authority"] is False

    with pytest.raises(SystemExit, match="workllm_run_receipt_missing"):
        finalize_canary(
            plan_path=plan_path,
            env_path=env_path,
            account_path=account_path,
            manifest_path=tmp_path / "manifest.json",
            output_path=tmp_path / "canary.json",
        )


def test_operator_stages_validated_browser_capture_with_credit_ceiling(
    tmp_path: Path,
) -> None:
    result_root = tmp_path / "runtime" / "workllm"
    preparation = prepare_manual_canary(
        corpus_path=DEFAULT_CORPUS,
        runtime_root=result_root / "canary-prepared",
        output_path=tmp_path / "preparation.json",
        batch_id="fixture-canary-v1",
        created_at="2026-07-28T05:00:00Z",
    )
    plan_path = Path(str(preparation["execution_plan_path"]))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    task = plan["tasks"][0]
    account_path, _ = _write_account_receipt(tmp_path)
    env_path = tmp_path / ".env"
    _write_env(env_path, result_root=result_root)
    artifact_path = Path(task["provider_output_surface_artifact_path"])
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(b"fixture-browser-surface")
    artifact_path.chmod(0o600)

    staged = stage_browser_capture(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        provider_output_text=json.dumps(
            {
                "summary": "Candidate summary.",
                "findings": ["One finding."],
                "contradictions": [],
                "uncertainties": ["One uncertainty."],
                "recommendation": "Measure one reversible step.",
                "authority_statement": "Candidate only; no action taken.",
            }
        ),
        provider_output_surface_artifact_path=artifact_path,
        provider_credits_observed="2.451",
        observed_at="2026-07-28T05:02:00Z",
    )

    assert staged["credits_accounted"] == 3
    assert staged["canonical_promotion_authority"] is False
    output_path = Path(str(staged["provider_output_path"]))
    surface_path = Path(str(staged["provider_surface_receipt_path"]))
    assert output_path.stat().st_mode & 0o777 == 0o600
    assert surface_path.stat().st_mode & 0o777 == 0o600
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    assert surface["provider_credits_observed"] == "2.451"
    assert surface["credits_accounted"] == 3
    assert surface["provider_attempt_count"] == 1
    assert surface["aborted_attempt_credits_observed"] == "0"
    assert surface["provider_quality_caveats"] == []
    assert surface["provider_output_surface_sha256"] == hashlib.sha256(
        artifact_path.read_bytes()
    ).hexdigest()


def test_operator_records_identical_duplicate_key_normalization(
    tmp_path: Path,
) -> None:
    result_root = tmp_path / "runtime" / "workllm"
    preparation = prepare_manual_canary(
        corpus_path=DEFAULT_CORPUS,
        runtime_root=result_root / "canary-prepared",
        output_path=tmp_path / "preparation.json",
        batch_id="fixture-canary-v1",
        created_at="2026-07-28T05:00:00Z",
    )
    plan_path = Path(str(preparation["execution_plan_path"]))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    task = plan["tasks"][0]
    account_path, _ = _write_account_receipt(tmp_path)
    env_path = tmp_path / ".env"
    _write_env(env_path, result_root=result_root)
    artifact_path = Path(task["provider_output_surface_artifact_path"])
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(b"fixture-browser-surface")
    artifact_path.chmod(0o600)

    staged = stage_browser_capture(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        provider_output_text=(
            '{"summary":"Candidate summary.",'
            '"findings":[],"contradictions":[],"uncertainties":[],'
            '"recommendation":"Measure one reversible step.",'
            '"authority_statement":"Candidate only; no action taken.",'
            '"authority_statement":"Candidate only; no action taken."}'
        ),
        provider_output_surface_artifact_path=artifact_path,
        provider_credits_observed="1",
        observed_at="2026-07-28T05:02:00Z",
    )

    surface = json.loads(
        Path(str(staged["provider_surface_receipt_path"])).read_text(
            encoding="utf-8"
        )
    )
    assert surface["provider_output_normalizations"] == [
        "identical_duplicate_key_collapsed"
    ]
    assert surface["provider_output_duplicate_keys"] == [
        "authority_statement"
    ]


def test_operator_records_shared_batch_credit_observation(
    tmp_path: Path,
) -> None:
    result_root = tmp_path / "runtime" / "workllm"
    preparation = prepare_manual_canary(
        corpus_path=DEFAULT_CORPUS,
        runtime_root=result_root / "canary-prepared",
        output_path=tmp_path / "preparation.json",
        batch_id="fixture-canary-v1",
        created_at="2026-07-28T05:00:00Z",
    )
    plan_path = Path(str(preparation["execution_plan_path"]))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    task = plan["tasks"][0]
    account_path, _ = _write_account_receipt(tmp_path)
    env_path = tmp_path / ".env"
    _write_env(env_path, result_root=result_root)
    artifact_path = Path(task["provider_output_surface_artifact_path"])
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(b"fixture-browser-surface")
    artifact_path.chmod(0o600)

    staged = stage_browser_capture(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        provider_output_text=json.dumps(
            {
                "summary": "Candidate summary.",
                "findings": [],
                "contradictions": [],
                "uncertainties": [],
                "recommendation": "Measure one reversible step.",
                "authority_statement": "Candidate only; no action taken.",
            }
        ),
        provider_output_surface_artifact_path=artifact_path,
        provider_credits_observed="5.102",
        observed_at="2026-07-28T05:02:00Z",
        provider_credit_observation_scope="shared_batch_delta",
        shared_batch_case_ids=["01", "02"],
    )

    assert staged["credits_accounted"] == 6
    surface = json.loads(
        Path(str(staged["provider_surface_receipt_path"])).read_text(
            encoding="utf-8"
        )
    )
    assert surface["provider_credit_observation_scope"] == (
        "shared_batch_delta"
    )
    assert surface["shared_batch_case_ids"] == ["01", "02"]


def test_operator_rebinds_replaced_surface_and_requires_new_review(
    tmp_path: Path,
) -> None:
    result_root = tmp_path / "runtime" / "workllm"
    preparation = prepare_manual_canary(
        corpus_path=DEFAULT_CORPUS,
        runtime_root=result_root / "canary-prepared",
        output_path=tmp_path / "preparation.json",
        batch_id="fixture-canary-v1",
        created_at="2026-07-28T05:00:00Z",
    )
    plan_path = Path(str(preparation["execution_plan_path"]))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    task = plan["tasks"][0]
    account_path, account_ref = _write_account_receipt(tmp_path)
    env_path = tmp_path / ".env"
    _write_env(env_path, result_root=result_root)
    authorize_case(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        actor_ref="fixture-operator",
        occurred_at="2026-07-28T05:01:00Z",
    )
    artifact_path = Path(task["provider_output_surface_artifact_path"])
    artifact_path.write_bytes(b"original-surface")
    artifact_path.chmod(0o600)
    candidate = json.dumps(
        {
            "summary": "Candidate summary.",
            "findings": [],
            "contradictions": [],
            "uncertainties": [],
            "recommendation": "Measure one reversible step.",
            "authority_statement": "Candidate only; no action taken.",
        },
        indent=2,
        sort_keys=True,
    ) + "\n"
    staged = stage_browser_capture(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        provider_output_text=candidate,
        provider_output_surface_artifact_path=artifact_path,
        provider_credits_observed="1",
        observed_at="2026-07-28T05:02:00Z",
    )
    capture_case(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        actor_ref="fixture-operator",
        provider_output_path=Path(str(staged["provider_output_path"])),
        provider_surface_receipt_path=Path(
            str(staged["provider_surface_receipt_path"])
        ),
        provider_output_surface_artifact_path=artifact_path,
        observed_models=["fixture-model"],
        credits_consumed=1,
        provider_job_ref="fixture-job",
        captured_at="2026-07-28T05:02:00Z",
    )
    artifact_path.write_bytes(b"replacement-surface")
    artifact_path.chmod(0o600)
    replacement_surface = json.loads(
        Path(str(staged["provider_surface_receipt_path"])).read_text(
            encoding="utf-8"
        )
    )
    replacement_surface["provider_output_surface_sha256"] = hashlib.sha256(
        artifact_path.read_bytes()
    ).hexdigest()
    surface_path = Path(str(staged["provider_surface_receipt_path"]))
    surface_path.write_text(
        json.dumps(replacement_surface),
        encoding="utf-8",
    )
    surface_path.chmod(0o600)

    rebound = rebind_surface_evidence(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        reason="Duplicate staging replaced browser evidence.",
        rebound_at="2026-07-28T05:03:00Z",
    )

    assert rebound["review_required"] is True
    run = json.loads(
        Path(str(rebound["run_receipt_path"])).read_text(encoding="utf-8")
    )
    assert run["human_review"]["status"] == "pending"
    assert run["candidate_accepted"] is False
    assert (
        run["provider_surface_receipt_sha256"]
        == hashlib.sha256(surface_path.read_bytes()).hexdigest()
    )
    with pytest.raises(
        SystemExit,
        match="workllm_browser_capture_already_finalized",
    ):
        stage_browser_capture(
            plan_path=plan_path,
            case_id="01",
            env_path=env_path,
            account_path=account_path,
            provider_output_text=candidate,
            provider_output_surface_artifact_path=artifact_path,
            provider_credits_observed="1",
            observed_at="2026-07-28T05:04:00Z",
        )


def test_operator_rejects_plan_artifact_path_escape(
    tmp_path: Path,
) -> None:
    result_root = tmp_path / "runtime" / "workllm"
    preparation = prepare_manual_canary(
        corpus_path=DEFAULT_CORPUS,
        runtime_root=result_root / "canary-prepared",
        output_path=tmp_path / "preparation.json",
        batch_id="fixture-canary-v1",
        created_at="2026-07-28T05:00:00Z",
    )
    plan_path = Path(str(preparation["execution_plan_path"]))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["tasks"][0]["provider_output_capture_path"] = str(
        tmp_path / "outside-result-root.txt"
    )
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    plan_path.chmod(0o600)
    env_path = tmp_path / ".env"
    _write_env(env_path, result_root=result_root)

    with pytest.raises(
        SystemExit,
        match="workllm_canary_plan_contract_invalid",
    ):
        authorize_case(
            plan_path=plan_path,
            case_id="01",
            env_path=env_path,
            account_path=tmp_path / "unused-account.json",
            actor_ref="fixture-operator",
            occurred_at="2026-07-28T05:01:00Z",
        )


def test_operator_can_cancel_reservation_and_engage_rollback(
    tmp_path: Path,
) -> None:
    result_root = tmp_path / "runtime" / "workllm"
    preparation = prepare_manual_canary(
        corpus_path=DEFAULT_CORPUS,
        runtime_root=result_root / "canary-prepared",
        output_path=tmp_path / "preparation.json",
        batch_id="fixture-canary-v1",
        created_at="2026-07-28T05:00:00Z",
    )
    plan_path = Path(str(preparation["execution_plan_path"]))
    account_path, _ = _write_account_receipt(tmp_path)
    env_path = tmp_path / ".env"
    _write_env(env_path, result_root=result_root)
    authorize_case(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        account_path=account_path,
        actor_ref="fixture-operator",
        occurred_at="2026-07-28T05:01:00Z",
    )

    cancellation = cancel_case(
        plan_path=plan_path,
        case_id="01",
        env_path=env_path,
        actor_ref="fixture-operator",
        reason="Operator cancelled the unused reservation.",
        cancelled_at="2026-07-28T05:02:00Z",
    )
    rollback = engage_rollback(
        env_path=env_path,
        actor_ref="fixture-operator",
        reason="Operator requested a fail-closed stop.",
        engaged_at="2026-07-28T05:03:00Z",
    )

    assert cancellation["credit_reservation_status"] == "cancelled"
    assert cancellation["canonical_promotion_authority"] is False
    assert rollback["kill_switch_effective"] is True
    assert Path(str(rollback["control_state_path"])).is_file()
    assert rollback["canonical_promotion_authority"] is False
