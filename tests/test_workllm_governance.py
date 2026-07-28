from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
from app.services.workllm_governance import (
    GovernedWorkLLMManualLane,
    WorkLLMAuditLedger,
    WorkLLMCreditLedger,
    WorkLLMGovernanceError,
)
from app.services.workllm_sidecar import (
    WorkLLMConfig,
    WorkLLMPolicyError,
    WorkLLMSidecar,
)


def _config(tmp_path: Path) -> WorkLLMConfig:
    return WorkLLMConfig(
        workspace_url="workspace.example.test",
        account_verified=True,
        manual_lane_enabled=True,
        internal_nonsecret_enabled=True,
        kill_switch_engaged=False,
        monthly_credit_limit=100,
        soft_credit_limit=70,
        hard_credit_limit=90,
        max_task_credits=50,
        receipt_root=tmp_path / "runs",
        control_state_file=tmp_path / "control" / "workllm.json",
    )


def _packet(
    sidecar: WorkLLMSidecar,
    *,
    task_id: str,
    max_credits: int = 25,
):
    return sidecar.prepare_task_packet(
        lane="multi_model_compare",
        data_classification="internal_nonsecret",
        prepared_context="Compare approved design evidence.",
        source_manifest=[
            {
                "ref": "docs/approved-design.md",
                "sha256": hashlib.sha256(b"approved").hexdigest(),
            }
        ],
        prompt_template_id="fleet-research-critic",
        prompt_template_version="1",
        prompt_text="Return source-bound candidate findings.",
        output_schema={
            "type": "object",
            "required": ["findings"],
            "properties": {"findings": {"type": "array"}},
        },
        max_credits=max_credits,
        task_id=task_id,
        correlation_id=f"corr-{task_id}",
        created_at="2026-07-27T10:00:00Z",
    )


def test_audit_ledger_redacts_and_verifies_hash_chain(
    tmp_path: Path,
) -> None:
    ledger = WorkLLMAuditLedger(tmp_path / "audit")

    first = ledger.append(
        event_type="task_prepared",
        actor_ref="operator@example.test",
        task_id="task-1",
        details={
            "contact": "reviewer@example.test",
            "password": "password=hunter42",
        },
        occurred_at="2026-07-27T10:00:00Z",
    )
    second = ledger.append(
        event_type="submission_authorized",
        actor_ref="operator@example.test",
        task_id="task-1",
        details={"credits": 25},
        occurred_at="2026-07-27T10:01:00Z",
    )
    verification = ledger.verify()
    serialized = ledger.path.read_text(encoding="utf-8")

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert second["previous_event_sha256"] == first["event_sha256"]
    assert verification["valid"] is True
    assert verification["event_count"] == 2
    assert verification["head_event_sha256"] == second["event_sha256"]
    assert "operator@example.test" not in serialized
    assert "reviewer@example.test" not in serialized
    assert "hunter42" not in serialized
    assert stat.S_IMODE(ledger.path.stat().st_mode) == 0o600


def test_audit_ledger_detects_tampering(tmp_path: Path) -> None:
    ledger = WorkLLMAuditLedger(tmp_path / "audit")
    ledger.append(
        event_type="task_prepared",
        actor_ref="operator-1",
        task_id="task-1",
        details={"credits": 25},
    )
    payload = ledger.path.read_text(encoding="utf-8").replace(
        '"credits":25',
        '"credits":26',
    )
    ledger.path.write_text(payload, encoding="utf-8")
    ledger.path.chmod(0o600)

    with pytest.raises(
        WorkLLMGovernanceError,
        match="workllm_audit_digest_mismatch",
    ):
        ledger.verify()


def test_credit_ledger_reserves_consumes_and_enforces_hard_limit(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    sidecar = WorkLLMSidecar(config)
    ledger = WorkLLMCreditLedger(tmp_path / "governance", config)
    first = _packet(sidecar, task_id="task-1", max_credits=50)
    second = _packet(sidecar, task_id="task-2", max_credits=50)

    reservation = ledger.reserve(
        first,
        reserved_at="2026-07-27T10:00:00Z",
    )
    duplicate = ledger.reserve(
        first,
        reserved_at="2026-07-27T10:00:00Z",
    )
    consumption = ledger.consume(
        task_id=first.task_id,
        request_sha256=first.request_sha256,
        credits_consumed=12,
        consumed_at="2026-07-27T10:02:00Z",
    )

    assert reservation["idempotent"] is False
    assert duplicate["idempotent"] is True
    assert consumption["status"] == "consumed"
    assert consumption["summary"]["consumed_credits"] == 12
    assert consumption["summary"]["active_reserved_credits"] == 0

    ledger.reserve(second, reserved_at="2026-07-27T10:03:00Z")
    third = _packet(sidecar, task_id="task-3", max_credits=50)
    with pytest.raises(
        WorkLLMGovernanceError,
        match="workllm_hard_credit_limit_exceeded",
    ):
        ledger.reserve(third, reserved_at="2026-07-27T10:04:00Z")

    assert stat.S_IMODE(ledger.path.stat().st_mode) == 0o600


def test_credit_cancellation_releases_reservation_and_redacts_reason(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    sidecar = WorkLLMSidecar(config)
    ledger = WorkLLMCreditLedger(tmp_path / "governance", config)
    packet = _packet(sidecar, task_id="task-1", max_credits=50)
    ledger.reserve(packet, reserved_at="2026-07-27T10:00:00Z")

    cancellation = ledger.cancel(
        task_id=packet.task_id,
        request_sha256=packet.request_sha256,
        reason="Cancelled by owner@example.test; password=hunter42",
        cancelled_at="2026-07-27T10:01:00Z",
    )
    serialized = json.dumps(cancellation)

    assert cancellation["status"] == "cancelled"
    assert cancellation["summary"]["active_reserved_credits"] == 0
    assert "owner@example.test" not in serialized
    assert "hunter42" not in serialized


def test_credit_ledger_rejects_tampered_negative_consumption(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    sidecar = WorkLLMSidecar(config)
    ledger = WorkLLMCreditLedger(tmp_path / "governance", config)
    packet = _packet(sidecar, task_id="task-1", max_credits=25)
    ledger.reserve(packet, reserved_at="2026-07-27T10:00:00Z")
    ledger.consume(
        task_id=packet.task_id,
        request_sha256=packet.request_sha256,
        credits_consumed=5,
        consumed_at="2026-07-27T10:01:00Z",
    )
    state = json.loads(ledger.path.read_text(encoding="utf-8"))
    state["reservations"]["task-1"]["consumed_credits"] = -100
    ledger.path.write_text(json.dumps(state), encoding="utf-8")
    ledger.path.chmod(0o600)

    with pytest.raises(
        WorkLLMGovernanceError,
        match="workllm_credit_ledger_invalid",
    ):
        ledger.summary(at="2026-07-27T10:02:00Z")


def test_governed_manual_lane_persists_full_audit_and_review(
    tmp_path: Path,
) -> None:
    sidecar = WorkLLMSidecar(_config(tmp_path))
    lane = GovernedWorkLLMManualLane(
        sidecar,
        governance_root=tmp_path / "governance",
    )
    packet = _packet(sidecar, task_id="task-1")

    staged = lane.stage_packet(
        packet,
        actor_ref="operator-1",
        occurred_at="2026-07-27T10:00:00Z",
    )
    authorized = lane.authorize(
        packet,
        actor_ref="operator-1",
        authorized_at="2026-07-27T10:01:00Z",
    )
    captured = lane.capture(
        packet,
        output_text="Candidate result.",
        actor_ref="operator-1",
        observed_models=("model-a",),
        credits_consumed=7,
        provider_job_ref="provider-job-1",
        provider_surface_receipt_sha256=hashlib.sha256(
            b"browser-run-receipt-1"
        ).hexdigest(),
        captured_at="2026-07-27T10:02:00Z",
    )
    reviewed = lane.review(
        captured["receipt"],
        actor_ref="operator-1",
        decision="accepted_candidate",
        schema_valid=True,
        safety_valid=True,
        reviewed_at="2026-07-27T10:03:00Z",
    )

    assert Path(staged["task_packet_path"]).is_file()
    assert authorized["reservation"]["status"] == "reserved"
    assert captured["consumption"]["status"] == "consumed"
    assert reviewed["receipt"]["candidate_accepted"] is True
    assert reviewed["receipt"]["canonical_promotion_authority"] is False
    assert Path(reviewed["receipt_path"]).is_file()
    verification = lane.audit.verify()
    assert verification["valid"] is True
    assert verification["event_count"] == 4


def test_capture_requires_existing_credit_reservation(
    tmp_path: Path,
) -> None:
    sidecar = WorkLLMSidecar(_config(tmp_path))
    lane = GovernedWorkLLMManualLane(
        sidecar,
        governance_root=tmp_path / "governance",
    )
    packet = _packet(sidecar, task_id="task-1")

    with pytest.raises(
        WorkLLMGovernanceError,
        match="workllm_credit_reservation_missing",
    ):
        lane.capture(
            packet,
            output_text="Candidate result.",
            actor_ref="operator-1",
            credits_consumed=1,
            provider_surface_receipt_sha256=hashlib.sha256(
                b"browser-run-receipt-1"
            ).hexdigest(),
            captured_at="2026-07-27T10:02:00Z",
        )

    assert not (
        sidecar.config.receipt_root / packet.task_id / "result.txt"
    ).exists()


def test_rollback_override_stops_existing_sidecar_and_writes_receipt(
    tmp_path: Path,
) -> None:
    sidecar = WorkLLMSidecar(_config(tmp_path))
    lane = GovernedWorkLLMManualLane(
        sidecar,
        governance_root=tmp_path / "governance",
    )
    packet = _packet(sidecar, task_id="task-1")
    lane.authorize(
        packet,
        actor_ref="operator-1",
        authorized_at="2026-07-27T10:00:00Z",
    )

    rollback = lane.engage_rollback(
        actor_ref="operator-1",
        reason="Provider anomaly reported by reviewer@example.test",
        engaged_at="2026-07-27T10:01:00Z",
    )

    assert sidecar.config.kill_switch_engaged is False
    assert sidecar.config.kill_switch_active() is True
    assert rollback["receipt"]["kill_switch_effective"] is True
    assert (
        rollback["receipt"]["required_runtime_posture"][
            "EA_WORKLLM_INTERNAL_NONSECRET_ENABLED"
        ]
        == "0"
    )
    assert Path(rollback["receipt_path"]).is_file()
    assert Path(rollback["control_state_path"]).is_file()
    assert (
        stat.S_IMODE(Path(rollback["control_state_path"]).stat().st_mode)
        == 0o600
    )
    assert "reviewer@example.test" not in json.dumps(rollback)

    second = _packet(sidecar, task_id="task-2")
    with pytest.raises(
        WorkLLMPolicyError,
        match="workllm_kill_switch_engaged",
    ):
        lane.authorize(
            second,
            actor_ref="operator-1",
            authorized_at="2026-07-27T10:02:00Z",
        )


def test_malformed_control_override_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.control_state_file.parent.mkdir(parents=True)
    config.control_state_file.write_text("{broken", encoding="utf-8")
    config.control_state_file.chmod(0o600)

    assert config.kill_switch_active() is True
