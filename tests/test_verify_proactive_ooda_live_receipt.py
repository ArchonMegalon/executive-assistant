from __future__ import annotations

import importlib
import json
from pathlib import Path

import scripts.verify_proactive_ooda_live_receipt as live_receipt_module
from scripts.verify_proactive_ooda_live_receipt import verify_receipt


def _with_followthrough(payload: dict[str, object], *, status: str = "ok", reason: str = "") -> dict[str, object]:
    enriched = dict(payload)
    enriched["followthrough_artifacts"] = {
        "status": status,
        "reason": reason,
        "run_receipt_path": "state/proactive_ooda_latest_run.generated.json",
        "operator_status": {
            "path": ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
            "status": "ready_with_live_receipt",
        },
        "gold_acceptance": {
            "path": ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
            "status": "blocked_not_accepted_under_ordinary_use",
        },
        "goal_posture": {
            "path": ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json",
            "status": "active_with_blockers",
            "operator_action_queue_count": 4,
        },
        "operator_action_required_digest": {
            "path": ".codex-studio/published/ea_operator_action_required_digest.generated.json",
            "status": "ready_to_send",
            "notification_status": "ready_to_send",
            "item_count": 2,
        },
    }
    return enriched


def test_verify_proactive_ooda_live_receipt_accepts_redacted_sent_receipt(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(live_receipt_module, "ROOT", tmp_path)
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-20T14:58:30+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "delivery_route_error": "whatsapp_web_session_not_ready:qr_required",
                "delivery_recovery_hint": "Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
                "delivery_next_action": "scan_whatsapp_web_qr",
                "telegram_message_ids": ["3004"],
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["delivery_message_count"] == 1
    assert report["telegram_message_count"] == 1
    assert report["delivery_next_action"] == "scan_whatsapp_web_qr"
    assert report["followthrough_status"] == "ok"
    assert report["followthrough_digest_status"] == "ready_to_send"


def test_verify_proactive_ooda_live_receipt_accepts_operator_safe_mirror_receipt(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "mirrored_delivery_proof",
                "generated_at": "2026-07-01T00:34:10+00:00",
                "item_count": 1,
                "notification_status": "deferred",
                "delivery_message_ids": [],
                "telegram_message_ids": [],
                "principal_id_hash": "b" * 64,
                "stage_packet_ref_hashes": ["c" * 64],
                "safe_work_result_ref_hashes": ["d" * 64],
                "delivery_mirror": {
                    "enabled": True,
                    "mode": "operator_safe_mirror",
                    "user_notification_suppressed": True,
                    "approval_request_requires_user_action": True,
                    "packet_ref_hash": "e" * 64,
                    "staged_artifact_ref_hash": "f" * 64,
                    "notification_text_sha256": "1" * 64,
                    "raw_notification_text_exposed": False,
                    "raw_approval_prompt_exposed": False,
                    "raw_private_url_exposed": False,
                },
                "delivery_guard": {
                    "delivery_state": "deferred",
                    "deferred_reason": "mirrored_delivery_proof",
                    "notification_requires_user_action": True,
                },
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["delivery_mode"] == "operator_safe_mirror"
    assert report["operator_safe_mirror_present"] is True
    assert report["delivery_message_count"] == 0
    assert report["telegram_message_count"] == 0
    assert report["delivery_guard_state"] == "deferred"
    assert report["delivery_guard_deferred_reason"] == "mirrored_delivery_proof"
    assert report["notification_requires_user_action"] is True


def test_verify_proactive_ooda_live_receipt_uses_archived_sent_receipt_when_latest_is_quiet(tmp_path) -> None:
    receipt = tmp_path / "proactive_ooda_latest_run.generated.json"
    archive_receipt = tmp_path / "proactive_ooda_run_receipts" / "20260629T103000Z-sent.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "no_user_action_required",
                "generated_at": "2026-06-29T10:40:00+00:00",
                "item_count": 4,
                "notification_status": "deferred",
                "telegram_message_ids": [],
                "delivery_message_ids": [],
                }
            )
        ),
        encoding="utf-8",
    )
    archive_receipt.parent.mkdir(parents=True, exist_ok=True)
    archive_receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-29T10:30:00+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": ["3201"],
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["archived_sent_receipt_used"] is True
    assert report["receipt_path"] == str(archive_receipt)
    assert report["latest_receipt_path"] == str(receipt)
    assert report["latest_notification_status"] == "deferred"
    assert report["quiet_receipt_error_code"] == "no_user_action_required"


def test_verify_proactive_ooda_live_receipt_uses_archived_operator_safe_mirror_when_latest_has_no_items(
    tmp_path,
) -> None:
    receipt = tmp_path / "proactive_ooda_latest_run.generated.json"
    archive_receipt = tmp_path / "proactive_ooda_run_receipts" / "20260701T003410Z-deferred-mirror.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-07-01T00:40:22+00:00",
                "item_count": 0,
                "notification_status": "skipped_no_items",
                "telegram_message_ids": [],
                "delivery_message_ids": [],
                }
            )
        ),
        encoding="utf-8",
    )
    archive_receipt.parent.mkdir(parents=True, exist_ok=True)
    archive_receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "mirrored_delivery_proof",
                "generated_at": "2026-07-01T00:34:10+00:00",
                "item_count": 1,
                "notification_status": "deferred",
                "delivery_message_ids": [],
                "telegram_message_ids": [],
                "principal_id_hash": "b" * 64,
                "stage_packet_ref_hashes": ["c" * 64],
                "safe_work_result_ref_hashes": ["d" * 64],
                "delivery_mirror": {
                    "enabled": True,
                    "mode": "operator_safe_mirror",
                    "user_notification_suppressed": True,
                    "approval_request_requires_user_action": True,
                    "packet_ref_hash": "e" * 64,
                    "staged_artifact_ref_hash": "f" * 64,
                    "notification_text_sha256": "1" * 64,
                    "raw_notification_text_exposed": False,
                    "raw_approval_prompt_exposed": False,
                    "raw_private_url_exposed": False,
                },
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["archived_delivery_receipt_used"] is True
    assert report["archived_operator_safe_mirror_receipt_used"] is True
    assert report["archived_sent_receipt_used"] is False
    assert report["receipt_path"] == str(archive_receipt)
    assert report["latest_receipt_path"] == str(receipt)
    assert report["latest_notification_status"] == "skipped_no_items"
    assert report["quiet_receipt_error_code"] == "skipped_no_items"
    assert report["delivery_mode"] == "operator_safe_mirror"


def test_verify_proactive_ooda_live_receipt_rejects_raw_fields_in_quiet_latest_receipt(tmp_path) -> None:
    receipt = tmp_path / "proactive_ooda_latest_run.generated.json"
    archive_receipt = tmp_path / "proactive_ooda_run_receipts" / "20260629T103000Z-sent.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "no_user_action_required",
                "generated_at": "2026-06-29T10:40:00+00:00",
                "item_count": 4,
                "notification_status": "deferred",
                "telegram_message_ids": [],
                "delivery_message_ids": [],
                "chat_id": "raw-chat-id",
                }
            )
        ),
        encoding="utf-8",
    )
    archive_receipt.parent.mkdir(parents=True, exist_ok=True)
    archive_receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-29T10:30:00+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": ["3201"],
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert report["archived_sent_receipt_used"] is True
    assert "quiet_receipt_contains_raw_chat_id" in report["errors"]


def test_verify_proactive_ooda_live_receipt_rejects_raw_fields(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-20T14:58:30+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": ["3004"],
                "chat_id": "12345",
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert "receipt_contains_raw_chat_id" in report["errors"]


def test_verify_proactive_ooda_live_receipt_rejects_raw_approval_surface_fields(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-20T14:58:30+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": ["3004"],
                "approval_surface": {"callback_token": "secret-token"},
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert "receipt_contains_raw_approval_surface_callback_token" in report["errors"]


def test_verify_proactive_ooda_live_receipt_rejects_missing_message_ids(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-20T14:58:30+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": [],
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert "receipt_missing_delivery_message_id" in report["errors"]
    assert "receipt_missing_telegram_message_id" in report["errors"]


def test_verify_proactive_ooda_live_receipt_rejects_missing_followthrough_artifacts(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-07-06T10:12:00+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": ["3004"],
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert "followthrough_artifacts_missing" in report["errors"]
    assert report["delivery_next_action"] == "repair_proactive_operator_runtime_posture"


def test_verify_proactive_ooda_live_receipt_latest_followthrough_failure_is_not_masked_by_archived_fallback(
    tmp_path,
) -> None:
    receipt = tmp_path / "proactive_ooda_latest_run.generated.json"
    archive_receipt = tmp_path / "proactive_ooda_run_receipts" / "20260706T101000Z-sent.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                    "dry_run": False,
                    "error_code": "no_user_action_required",
                    "generated_at": "2026-07-06T10:12:00+00:00",
                    "item_count": 1,
                    "notification_status": "deferred",
                    "telegram_message_ids": [],
                    "delivery_message_ids": [],
                },
                status="failed",
                reason="AttributeError",
            )
        ),
        encoding="utf-8",
    )
    archive_receipt.parent.mkdir(parents=True, exist_ok=True)
    archive_receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                    "dry_run": False,
                    "error_code": "",
                    "generated_at": "2026-07-06T10:10:00+00:00",
                    "item_count": 1,
                    "notification_status": "sent",
                    "notified_ref_hashes": ["a" * 64],
                    "principal_id_hash": "b" * 64,
                    "telegram_message_ids": ["3201"],
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert report["archived_sent_receipt_used"] is True
    assert "followthrough_status_not_ok" in report["errors"]
    assert report["followthrough_status"] == "failed"
    assert report["followthrough_reason"] == "AttributeError"
    assert report["delivery_next_action"] == "repair_proactive_operator_runtime_posture"


def test_verify_proactive_ooda_live_receipt_overlays_current_followthrough_component_receipts(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(live_receipt_module, "ROOT", tmp_path)
    published = tmp_path / ".codex-studio" / "published"
    published.mkdir(parents=True, exist_ok=True)
    (published / "ea_proactive_ooda_operator_status.generated.json").write_text(
        json.dumps({"status": "ready_with_live_receipt"}),
        encoding="utf-8",
    )
    (published / "ea_proactive_ooda_gold_acceptance.generated.json").write_text(
        json.dumps({"status": "blocked_missing_proactive_packet_evidence"}),
        encoding="utf-8",
    )
    (published / "ea_continuous_improvement_goal_posture.generated.json").write_text(
        json.dumps(
            {
                "status": "blocked_real_world_acceptance",
                "operator_action_queue_count": 6,
            }
        ),
        encoding="utf-8",
    )
    (published / "ea_operator_action_required_digest.generated.json").write_text(
        json.dumps(
            {
                "status": "suppressed_duplicate",
                "notification_status": "suppressed_duplicate",
                "item_count": 1,
            }
        ),
        encoding="utf-8",
    )
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                    "dry_run": False,
                    "error_code": "",
                    "generated_at": "2026-07-08T12:38:09.960446+00:00",
                    "item_count": 1,
                    "notification_status": "sent",
                    "notified_ref_hashes": ["a" * 64],
                    "principal_id_hash": "b" * 64,
                    "telegram_message_ids": ["3004"],
                }
            )
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["followthrough_operator_status"] == "ready_with_live_receipt"
    assert report["followthrough_gold_acceptance_status"] == "blocked_missing_proactive_packet_evidence"
    assert report["followthrough_goal_posture_status"] == "blocked_real_world_acceptance"
    assert report["followthrough_goal_posture_queue_count"] == 6
    assert report["followthrough_digest_status"] == "suppressed_duplicate"
    assert report["followthrough_digest_notification_status"] == "suppressed_duplicate"
    assert report["followthrough_digest_item_count"] == 1
    assert report["followthrough_current_receipt_overlay_applied"] is True
    assert report["followthrough_current_receipt_overlay_components"] == [
        "operator_status",
        "gold_acceptance",
        "goal_posture",
        "operator_action_required_digest",
    ]


def test_verify_proactive_ooda_live_receipt_default_prefers_runtime_receipt_env(monkeypatch) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_RECEIPT_PATH", "/data/provider-ledger/proactive_ooda_latest_run.generated.json")
    monkeypatch.delenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_STATE_PATH", raising=False)

    module = importlib.reload(live_receipt_module)

    assert str(module.default_receipt_path()) == "/data/provider-ledger/proactive_ooda_latest_run.generated.json"


def test_verify_proactive_ooda_live_receipt_default_falls_back_to_state_sibling(monkeypatch) -> None:
    monkeypatch.delenv("EA_PROACTIVE_OODA_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH", raising=False)
    monkeypatch.setenv("EA_PROACTIVE_OODA_STATE_PATH", "/data/provider-ledger/proactive_ooda_notified.json")

    module = importlib.reload(live_receipt_module)

    assert str(module.default_receipt_path()) == "/data/provider-ledger/proactive_ooda_latest_run.generated.json"


def test_verify_proactive_ooda_live_receipt_default_prefers_runtime_receipt_when_present(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("EA_PROACTIVE_OODA_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_STATE_PATH", raising=False)

    module = importlib.reload(live_receipt_module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    runtime_receipt = tmp_path / "provider-ledger" / "proactive_ooda_latest_run.generated.json"
    runtime_receipt.parent.mkdir(parents=True, exist_ok=True)
    runtime_receipt.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "CURRENT_RUNTIME_RECEIPT", runtime_receipt)

    assert module.default_receipt_path() == runtime_receipt


def test_verify_proactive_ooda_live_receipt_default_prefers_repo_state_when_env_is_unset(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("EA_PROACTIVE_OODA_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_STATE_PATH", raising=False)

    module = importlib.reload(live_receipt_module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "CURRENT_RUNTIME_RECEIPT", tmp_path / "missing-runtime" / "proactive_ooda_latest_run.generated.json")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "proactive_ooda_notified.json").write_text("{}", encoding="utf-8")

    assert module.default_receipt_path() == tmp_path / "state" / "proactive_ooda_latest_run.generated.json"


def test_verify_proactive_ooda_live_receipt_main_prefers_runtime_container_when_default_runtime_path_is_not_local(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    module = importlib.reload(live_receipt_module)
    monkeypatch.setattr(module, "CURRENT_RUNTIME_RECEIPT", tmp_path / "missing-runtime" / "proactive_ooda_latest_run.generated.json")
    monkeypatch.setattr(module, "DEFAULT_RUNTIME_CONTAINER", "ea-proactive-ooda")
    monkeypatch.setattr(
        module,
        "_verify_receipt_via_runtime_container",
        lambda container_name: {
            "ok": True,
            "errors": [],
            "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
            "latest_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "latest_notification_status": "skipped_no_items",
            "archived_delivery_receipt_used": True,
            "archived_sent_receipt_used": True,
            "archived_operator_safe_mirror_receipt_used": False,
            "quiet_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "quiet_receipt_error_code": "skipped_no_items",
            "delivery_mode": "telegram_sent",
            "operator_safe_mirror_present": False,
            "notification_status": "sent",
            "item_count": 1,
            "delivery_channel": "telegram",
            "delivery_message_count": 1,
            "telegram_message_count": 1,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "delivery_guard_state": "eligible",
            "delivery_guard_deferred_reason": "",
            "quiet_hours_active": False,
            "interruption_budget_exhausted": False,
            "notification_requires_user_action": False,
            "followthrough_status": "ok",
            "followthrough_reason": "",
            "followthrough_error": "",
            "followthrough_run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "followthrough_operator_status": "ready_with_recovery_action",
            "followthrough_gold_acceptance_status": "blocked_operator_runtime_posture",
            "followthrough_goal_posture_status": "active_with_blockers",
            "followthrough_goal_posture_queue_count": 7,
            "followthrough_digest_status": "suppressed_duplicate",
            "followthrough_digest_notification_status": "suppressed_duplicate",
            "followthrough_digest_item_count": 1,
            "generated_at": "2026-07-08T12:38:09.960446+00:00",
        },
    )
    monkeypatch.setattr(module, "verify_receipt", lambda path: (_ for _ in ()).throw(AssertionError(f"unexpected local verify: {path}")))

    assert module.main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["receipt_path"] == "/data/provider-ledger/proactive_ooda_run_receipts/live.json"
    assert payload["archived_delivery_receipt_used"] is True


def test_verify_proactive_ooda_live_receipt_main_overlays_delegated_followthrough_component_receipts(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    module = importlib.reload(live_receipt_module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "CURRENT_RUNTIME_RECEIPT", tmp_path / "missing-runtime" / "proactive_ooda_latest_run.generated.json")
    monkeypatch.setattr(module, "DEFAULT_RUNTIME_CONTAINER", "ea-proactive-ooda")
    published = tmp_path / ".codex-studio" / "published"
    published.mkdir(parents=True, exist_ok=True)
    (published / "ea_proactive_ooda_operator_status.generated.json").write_text(
        json.dumps({"status": "ready_with_live_receipt"}),
        encoding="utf-8",
    )
    (published / "ea_proactive_ooda_gold_acceptance.generated.json").write_text(
        json.dumps({"status": "blocked_missing_proactive_packet_evidence"}),
        encoding="utf-8",
    )
    (published / "ea_continuous_improvement_goal_posture.generated.json").write_text(
        json.dumps({"status": "blocked_real_world_acceptance", "operator_action_queue_count": 6}),
        encoding="utf-8",
    )
    (published / "ea_operator_action_required_digest.generated.json").write_text(
        json.dumps(
            {
                "status": "suppressed_duplicate",
                "notification_status": "suppressed_duplicate",
                "item_count": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "_verify_receipt_via_runtime_container",
        lambda container_name: {
            "ok": True,
            "errors": [],
            "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
            "latest_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "latest_notification_status": "skipped_no_items",
            "archived_delivery_receipt_used": True,
            "archived_sent_receipt_used": True,
            "archived_operator_safe_mirror_receipt_used": False,
            "quiet_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "quiet_receipt_error_code": "skipped_no_items",
            "delivery_mode": "telegram_sent",
            "operator_safe_mirror_present": False,
            "notification_status": "sent",
            "item_count": 1,
            "delivery_channel": "telegram",
            "delivery_message_count": 1,
            "telegram_message_count": 1,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "delivery_guard_state": "eligible",
            "delivery_guard_deferred_reason": "",
            "quiet_hours_active": False,
            "interruption_budget_exhausted": False,
            "notification_requires_user_action": False,
            "followthrough_status": "ok",
            "followthrough_reason": "",
            "followthrough_error": "",
            "followthrough_run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "followthrough_operator_status": "ready_with_recovery_action",
            "followthrough_gold_acceptance_status": "blocked_operator_runtime_posture",
            "followthrough_goal_posture_status": "active_with_blockers",
            "followthrough_goal_posture_queue_count": 7,
            "followthrough_digest_status": "ready_to_send",
            "followthrough_digest_notification_status": "ready_to_send",
            "followthrough_digest_item_count": 2,
            "generated_at": "2026-07-08T12:38:09.960446+00:00",
        },
    )

    assert module.main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["followthrough_operator_status"] == "ready_with_live_receipt"
    assert payload["followthrough_gold_acceptance_status"] == "blocked_missing_proactive_packet_evidence"
    assert payload["followthrough_goal_posture_status"] == "blocked_real_world_acceptance"
    assert payload["followthrough_goal_posture_queue_count"] == 6
    assert payload["followthrough_digest_status"] == "suppressed_duplicate"
    assert payload["followthrough_digest_notification_status"] == "suppressed_duplicate"
    assert payload["followthrough_digest_item_count"] == 1
    assert payload["followthrough_current_receipt_overlay_applied"] is True


def test_verify_proactive_ooda_live_receipt_main_keeps_explicit_receipt_path_local(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    module = importlib.reload(live_receipt_module)
    monkeypatch.setattr(module, "CURRENT_RUNTIME_RECEIPT", tmp_path / "missing-runtime" / "proactive_ooda_latest_run.generated.json")
    monkeypatch.setattr(module, "_verify_receipt_via_runtime_container", lambda container_name: (_ for _ in ()).throw(AssertionError("unexpected runtime delegation")))
    receipt = tmp_path / "explicit.json"
    receipt.write_text(
        json.dumps(
            _with_followthrough(
                {
                    "dry_run": False,
                    "error_code": "",
                    "generated_at": "2026-06-20T14:58:30+00:00",
                    "item_count": 1,
                    "notification_status": "sent",
                    "notified_ref_hashes": ["a" * 64],
                    "principal_id_hash": "b" * 64,
                    "telegram_message_ids": ["3004"],
                }
            )
        ),
        encoding="utf-8",
    )

    assert module.main(["--receipt-path", str(receipt)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["receipt_path"] == str(receipt)
