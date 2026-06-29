from __future__ import annotations

import json
from pathlib import Path

from app.services.proactive_ooda_approval_outcomes import (
    PROACTIVE_OODA_APPROVAL_OUTCOME_EVENT_TYPE,
    PROACTIVE_OODA_APPROVAL_OUTCOME_SCHEMA,
    build_proactive_ooda_approval_outcome_observation,
    default_proactive_ooda_approval_outcome_path,
    record_proactive_ooda_approval_outcome,
)
from app.services.proactive_ooda_approval_capture import finalize_proactive_ooda_approval_outcome


def test_default_proactive_ooda_approval_outcome_path_tracks_run_receipt_directory(tmp_path: Path) -> None:
    path = default_proactive_ooda_approval_outcome_path(
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    assert path == tmp_path / "provider-ledger" / "proactive_ooda_latest_approval_outcome.generated.json"


def test_record_proactive_ooda_approval_outcome_writes_redacted_artifact(tmp_path: Path) -> None:
    output = tmp_path / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
    raw_evidence = "Approved after comparing the live shortlist."
    raw_actor = "operator-admin-1"
    raw_packet_ref = "stage_packet:private-packet-123"
    raw_artifact_ref = "safe_work_result:private-artifact-456"

    payload = record_proactive_ooda_approval_outcome(
        principal_id="exec",
        outcome="approved",
        source_kind="operator",
        evidence=raw_evidence,
        actor=raw_actor,
        packet_ref=raw_packet_ref,
        staged_artifact_ref=raw_artifact_ref,
        recorded_at="2026-06-27T10:00:00Z",
        output_path=output,
    )

    assert payload["schema"] == PROACTIVE_OODA_APPROVAL_OUTCOME_SCHEMA
    assert payload["event_type"] == PROACTIVE_OODA_APPROVAL_OUTCOME_EVENT_TYPE
    assert payload["accepted"] is True
    assert payload["approval_outcome_recorded"] is True
    assert payload["status"] == "accepted_redacted"
    assert payload["packet_ref_kind"] == "stage_packet"
    assert payload["staged_artifact_kind"] == "safe_work_result"
    assert payload["evidence_sha256"]
    assert payload["actor_sha256"]
    assert payload["packet_ref_sha256"]
    assert payload["staged_artifact_sha256"]

    persisted = json.loads(output.read_text(encoding="utf-8"))
    persisted_text = output.read_text(encoding="utf-8")
    assert persisted["outcome_id"] == payload["outcome_id"]
    assert raw_evidence not in persisted_text
    assert raw_actor not in persisted_text
    assert raw_packet_ref not in persisted_text
    assert raw_artifact_ref not in persisted_text


def test_proactive_ooda_approval_outcome_observation_keeps_payload_sanitized() -> None:
    payload = record_proactive_ooda_approval_outcome(
        principal_id="exec",
        outcome="rejected",
        source_kind="operator",
        evidence="Rejected after review.",
        actor="operator-admin-1",
        packet_ref="stage_packet:private-packet-123",
        staged_artifact_ref="safe_work_result:private-artifact-456",
        recorded_at="2026-06-27T10:00:00Z",
        output_path=Path("/tmp/proactive-ooda-approval-outcome-test.json"),
    )
    observation = build_proactive_ooda_approval_outcome_observation(
        principal_id="exec",
        payload=payload,
    )

    assert observation["event_type"] == PROACTIVE_OODA_APPROVAL_OUTCOME_EVENT_TYPE
    assert observation["principal_id"] == "exec"
    assert "Rejected after review." not in observation["payload_json"]
    assert "operator-admin-1" not in observation["payload_json"]
    assert "stage_packet:private-packet-123" not in observation["payload_json"]


def test_finalize_proactive_ooda_approval_outcome_materializes_gold_and_syncs(monkeypatch, tmp_path: Path) -> None:
    from app.services import proactive_ooda_approval_capture as capture

    calls: dict[str, object] = {}

    def fake_operator_status_materialize(*, output_path: Path, live_receipt_path: Path | None = None) -> None:
        calls["operator_status"] = {
            "output_path": output_path,
            "live_receipt_path": live_receipt_path,
        }

    def fake_gold_materialize(
        *,
        output_path: Path,
        operator_status_path: Path,
        run_receipt_path: Path | None,
        stage_packet_dir: Path | None,
        safe_work_result_dir: Path | None,
        approval_outcome_path: Path,
    ) -> None:
        calls["gold"] = {
            "output_path": output_path,
            "operator_status_path": operator_status_path,
            "run_receipt_path": run_receipt_path,
            "stage_packet_dir": stage_packet_dir,
            "safe_work_result_dir": safe_work_result_dir,
            "approval_outcome_path": approval_outcome_path,
        }

    monkeypatch.setattr(capture, "_materialize_operator_status", fake_operator_status_materialize)
    monkeypatch.setattr(capture, "_materialize_gold_acceptance", fake_gold_materialize)
    monkeypatch.setattr(capture, "teable_sync_enabled", lambda: True)
    monkeypatch.setattr(
        capture,
        "load_runtime_artifact_bundle",
        lambda **kwargs: {
            "run_receipt_path": tmp_path / "provider-ledger" / "proactive_ooda_run_receipts" / "20260627T100000Z-sent-proof.json",
            "run_receipt": {"notification_status": "sent"},
            "stage_packet_dir": tmp_path / "provider-ledger" / "proactive_ooda_stage_packets",
            "safe_work_result": {"result_ref": "safe_work_result:private-artifact-456"},
            "safe_work_result_dir": tmp_path / "provider-ledger" / "proactive_ooda_safe_work_results",
        },
    )
    monkeypatch.setattr(
        capture,
        "sync_proactive_ooda_approval_outcome_to_teable",
        lambda **kwargs: {
            "status": "synced",
            "sync_attempted": True,
            "blocked_reason": "",
        },
    )

    result = finalize_proactive_ooda_approval_outcome(
        principal_id="exec",
        outcome="approved",
        source_kind="operator",
        evidence="Approved after comparing the live shortlist.",
        actor="operator-admin-1",
        packet_ref="stage_packet:private-packet-123",
        staged_artifact_ref="safe_work_result:private-artifact-456",
        recorded_at="2026-06-27T10:00:00Z",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    assert result["approval_outcome"]["accepted"] is True
    assert result["teable_sync"]["status"] == "synced"
    assert result["operator_status_path"] == tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_operator_status.generated.json"
    assert calls["operator_status"]["output_path"] == tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_operator_status.generated.json"
    assert calls["operator_status"]["live_receipt_path"] == tmp_path / "provider-ledger" / "proactive_ooda_run_receipts" / "20260627T100000Z-sent-proof.json"
    assert calls["gold"]["output_path"] == tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json"
    assert calls["gold"]["operator_status_path"] == tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_operator_status.generated.json"
    assert calls["gold"]["run_receipt_path"] == tmp_path / "provider-ledger" / "proactive_ooda_run_receipts" / "20260627T100000Z-sent-proof.json"
    assert calls["gold"]["stage_packet_dir"] == tmp_path / "provider-ledger" / "proactive_ooda_stage_packets"
    assert calls["gold"]["safe_work_result_dir"] == tmp_path / "provider-ledger" / "proactive_ooda_safe_work_results"
    assert calls["gold"]["approval_outcome_path"] == tmp_path / "provider-ledger" / "proactive_ooda_latest_approval_outcome.generated.json"


def test_finalize_proactive_ooda_approval_outcome_keeps_recorded_outcome_when_materializers_are_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import proactive_ooda_approval_capture as capture

    monkeypatch.setattr(
        capture,
        "_materialize_operator_status",
        lambda **kwargs: (_ for _ in ()).throw(ModuleNotFoundError("scripts.materialize_proactive_ooda_operator_status")),
    )
    monkeypatch.setattr(capture, "teable_sync_enabled", lambda: False)
    monkeypatch.setattr(
        capture,
        "load_runtime_artifact_bundle",
        lambda **kwargs: {
            "run_receipt_path": tmp_path / "provider-ledger" / "proactive_ooda_run_receipts" / "20260627T100000Z-sent-proof.json",
            "run_receipt": {"notification_status": "sent"},
            "stage_packet_dir": tmp_path / "provider-ledger" / "proactive_ooda_stage_packets",
            "safe_work_result_dir": tmp_path / "provider-ledger" / "proactive_ooda_safe_work_results",
        },
    )

    result = finalize_proactive_ooda_approval_outcome(
        principal_id="exec",
        outcome="rejected",
        source_kind="telegram_button",
        evidence="Rejected after review.",
        actor="telegram:42",
        packet_ref="stage_packet:private-packet-123",
        staged_artifact_ref="safe_work_result:private-artifact-456",
        recorded_at="2026-06-27T10:00:00Z",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    assert result["approval_outcome"]["outcome"] == "rejected"
    assert result["approval_outcome_path"].is_file()
    assert result["operator_status_materialization"]["status"] == "failed"
    assert "ModuleNotFoundError" in result["operator_status_materialization"]["error"]
    assert result["gold_acceptance_materialization"]["status"] == "skipped"
    assert result["gold_acceptance_materialization"]["error"] == "operator_status_materialization_failed"


def test_materialize_script_import_works_from_ea_scripts_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import proactive_ooda_approval_capture as capture

    monkeypatch.chdir(Path("/docker/EA/ea"))

    operator_status = tmp_path / "operator_status.generated.json"
    gold_acceptance = tmp_path / "gold_acceptance.generated.json"

    capture._materialize_operator_status(output_path=operator_status)
    capture._materialize_gold_acceptance(
        output_path=gold_acceptance,
        operator_status_path=operator_status,
        run_receipt_path=None,
        stage_packet_dir=tmp_path / "stage_packets",
        safe_work_result_dir=tmp_path / "safe_work_results",
        approval_outcome_path=tmp_path / "approval_outcome.json",
    )

    assert operator_status.is_file()
    assert gold_acceptance.is_file()
