from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
from app.services.workllm_sidecar import (
    WORKLLM_RUN_RECEIPT_SCHEMA,
    WORKLLM_TASK_PACKET_SCHEMA,
    WorkLLMConfig,
    WorkLLMPolicyError,
    WorkLLMSidecar,
    WorkLLMTaskPacket,
    evaluate_workllm_canary,
)


def _source_manifest() -> list[dict[str, str]]:
    return [
        {
            "ref": "docs/approved-design.md",
            "sha256": hashlib.sha256(b"approved design").hexdigest(),
        }
    ]


def _packet(
    sidecar: WorkLLMSidecar,
    *,
    prepared_context: str = "Compare the approved design against the test evidence.",
    data_classification: str = "internal_nonsecret",
    source_manifest: list[dict[str, str]] | None = None,
    task_id: str = "workllm-test-1",
):
    return sidecar.prepare_task_packet(
        lane="multi_model_compare",
        data_classification=data_classification,
        prepared_context=prepared_context,
        source_manifest=source_manifest or _source_manifest(),
        prompt_template_id="fleet-research-critic",
        prompt_template_version="1",
        prompt_text="Return findings bound to the supplied source manifest.",
        output_schema={
            "type": "object",
            "required": ["findings"],
            "properties": {"findings": {"type": "array"}},
        },
        max_credits=50,
        task_id=task_id,
        correlation_id=f"corr-{task_id}",
        created_at="2026-07-27T10:00:00Z",
    )


def test_default_configuration_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "WORKLLM_BASE_URL",
        "EA_WORKLLM_ACCOUNT_VERIFIED",
        "WORKLLM_PROVIDER_VERIFIED",
        "EA_WORKLLM_MANUAL_LANE_ENABLED",
        "WORKLLM_RUNTIME_ENABLED",
        "EA_WORKLLM_API_LANE_ENABLED",
        "EA_WORKLLM_KILL_SWITCH",
    ):
        monkeypatch.delenv(name, raising=False)

    config = WorkLLMConfig.from_environment()

    assert config.account_verified is False
    assert config.provider_verified is False
    assert config.manual_lane_enabled is False
    assert config.internal_nonsecret_enabled is False
    assert config.runtime_enabled is False
    assert config.api_lane_enabled is False
    assert config.kill_switch_engaged is True
    assert config.api_proof_complete is False


def test_environment_rejects_non_binary_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_WORKLLM_KILL_SWITCH", "false")

    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_configuration_invalid:EA_WORKLLM_KILL_SWITCH",
    ):
        WorkLLMConfig.from_environment()


def test_task_packet_redacts_identity_and_secrets_and_denies_authority() -> None:
    sidecar = WorkLLMSidecar(WorkLLMConfig())

    packet = _packet(
        sidecar,
        prepared_context=(
            "Research owner@example.test with password=hunter42 and "
            "Authorization: Bearer abcdefghijklmnop."
        ),
    )
    payload = packet.to_dict()
    serialized = json.dumps(payload)

    assert payload["schema"] == WORKLLM_TASK_PACKET_SCHEMA
    assert "owner@example.test" not in serialized
    assert "hunter42" not in serialized
    assert "abcdefghijklmnop" not in serialized
    assert "[REDACTED_EMAIL]" in payload["prepared_context"]
    assert "[REDACTED_SECRET]" in payload["prepared_context"]
    assert "[REDACTED_TOKEN]" in payload["prepared_context"]
    assert payload["authority"] == {
        "candidate_only": True,
        "canonical_write_allowed": False,
        "repo_write_allowed": False,
        "external_send_allowed": False,
        "publish_allowed": False,
        "approval_allowed": False,
    }
    assert payload["retention"]["organization_memory_write_allowed"] is False
    packet.verify_digest()


def test_task_packet_round_trips_from_persisted_contract() -> None:
    packet = _packet(WorkLLMSidecar(WorkLLMConfig()))

    restored = WorkLLMTaskPacket.from_dict(packet.to_dict())

    assert restored == packet
    restored.verify_digest()


def test_task_packet_restore_rejects_recomputed_authority_escalation() -> None:
    packet = _packet(WorkLLMSidecar(WorkLLMConfig()))
    payload = packet.to_dict()
    payload["authority"]["repo_write_allowed"] = True
    payload_without_digest = dict(payload)
    payload_without_digest.pop("request_sha256")
    canonical = json.dumps(
        payload_without_digest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload["request_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_task_packet_digest_mismatch",
    ):
        WorkLLMTaskPacket.from_dict(payload)


def test_task_packet_restore_rejects_recomputed_sensitive_context() -> None:
    packet = _packet(WorkLLMSidecar(WorkLLMConfig()))
    payload = packet.to_dict()
    payload["prepared_context"] = "Contact owner@example.test."
    payload_without_digest = dict(payload)
    payload_without_digest.pop("request_sha256")
    canonical = json.dumps(
        payload_without_digest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload["request_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_task_packet_contains_sensitive_data",
    ):
        WorkLLMTaskPacket.from_dict(payload)


@pytest.mark.parametrize(
    "classification",
    ["confidential", "restricted", "personal", "secret"],
)
def test_task_packet_rejects_unapproved_data_classes(
    classification: str,
) -> None:
    sidecar = WorkLLMSidecar(WorkLLMConfig())

    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_data_classification_forbidden",
    ):
        _packet(sidecar, data_classification=classification)


@pytest.mark.parametrize(
    "source_ref",
    [
        ".env",
        ".env.local",
        "config/secrets/provider.json",
        "memorial_data/private_memorial_profiles/person/profile.json",
        "../outside.md",
        "https://example.test/raw",
    ],
)
def test_task_packet_rejects_forbidden_source_references(
    source_ref: str,
) -> None:
    sidecar = WorkLLMSidecar(WorkLLMConfig())

    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_source_ref_forbidden",
    ):
        _packet(
            sidecar,
            source_manifest=[
                {
                    "ref": source_ref,
                    "sha256": hashlib.sha256(b"source").hexdigest(),
                }
            ],
        )


def test_manual_submission_requires_verified_enabled_account() -> None:
    packet = _packet(WorkLLMSidecar(WorkLLMConfig()))
    sidecar = WorkLLMSidecar(
        WorkLLMConfig(
            workspace_url="https://workspace.example.test",
            kill_switch_engaged=False,
        )
    )

    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_account_unverified",
    ):
        sidecar.authorize_submission(
            packet,
            mode="manual_browser",
            monthly_credits_used=0,
        )


def test_manual_submission_is_bounded_by_credit_envelope() -> None:
    config = WorkLLMConfig(
        workspace_url="workspace.example.test",
        account_verified=True,
        manual_lane_enabled=True,
        internal_nonsecret_enabled=True,
        kill_switch_engaged=False,
        monthly_credit_limit=100,
        soft_credit_limit=70,
        hard_credit_limit=90,
        max_task_credits=50,
    )
    sidecar = WorkLLMSidecar(config)
    packet = _packet(sidecar)

    authorization = sidecar.authorize_submission(
        packet,
        mode="manual_browser",
        monthly_credits_used=25,
    )

    assert authorization["authorized"] is True
    assert authorization["projected_monthly_credits"] == 75
    assert authorization["soft_limit_exceeded"] is True
    assert authorization["canonical_authority"] is False

    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_hard_credit_limit_exceeded",
    ):
        sidecar.authorize_submission(
            packet,
            mode="manual_browser",
            monthly_credits_used=50,
        )


def test_internal_nonsecret_submission_requires_separate_enablement() -> None:
    sidecar = WorkLLMSidecar(
        WorkLLMConfig(
            workspace_url="workspace.example.test",
            account_verified=True,
            manual_lane_enabled=True,
            kill_switch_engaged=False,
        )
    )
    packet = _packet(sidecar, data_classification="internal_nonsecret")

    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_internal_nonsecret_disabled",
    ):
        sidecar.authorize_submission(
            packet,
            mode="manual_browser",
            monthly_credits_used=0,
        )


def test_api_submission_requires_every_proof_gate() -> None:
    config = WorkLLMConfig(
        workspace_url="workspace.example.test",
        provider_verified=True,
        runtime_enabled=True,
        api_lane_enabled=True,
        kill_switch_engaged=False,
        api_contract_verified=True,
        model_provenance_verified=True,
        usage_telemetry_verified=True,
        idempotency_verified=True,
        retention_controls_verified=True,
        webhook_controls_verified=False,
    )
    sidecar = WorkLLMSidecar(config)
    packet = _packet(sidecar)

    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_api_proof_incomplete",
    ):
        sidecar.authorize_submission(
            packet,
            mode="api",
            monthly_credits_used=0,
        )


def test_result_receipt_contains_hashes_and_no_provider_output() -> None:
    config = WorkLLMConfig(workspace_url="workspace.example.test")
    sidecar = WorkLLMSidecar(config)
    packet = _packet(sidecar)

    receipt, redacted_output = sidecar.capture_result(
        packet,
        output_text=(
            "Candidate finding for reviewer@example.test; "
            "access_token=abcdefghijklmno."
        ),
        mode="manual_browser",
        observed_models=("model-a", "model-a", "model-b"),
        credits_consumed=12,
        provider_job_ref="provider-job-123",
        captured_at="2026-07-27T10:05:00Z",
    )
    serialized = json.dumps(receipt)

    assert receipt["schema"] == WORKLLM_RUN_RECEIPT_SCHEMA
    assert receipt["observed_models"] == ["model-a", "model-b"]
    assert receipt["model_provenance_status"] == "observed"
    assert receipt["credits_consumed"] == 12
    assert receipt["provider_interaction_observed"] is False
    assert receipt["evidence_kind"] == "synthetic_or_unverified"
    assert receipt["source_binding_status"] == "bound"
    assert receipt["authority"]["canonical_write_allowed"] is False
    assert "provider-job-123" not in serialized
    assert "reviewer@example.test" not in serialized
    assert "abcdefghijklmno" not in serialized
    assert "[REDACTED_EMAIL]" in redacted_output
    assert "[REDACTED_SECRET]" in redacted_output


def test_manual_result_persistence_uses_private_permissions(
    tmp_path: Path,
) -> None:
    sidecar = WorkLLMSidecar(
        WorkLLMConfig(
            workspace_url="workspace.example.test",
            receipt_root=tmp_path / "workllm",
        )
    )
    packet = _packet(sidecar)

    receipt = sidecar.persist_manual_result(
        packet,
        output_text="Candidate-only finding.",
        observed_models=("model-a",),
        credits_consumed=3,
        captured_at="2026-07-27T10:05:00Z",
    )

    paths = {
        key: Path(value)
        for key, value in receipt["local_artifacts"].items()
    }
    assert set(paths) == {"task_packet", "result", "run_receipt"}
    for path in paths.values():
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(paths["result"].parent.stat().st_mode) == 0o700


def test_human_review_accepts_candidate_without_granting_promotion() -> None:
    sidecar = WorkLLMSidecar(
        WorkLLMConfig(workspace_url="workspace.example.test")
    )
    packet = _packet(sidecar)
    receipt, _ = sidecar.capture_result(
        packet,
        output_text="Candidate-only finding.",
        mode="manual_browser",
    )

    reviewed = sidecar.mark_reviewed(
        receipt,
        reviewer_ref="operator-1",
        decision="accepted_candidate",
        schema_valid=True,
        safety_valid=True,
        reviewed_at="2026-07-27T10:10:00Z",
    )

    assert reviewed["candidate_accepted"] is True
    assert reviewed["canonical_promotion_authority"] is False
    assert reviewed["human_review"]["status"] == "completed"
    assert reviewed["human_review"]["reviewer_ref_sha256"] != "operator-1"


def _reviewed_receipts(
    sidecar: WorkLLMSidecar,
    *,
    count: int,
    mode: str = "manual_browser",
    observed_models: tuple[str, ...] = ("model-a",),
) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    for index in range(count):
        packet = _packet(sidecar, task_id=f"canary-{index:02d}")
        receipt, _ = sidecar.capture_result(
            packet,
            output_text=f"Candidate finding {index}.",
            mode=mode,
            observed_models=observed_models,
            credits_consumed=1,
            provider_interaction_observed=True,
            provider_surface_receipt_sha256=hashlib.sha256(
                f"provider-surface-{index}".encode()
            ).hexdigest(),
        )
        receipts.append(
            sidecar.mark_reviewed(
                receipt,
                reviewer_ref="operator-1",
                decision="accepted_candidate",
                schema_valid=True,
                safety_valid=True,
            )
        )
    return receipts


def test_manual_canary_requires_twenty_fully_reviewed_receipts() -> None:
    sidecar = WorkLLMSidecar(
        WorkLLMConfig(workspace_url="workspace.example.test")
    )

    incomplete = evaluate_workllm_canary(
        _reviewed_receipts(sidecar, count=19),
        mode="manual_browser",
    )
    complete = evaluate_workllm_canary(
        _reviewed_receipts(sidecar, count=20),
        mode="manual_browser",
    )

    assert incomplete["promotion_eligible_candidate"] is False
    assert "minimum_run_count_not_met" in incomplete["failures"]
    assert complete["promotion_eligible_candidate"] is True
    assert complete["schema_success_rate"] == 1.0
    assert complete["authority_safe_count"] == 20
    assert complete["provider_observed_count"] == 20
    assert complete["canonical_promotion_authority"] is False


def test_api_canary_requires_model_provenance_for_every_run() -> None:
    sidecar = WorkLLMSidecar(
        WorkLLMConfig(workspace_url="workspace.example.test")
    )

    evaluation = evaluate_workllm_canary(
        _reviewed_receipts(
            sidecar,
            count=20,
            mode="api",
            observed_models=(),
        ),
        mode="api",
    )

    assert evaluation["promotion_eligible_candidate"] is False
    assert "model_provenance_incomplete" in evaluation["failures"]


def test_manual_canary_rejects_nonaccepted_review_decision() -> None:
    sidecar = WorkLLMSidecar(
        WorkLLMConfig(workspace_url="workspace.example.test")
    )
    receipts = _reviewed_receipts(sidecar, count=20)
    receipts[0] = sidecar.mark_reviewed(
        receipts[0],
        reviewer_ref="operator-1",
        decision="rejected",
        schema_valid=True,
        safety_valid=True,
    )

    evaluation = evaluate_workllm_canary(
        receipts,
        mode="manual_browser",
    )

    assert evaluation["promotion_eligible_candidate"] is False
    assert "candidate_acceptance_incomplete" in evaluation["failures"]


def test_canary_threshold_cannot_be_shrunk_below_twenty() -> None:
    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_canary_minimum_too_small",
    ):
        evaluate_workllm_canary([], mode="manual_browser", minimum_runs=5)


def test_real_canary_rejects_synthetic_or_unverified_receipts() -> None:
    sidecar = WorkLLMSidecar(
        WorkLLMConfig(workspace_url="workspace.example.test")
    )
    receipts: list[dict[str, object]] = []
    for index in range(20):
        packet = _packet(sidecar, task_id=f"synthetic-{index:02d}")
        receipt, _ = sidecar.capture_result(
            packet,
            output_text="Synthetic result.",
            mode="manual_browser",
            credits_consumed=1,
        )
        receipts.append(
            sidecar.mark_reviewed(
                receipt,
                reviewer_ref="operator-1",
                decision="accepted_candidate",
                schema_valid=True,
                safety_valid=True,
            )
        )

    evaluation = evaluate_workllm_canary(
        receipts,
        mode="manual_browser",
    )

    assert evaluation["promotion_eligible_candidate"] is False
    assert (
        "provider_interaction_evidence_incomplete"
        in evaluation["failures"]
    )
