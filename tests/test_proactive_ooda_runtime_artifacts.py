from __future__ import annotations

import json
from pathlib import Path

from app.services import proactive_ooda_runtime_artifacts as artifacts


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _stage_packet(*, packet_id: str, kind: str = "approval_packet") -> dict[str, object]:
    return {
        "schema": artifacts.STAGE_PACKET_SCHEMA,
        "packet_id": packet_id,
        "packet_ref": f"stage_packet:{packet_id}",
        "approval": {
            "required": kind == "approval_packet",
        },
        "stage": {
            "kind": kind,
            "payload": {
                "work_type": "compare_options",
                "approval_prompt": (
                    "Approve whether EA should proceed with this staged packet."
                    if kind == "approval_packet"
                    else ""
                ),
            },
        },
    }


def _safe_work_result(
    *,
    result_id: str,
    source_packet_ref_hash: str,
    status: str,
    approval_required: bool,
) -> dict[str, object]:
    return {
        "schema": artifacts.SAFE_WORK_RESULT_SCHEMA,
        "result_id": result_id,
        "result_ref": f"safe_work_result:{result_id}",
        "source_packet_ref_hash": source_packet_ref_hash,
        "status": status,
        "work_type": "compare_options",
        "approval": {
            "required": approval_required,
        },
        "approval_prompt": (
            "Approve whether EA should proceed with this staged packet."
            if approval_required
            else ""
        ),
        "staged_action_url": "https://example.com/review" if approval_required else "",
        "recommended_option_or_draft": {
            "kind": "shortlist_option",
            "value": {
                "label": "Best candidate",
                "url": "https://example.com/review",
            },
        },
        "shortlist": [
            {
                "label": "Best candidate",
                "url": "https://example.com/review",
            }
        ],
        "execution_receipt": {
            "network_fetch_success_count": 1,
            "page_checks": [
                {
                    "url": "https://example.com/review",
                    "reachable": True,
                }
            ],
        },
        "audit": {
            "status": "pass",
            "issues": [],
        },
    }


def _run_receipt(
    *,
    generated_at: str,
    notification_status: str,
    stage_packet_ref_hashes: list[str],
    safe_work_result_ref_hashes: list[str],
    teable_status: str = "",
    error_code: str = "",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at": generated_at,
        "notification_status": notification_status,
        "item_count": 1,
        "stage_packet_ref_hashes": stage_packet_ref_hashes,
        "safe_work_result_ref_hashes": safe_work_result_ref_hashes,
    }
    if error_code:
        payload["error_code"] = error_code
    if teable_status:
        payload["teable_sync"] = {"status": teable_status}
    return payload


def test_overlay_current_source_health_prefers_newer_primary_receipt() -> None:
    primary_path = Path("/tmp/proactive_ooda_latest_run.generated.json")
    archived_path = Path("/tmp/proactive_ooda_run_receipts/sent.json")
    primary = {
        "generated_at": "2026-07-08T15:30:34.750282+00:00",
        "source_health": {
            "present": True,
            "issue_count": 1,
            "issues": [
                {
                    "source_key": "google_workspace",
                    "error_code": "google_oauth_invalid_grant",
                    "recovery_mode": "scheduler_cooldown",
                    "blocked_until": "2026-07-08T21:29:49.591351Z",
                    "cooldown_active": True,
                }
            ],
        },
    }
    archived = {
        "generated_at": "2026-07-08T15:27:32.832947+00:00",
        "notification_status": "sent",
        "source_health": {
            "present": True,
            "issue_count": 1,
            "issues": [
                {
                    "source_key": "google_workspace",
                    "error_code": "google_oauth_invalid_grant",
                }
            ],
        },
    }

    merged = artifacts._overlay_current_source_health(
        primary_run_receipt_path=primary_path,
        primary_run_receipt=primary,
        run_receipt_path=archived_path,
        run_receipt=archived,
    )

    assert merged["notification_status"] == "sent"
    assert merged["source_health"]["issues"][0]["recovery_mode"] == "scheduler_cooldown"
    assert merged["source_health"]["issues"][0]["blocked_until"] == "2026-07-08T21:29:49.591351Z"


def test_overlay_current_source_health_keeps_selected_receipt_when_primary_is_older() -> None:
    primary = {
        "generated_at": "2026-07-08T15:27:32.832947+00:00",
        "source_health": {"present": False},
    }
    selected = {
        "generated_at": "2026-07-08T15:30:34.750282+00:00",
        "source_health": {
            "present": True,
            "issues": [{"source_key": "google_workspace", "error_code": "google_oauth_invalid_grant"}],
        },
    }

    merged = artifacts._overlay_current_source_health(
        primary_run_receipt_path=Path("/tmp/proactive_ooda_latest_run.generated.json"),
        primary_run_receipt=primary,
        run_receipt_path=Path("/tmp/proactive_ooda_run_receipts/sent.json"),
        run_receipt=selected,
    )

    assert merged == selected


def test_load_runtime_artifact_bundle_carries_forward_pending_approval_packet_from_older_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path
    state_path = root / "state" / "proactive_ooda_notified.json"
    receipt_path = root / "state" / artifacts.RUN_RECEIPT_FILENAME
    run_receipt_dir = root / "state" / artifacts.RUN_RECEIPT_DIRNAME
    stage_dir = root / "artifacts" / "stage_packets"
    safe_dir = root / "artifacts" / "safe_work_results"

    quiet_stage = _stage_packet(packet_id="quiet-packet", kind="decision_packet")
    quiet_safe = _safe_work_result(
        result_id="quiet-safe-work",
        source_packet_ref_hash=artifacts._packet_ref_hash(quiet_stage),  # noqa: SLF001
        status="ready_for_followthrough",
        approval_required=False,
    )
    pending_stage = _stage_packet(packet_id="pending-packet")
    pending_safe = _safe_work_result(
        result_id="pending-safe-work",
        source_packet_ref_hash=artifacts._packet_ref_hash(pending_stage),  # noqa: SLF001
        status="staged_for_user_decision",
        approval_required=True,
    )

    _write_json(stage_dir / "quiet-stage.json", quiet_stage)
    _write_json(safe_dir / "quiet-safe.json", quiet_safe)
    _write_json(stage_dir / "pending-stage.json", pending_stage)
    _write_json(safe_dir / "pending-safe.json", pending_safe)

    older_pending_receipt = _run_receipt(
        generated_at="2026-07-05T11:51:55.951035+00:00",
        notification_status="deferred",
        stage_packet_ref_hashes=[artifacts._packet_ref_hash(pending_stage)],  # noqa: SLF001
        safe_work_result_ref_hashes=[artifacts._safe_work_result_ref_hash(pending_safe)],  # noqa: SLF001
    )
    latest_quiet_receipt = _run_receipt(
        generated_at="2026-07-09T22:02:04.349407+00:00",
        notification_status="deferred",
        error_code="no_user_action_required",
        stage_packet_ref_hashes=[artifacts._packet_ref_hash(quiet_stage)],  # noqa: SLF001
        safe_work_result_ref_hashes=[artifacts._safe_work_result_ref_hash(quiet_safe)],  # noqa: SLF001
        teable_status="synced",
    )
    _write_json(run_receipt_dir / "20260705-pending.json", older_pending_receipt)
    _write_json(receipt_path, latest_quiet_receipt)

    bundle = artifacts.load_runtime_artifact_bundle(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
    )

    assert bundle["stage_packet"]["packet_ref"] == pending_stage["packet_ref"]
    assert bundle["safe_work_result"]["result_ref"] == pending_safe["result_ref"]
    assert bundle["run_receipt"]["generated_at"] == older_pending_receipt["generated_at"]
    assert bundle["artifact_filter_reason"] == ""
    assert bundle["current_packet_live_pending_count"] == 0


def test_load_runtime_artifact_bundle_does_not_carry_forward_pending_packet_with_matching_recorded_outcome(
    tmp_path: Path,
) -> None:
    root = tmp_path
    state_path = root / "state" / "proactive_ooda_notified.json"
    receipt_path = root / "state" / artifacts.RUN_RECEIPT_FILENAME
    run_receipt_dir = root / "state" / artifacts.RUN_RECEIPT_DIRNAME
    stage_dir = root / "artifacts" / "stage_packets"
    safe_dir = root / "artifacts" / "safe_work_results"

    quiet_stage = _stage_packet(packet_id="quiet-packet", kind="decision_packet")
    quiet_safe = _safe_work_result(
        result_id="quiet-safe-work",
        source_packet_ref_hash=artifacts._packet_ref_hash(quiet_stage),  # noqa: SLF001
        status="ready_for_followthrough",
        approval_required=False,
    )
    pending_stage = _stage_packet(packet_id="pending-packet")
    pending_safe = _safe_work_result(
        result_id="pending-safe-work",
        source_packet_ref_hash=artifacts._packet_ref_hash(pending_stage),  # noqa: SLF001
        status="staged_for_user_decision",
        approval_required=True,
    )

    _write_json(stage_dir / "quiet-stage.json", quiet_stage)
    _write_json(safe_dir / "quiet-safe.json", quiet_safe)
    _write_json(stage_dir / "pending-stage.json", pending_stage)
    _write_json(safe_dir / "pending-safe.json", pending_safe)

    older_pending_receipt = _run_receipt(
        generated_at="2026-07-05T11:51:55.951035+00:00",
        notification_status="deferred",
        stage_packet_ref_hashes=[artifacts._packet_ref_hash(pending_stage)],  # noqa: SLF001
        safe_work_result_ref_hashes=[artifacts._safe_work_result_ref_hash(pending_safe)],  # noqa: SLF001
    )
    latest_quiet_receipt = _run_receipt(
        generated_at="2026-07-09T22:02:04.349407+00:00",
        notification_status="deferred",
        error_code="no_user_action_required",
        stage_packet_ref_hashes=[artifacts._packet_ref_hash(quiet_stage)],  # noqa: SLF001
        safe_work_result_ref_hashes=[artifacts._safe_work_result_ref_hash(quiet_safe)],  # noqa: SLF001
        teable_status="synced",
    )
    _write_json(run_receipt_dir / "20260705-pending.json", older_pending_receipt)
    _write_json(receipt_path, latest_quiet_receipt)

    paths = artifacts.resolve_runtime_artifact_paths(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
    )
    _write_json(
        paths["approval_outcome_path"],
        {
            "approval_outcome_recorded": True,
            "packet_ref_sha256": artifacts._packet_ref_hash(pending_stage),  # noqa: SLF001
            "staged_artifact_sha256": artifacts._safe_work_result_ref_hash(pending_safe),  # noqa: SLF001
        },
    )

    bundle = artifacts.load_runtime_artifact_bundle(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
    )

    assert bundle["stage_packet"]["packet_ref"] == quiet_stage["packet_ref"]
    assert bundle["safe_work_result"]["result_ref"] == quiet_safe["result_ref"]
    assert bundle["run_receipt"]["generated_at"] == latest_quiet_receipt["generated_at"]


def test_latest_run_receipts_returns_empty_when_directory_probe_is_permission_denied(monkeypatch) -> None:
    original_is_dir = Path.is_dir

    def fake_is_dir(self: Path) -> bool:
        if self.as_posix() == "/denied/proactive_ooda_run_receipts":
            raise PermissionError("denied")
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)

    assert artifacts.latest_run_receipts(Path("/denied/proactive_ooda_run_receipts")) == []
