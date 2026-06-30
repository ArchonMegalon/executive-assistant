from __future__ import annotations

import hashlib
from pathlib import Path

from app.services import proactive_ooda_live_ops_bridge


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_ea_live_ops_script_path_supports_host_repo_layout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo-root"
    service_file = repo_root / "ea" / "app" / "services" / "bridge.py"
    script_path = repo_root / "scripts" / "ea_live_ops.py"
    service_file.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text("", encoding="utf-8")
    script_path.write_text("# probe\n", encoding="utf-8")

    result = proactive_ooda_live_ops_bridge._ea_live_ops_script_path(service_file=service_file)  # noqa: SLF001

    assert result == script_path


def test_ea_live_ops_script_path_supports_container_layout(tmp_path: Path) -> None:
    app_root = tmp_path / "app-root"
    service_file = app_root / "app" / "services" / "bridge.py"
    script_path = app_root / "scripts" / "ea_live_ops.py"
    service_file.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text("", encoding="utf-8")
    script_path.write_text("# probe\n", encoding="utf-8")

    result = proactive_ooda_live_ops_bridge._ea_live_ops_script_path(service_file=service_file)  # noqa: SLF001

    assert result == script_path


def test_resolve_proactive_ooda_capture_bundle_prefers_live_runtime_probe() -> None:
    packet_ref = "stage_packet:live-packet"
    staged_artifact_ref = "safe_work_result:live-artifact"

    def _live_probe(*, timeout_seconds: float | None = None) -> dict[str, object]:
        assert timeout_seconds == 11.0
        return {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/live.json",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_approval_outcomes/live.json",
            "run_receipt": {"notification_status": "sent"},
            "stage_packet": {
                "packet_ref": packet_ref,
                "approval": {"required": True},
            },
            "safe_work_result": {
                "result_ref": staged_artifact_ref,
                "status": "staged_for_user_decision",
                "approval": {"required": True},
            },
            "approval_outcome": {},
            "current_packet_callback_outcome": {
                "approval_outcome_recorded": True,
                "status": "approved",
                "packet_ref_sha256": _hash(packet_ref),
                "staged_artifact_sha256": _hash(staged_artifact_ref),
            },
            "current_packet_live_pending_count": 1,
        }

    def _host_loader(**_: object) -> dict[str, object]:
        raise AssertionError("host loader should not run when live probe is healthy")

    result = proactive_ooda_live_ops_bridge.resolve_proactive_ooda_capture_bundle(
        root=Path("/workspace"),
        state_path="state/proactive_ooda_notified.json",
        timeout_seconds=11.0,
        live_probe=_live_probe,
        bundle_loader=_host_loader,
    )

    assert result["bundle_source"] == "live_runtime"
    assert result["host_fallback_used"] is False
    assert dict(result["bundle"])["stage_packet"]["packet_ref"] == packet_ref
    assert dict(result["approval_selection"])["source"] == "current_packet_callback"
    assert dict(dict(result["approval_selection"])["approval_outcome"])["status"] == "approved"


def test_resolve_proactive_ooda_capture_bundle_falls_back_to_host_bundle() -> None:
    host_bundle = {
        "stage_packet": {"packet_ref": "stage_packet:host-packet", "approval": {"required": True}},
        "safe_work_result": {
            "result_ref": "safe_work_result:host-artifact",
            "status": "staged_for_user_decision",
            "approval": {"required": True},
        },
        "approval_outcome": {},
        "current_packet_callback_outcome": {},
        "run_receipt": {"notification_status": "deferred"},
        "run_receipt_path": "/host/state/proactive_ooda_latest_run.generated.json",
        "stage_packet_path": "/host/state/proactive_ooda_stage_packets/host.json",
        "safe_work_result_path": "/host/state/proactive_ooda_safe_work_results/host.json",
    }

    def _live_probe(*, timeout_seconds: float | None = None) -> dict[str, object]:
        assert timeout_seconds == 9.0
        return {
            "probe_ok": False,
            "status": "probe_failed",
            "blocking_reason": "runtime_artifact_probe_failed:exit_1",
        }

    def _host_loader(**_: object) -> dict[str, object]:
        return host_bundle

    result = proactive_ooda_live_ops_bridge.resolve_proactive_ooda_capture_bundle(
        root=Path("/workspace"),
        state_path="state/proactive_ooda_notified.json",
        timeout_seconds=9.0,
        live_probe=_live_probe,
        bundle_loader=_host_loader,
    )

    assert result["bundle_source"] == "host_runtime_fallback"
    assert result["host_fallback_used"] is True
    assert result["fallback_reason"] == "runtime_artifact_probe_failed:exit_1"
    assert dict(result["bundle"]) == host_bundle


def test_resolve_proactive_ooda_capture_bundle_falls_back_when_live_probe_raises() -> None:
    host_bundle = {
        "stage_packet": {"packet_ref": "stage_packet:host-packet", "approval": {"required": True}},
        "safe_work_result": {
            "result_ref": "safe_work_result:host-artifact",
            "status": "staged_for_user_decision",
            "approval": {"required": True},
        },
        "approval_outcome": {},
        "current_packet_callback_outcome": {},
    }

    def _live_probe(*, timeout_seconds: float | None = None) -> dict[str, object]:
        assert timeout_seconds == 7.0
        raise RuntimeError("boom")

    def _host_loader(**_: object) -> dict[str, object]:
        return host_bundle

    result = proactive_ooda_live_ops_bridge.resolve_proactive_ooda_capture_bundle(
        root=Path("/workspace"),
        state_path="state/proactive_ooda_notified.json",
        timeout_seconds=7.0,
        live_probe=_live_probe,
        bundle_loader=_host_loader,
    )

    assert result["bundle_source"] == "host_runtime_fallback"
    assert result["host_fallback_used"] is True
    assert result["fallback_reason"] == "RuntimeError"


def test_record_live_proactive_ooda_approval_outcome_surfaces_specific_block_reason() -> None:
    captured: dict[str, object] = {}

    def _recorder(**_: object) -> dict[str, object]:
        captured.update(_)
        return {
            "recorded": False,
            "reason": "blocked",
            "approval_outcome": {
                "status": "blocked",
                "reason": "current_packet_ref_mismatch",
            },
        }

    result = proactive_ooda_live_ops_bridge.record_live_proactive_ooda_approval_outcome(
        principal_id="principal-1",
        outcome="approved",
        evidence="reviewed",
        actor="operator-1",
        packet_ref="stage_packet:expected",
        staged_artifact_ref="safe_work_result:expected",
        dry_run=True,
        recorder=_recorder,
    )

    assert result["status"] == "blocked"
    assert result["error"] == "current_packet_ref_mismatch"
    assert captured["dry_run"] is True


def test_record_live_proactive_ooda_approval_outcome_marks_already_decided() -> None:
    def _recorder(**_: object) -> dict[str, object]:
        return {
            "recorded": True,
            "reason": "already_decided",
            "approval_outcome": {
                "status": "approved",
                "reason": "current_packet_approval_outcome_already_recorded",
            },
        }

    result = proactive_ooda_live_ops_bridge.record_live_proactive_ooda_approval_outcome(
        principal_id="principal-1",
        outcome="approved",
        evidence="reviewed",
        actor="operator-1",
        recorder=_recorder,
    )

    assert result["status"] == "already_decided"
    assert result["error"] == ""


def test_record_live_proactive_ooda_approval_outcome_marks_probe_failures() -> None:
    def _recorder(**_: object) -> dict[str, object]:
        return {
            "recorded": False,
            "reason": "artifact_probe_failed",
            "blocking_reason": "runtime_artifact_probe_failed:exit_1",
        }

    result = proactive_ooda_live_ops_bridge.record_live_proactive_ooda_approval_outcome(
        principal_id="principal-1",
        outcome="approved",
        evidence="reviewed",
        actor="operator-1",
        recorder=_recorder,
    )

    assert result["status"] == "probe_failed"
    assert result["error"] == "runtime_artifact_probe_failed:exit_1"


def test_record_live_proactive_ooda_approval_outcome_handles_bridge_exceptions() -> None:
    def _recorder(**_: object) -> dict[str, object]:
        raise RuntimeError("boom")

    result = proactive_ooda_live_ops_bridge.record_live_proactive_ooda_approval_outcome(
        principal_id="principal-1",
        outcome="approved",
        evidence="reviewed",
        actor="operator-1",
        recorder=_recorder,
    )

    assert result["status"] == "record_failed"
    assert result["error"] == "RuntimeError"
