from __future__ import annotations

import json
from pathlib import Path

from scripts import verify_proactive_ooda_live_receipt as verifier


def _write_receipt(path: Path, **payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _followthrough_ok() -> dict[str, object]:
    return {
        "status": "ok",
        "reason": "",
        "error": "",
        "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        "operator_status": {
            "path": ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
            "status": "ready_local_runtime",
        },
        "gold_acceptance": {
            "path": ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
            "status": "blocked_operator_runtime_posture",
        },
        "goal_posture": {
            "path": ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json",
            "status": "blocked_real_world_acceptance",
        },
        "operator_action_required_digest": {
            "path": ".codex-studio/published/ea_operator_action_required_digest.generated.json",
            "status": "suppressed_duplicate",
            "notification_status": "suppressed_duplicate",
            "item_count": 1,
        },
    }


def _sent_receipt_payload() -> dict[str, object]:
    return {
        "generated_at": "2026-07-08T15:27:32.832947+00:00",
        "notification_status": "sent",
        "dry_run": False,
        "item_count": 1,
        "delivery_channel": "telegram",
        "delivery_message_ids": ["telegram-delivery-1"],
        "telegram_message_ids": ["telegram-1"],
        "principal_id_hash": "a" * 64,
        "notified_ref_hashes": ["b" * 64],
        "error_code": "",
    }


def test_live_receipt_verifier_falls_back_to_archived_sent_receipt_for_no_decision_ready_safe_work(
    tmp_path: Path,
) -> None:
    latest_receipt = tmp_path / "proactive_ooda_latest_run.generated.json"
    archived_receipt = tmp_path / "proactive_ooda_run_receipts" / "archived-sent.json"
    _write_receipt(archived_receipt, **_sent_receipt_payload())
    _write_receipt(
        latest_receipt,
        generated_at="2026-07-09T03:07:48.136221+00:00",
        notification_status="deferred",
        dry_run=False,
        item_count=5,
        delivery_message_ids=[],
        telegram_message_ids=[],
        principal_id_hash="c" * 64,
        notified_ref_hashes=[],
        error_code="no_decision_ready_safe_work",
        delivery_route_error="",
        delivery_guard={
            "delivery_state": "deferred",
            "deferred_reason": "no_decision_ready_safe_work",
            "notification_requires_user_action": False,
            "decision_ready_safe_work_present": False,
        },
        followthrough_artifacts=_followthrough_ok(),
    )

    report = verifier.verify_receipt(latest_receipt)

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["archived_delivery_receipt_used"] is True
    assert report["archived_sent_receipt_used"] is True
    assert report["notification_status"] == "sent"
    assert report["latest_notification_status"] == "deferred"
    assert report["followthrough_source"] == "latest_receipt"
    assert report["delivery_guard_deferred_reason"] == ""


def test_live_receipt_verifier_keeps_budget_deferred_actionable_receipt_blocked_even_with_archived_sent_receipt(
    tmp_path: Path,
) -> None:
    latest_receipt = tmp_path / "proactive_ooda_latest_run.generated.json"
    archived_receipt = tmp_path / "proactive_ooda_run_receipts" / "archived-sent.json"
    _write_receipt(archived_receipt, **_sent_receipt_payload())
    _write_receipt(
        latest_receipt,
        generated_at="2026-07-09T03:07:48.136221+00:00",
        notification_status="deferred",
        dry_run=False,
        item_count=1,
        delivery_message_ids=[],
        telegram_message_ids=[],
        principal_id_hash="d" * 64,
        notified_ref_hashes=["e" * 64],
        error_code="deferred_by_interruption_budget",
        delivery_route_error="",
        delivery_guard={
            "delivery_state": "deferred",
            "deferred_reason": "deferred_by_interruption_budget",
            "notification_requires_user_action": True,
            "decision_ready_safe_work_present": True,
        },
        followthrough_artifacts=_followthrough_ok(),
    )

    report = verifier.verify_receipt(latest_receipt)

    assert report["ok"] is False
    assert report["archived_delivery_receipt_used"] is False
    assert "receipt_not_sent" in report["errors"]
