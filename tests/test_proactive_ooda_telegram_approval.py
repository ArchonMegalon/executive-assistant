from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace


def test_prepare_proactive_ooda_telegram_approval_writes_callback_record_and_decodes(tmp_path) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:packet-1",
        staged_artifact_ref="safe_work_result:result-1",
        approval_prompt="Approve this staged shortlist.",
        staged_action_url="https://example.com/candidate",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        created_at="2026-06-28T10:00:00Z",
    )

    assert prepared["callback_token"]
    assert prepared["record_path"].is_file()
    assert prepared["inline_buttons"]
    assert prepared["url_buttons"] == [[("Open candidate", "https://example.com/candidate")]]
    decoded = approval.decode_proactive_ooda_telegram_callback(
        callback_data=prepared["inline_buttons"][0][0][1],
        chat_id="42",
        bot_token="telegram-token",
    )

    assert decoded["ok"] is True
    assert decoded["action"] == "approved"
    assert decoded["callback_token"] == prepared["callback_token"]


def test_apply_proactive_ooda_telegram_approval_callback_finalizes_and_marks_record(monkeypatch, tmp_path: Path) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:packet-2",
        staged_artifact_ref="safe_work_result:result-2",
        approval_prompt="Approve this staged shortlist.",
        staged_action_url="https://example.com/candidate",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )
    calls: dict[str, object] = {}

    def fake_finalize(**kwargs):
        calls["kwargs"] = kwargs
        return {
            "approval_outcome": {
                "outcome_id": "approval-1",
                "accepted": True,
                "outcome": "approved",
            },
            "gold_acceptance_path": tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json",
        }

    monkeypatch.setattr(approval, "finalize_proactive_ooda_approval_outcome", fake_finalize)

    result = approval.apply_proactive_ooda_telegram_approval_callback(
        callback_token=prepared["callback_token"],
        outcome="approved",
        principal_id="exec",
        actor="telegram:42",
        message_id="message-1",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    assert result["status"] == "recorded"
    assert result["outcome"] == "approved"
    assert calls["kwargs"]["packet_ref"] == "stage_packet:packet-2"
    assert calls["kwargs"]["staged_artifact_ref"] == "safe_work_result:result-2"
    assert calls["kwargs"]["source_kind"] == "telegram_button"
    stored = prepared["record_path"].read_text(encoding="utf-8")
    assert "telegram:42" not in stored
    assert "message-1" not in stored
    assert "approval-1" in stored


def test_apply_proactive_ooda_telegram_approval_callback_accepts_principal_alias_match(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import google_oauth as google_oauth_service
    from app.services import proactive_ooda_telegram_approval as approval

    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="cf-email:tibor.girschele@gmail.com",
        packet_ref="stage_packet:packet-alias-1",
        staged_artifact_ref="safe_work_result:result-alias-1",
        approval_prompt="Approve this staged draft.",
        staged_action_url="https://example.com/drafts",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        approved_execution_mode="record_outcome_only",
        approved_action="save_gmail_draft",
    )
    calls: dict[str, object] = {}

    def fake_finalize(**kwargs):
        calls["kwargs"] = kwargs
        return {
            "approval_outcome": {
                "outcome_id": "approval-alias-1",
                "accepted": True,
                "outcome": "approved",
            },
            "gold_acceptance_path": tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json",
        }

    monkeypatch.setattr(approval, "finalize_proactive_ooda_approval_outcome", fake_finalize)
    monkeypatch.setattr(
        google_oauth_service,
        "_principal_alias_candidates",
        lambda **kwargs: ("exec-1", "cf-email:tibor.girschele@gmail.com"),
    )

    result = approval.apply_proactive_ooda_telegram_approval_callback(
        callback_token=prepared["callback_token"],
        outcome="approved",
        principal_id="exec-1",
        actor="telegram:42",
        message_id="message-alias-1",
        container=SimpleNamespace(channel_runtime=SimpleNamespace(ingest_observation=lambda **kwargs: None)),
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    assert result["status"] == "recorded"
    assert result["outcome"] == "approved"
    assert result["execution"]["status"] == "already_executed"
    assert result["execution"]["action"] == "save_gmail_draft"
    assert calls["kwargs"]["principal_id"] == "exec-1"


def test_apply_proactive_ooda_telegram_approval_callback_accepts_google_binding_principal_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import google_oauth as google_oauth_service
    from app.services import proactive_ooda_telegram_approval as approval

    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="cf-email:work.tibor.girschele@gmail.com",
        packet_ref="stage_packet:packet-google-binding-fallback",
        staged_artifact_ref="safe_work_result:result-google-binding-fallback",
        approval_prompt="Approve this staged draft.",
        staged_action_url="https://example.com/drafts",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        approved_execution_mode="record_outcome_only",
        approved_action="save_gmail_draft",
    )
    calls: dict[str, object] = {}

    def fake_finalize(**kwargs):
        calls["kwargs"] = kwargs
        return {
            "approval_outcome": {
                "outcome_id": "approval-google-binding-fallback",
                "accepted": True,
                "outcome": "approved",
            },
            "gold_acceptance_path": tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json",
        }

    monkeypatch.setattr(approval, "finalize_proactive_ooda_approval_outcome", fake_finalize)
    monkeypatch.setattr(
        google_oauth_service,
        "_google_binding_principal_ids",
        lambda **kwargs: ("exec-1", "cf-email:work.tibor.girschele@gmail.com", "local-user"),
    )
    monkeypatch.setattr(
        google_oauth_service,
        "_principal_alias_candidates",
        lambda **kwargs: tuple(str(value or "").strip() for value in tuple(kwargs.get("principal_ids") or ()) if str(value or "").strip()),
    )

    result = approval.apply_proactive_ooda_telegram_approval_callback(
        callback_token=prepared["callback_token"],
        outcome="approved",
        principal_id="exec-1",
        actor="telegram:42",
        message_id="message-google-binding-fallback",
        container=SimpleNamespace(channel_runtime=SimpleNamespace(ingest_observation=lambda **kwargs: None)),
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    assert result["status"] == "recorded"
    assert result["outcome"] == "approved"
    assert result["execution"]["status"] == "already_executed"
    assert result["execution"]["action"] == "save_gmail_draft"
    assert calls["kwargs"]["principal_id"] == "exec-1"


def test_apply_proactive_ooda_telegram_approval_callback_accepts_telegram_default_principal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "cf-email:tibor.girschele@gmail.com")
    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="cf-email:tibor.girschele@gmail.com",
        packet_ref="stage_packet:packet-default-principal",
        staged_artifact_ref="safe_work_result:result-default-principal",
        approval_prompt="Approve this staged packet.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )
    calls: dict[str, object] = {}

    def fake_finalize(**kwargs):
        calls["kwargs"] = kwargs
        return {
            "approval_outcome": {
                "outcome_id": "approval-default-principal",
                "accepted": True,
                "outcome": "approved",
            },
            "gold_acceptance_path": tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json",
        }

    monkeypatch.setattr(approval, "finalize_proactive_ooda_approval_outcome", fake_finalize)

    result = approval.apply_proactive_ooda_telegram_approval_callback(
        callback_token=prepared["callback_token"],
        outcome="approved",
        principal_id="local-user",
        actor="telegram:42",
        message_id="message-default-principal",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    assert result["status"] == "recorded"
    assert result["outcome"] == "approved"
    assert calls["kwargs"]["principal_id"] == "local-user"
    stored = json.loads(prepared["record_path"].read_text(encoding="utf-8"))
    assert stored["status"] == "approved"
    assert "cf-email:tibor.girschele@gmail.com" not in json.dumps(stored)


def test_apply_proactive_ooda_telegram_approval_callback_rejects_default_principal_for_non_telegram_actor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "cf-email:tibor.girschele@gmail.com")
    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="cf-email:tibor.girschele@gmail.com",
        packet_ref="stage_packet:packet-non-telegram",
        staged_artifact_ref="safe_work_result:result-non-telegram",
        approval_prompt="Approve this staged packet.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )
    monkeypatch.setattr(
        approval,
        "finalize_proactive_ooda_approval_outcome",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("principal mismatch must not finalize")),
    )

    try:
        approval.apply_proactive_ooda_telegram_approval_callback(
            callback_token=prepared["callback_token"],
            outcome="approved",
            principal_id="local-user",
            actor="api:local-user",
            message_id="message-non-telegram",
            root=tmp_path,
            state_path="state/proactive_ooda_notified.json",
            receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        )
    except RuntimeError as exc:
        assert str(exc) == "proactive_ooda_approval_callback_principal_mismatch"
    else:
        raise AssertionError("expected non-Telegram actor to reject default-principal fallback")

    stored = json.loads(prepared["record_path"].read_text(encoding="utf-8"))
    assert stored["status"] == "pending"


def test_inspect_latest_telegram_gmail_draft_followthrough_reports_redacted_execution_observation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import google_oauth as google_oauth_service
    from app.services import proactive_ooda_telegram_approval as approval

    packet_ref = "stage_packet:packet-draft-1"
    staged_artifact_ref = "safe_work_result:result-draft-1"
    rows = [
        SimpleNamespace(
            created_at="2026-06-28T18:00:00Z",
            event_type="telegram.proactive_ooda_task_staged",
            observation_id="obs-stage-1",
            principal_id="cf-email:tibor.girschele@gmail.com",
            payload={
                "work_type": "draft",
                "approval_required": False,
                "stage_packet_ref": packet_ref,
                "safe_work_result_ref": staged_artifact_ref,
            },
        ),
        SimpleNamespace(
            created_at="2026-06-28T18:01:00Z",
            event_type="proactive_ooda.approved_action_execution",
            observation_id="obs-exec-1",
            principal_id="cf-email:tibor.girschele@gmail.com",
            payload={
                "packet_ref_sha256": hashlib.sha256(packet_ref.encode("utf-8")).hexdigest(),
                "staged_artifact_ref_sha256": hashlib.sha256(staged_artifact_ref.encode("utf-8")).hexdigest(),
                "status": "executed",
                "action": "save_gmail_draft",
                "work_type": "draft",
                "saved_at": "2026-06-28T18:01:00Z",
                "recipient_email_sha256": "recipient-hash",
                "gmail_draft_id_sha256": "draft-hash",
                "gmail_message_id_sha256": "message-hash",
                "draft_folder_url_sha256": "folder-hash",
                "raw_execution_payload_exposed": False,
            },
        ),
    ]
    container = SimpleNamespace(
        channel_runtime=SimpleNamespace(list_recent_observations=lambda **_kwargs: rows),
    )
    monkeypatch.setattr(
        google_oauth_service,
        "_google_binding_principal_ids",
        lambda **_kwargs: ("cf-email:tibor.girschele@gmail.com",),
    )

    report = approval.inspect_latest_telegram_gmail_draft_followthrough(
        container=container,
        principal_id="cf-email:tibor.girschele@gmail.com",
        root=tmp_path,
    )

    assert report["status"] == "already_executed"
    assert report["action"] == "save_gmail_draft"
    assert report["execution_status"] == "executed"
    assert report["execution_observation_present"] is True
    assert report["recipient_email_sha256_present"] is True
    assert report["gmail_draft_id_sha256_present"] is True
    assert report["gmail_message_id_sha256_present"] is True
    assert report["draft_folder_url_sha256_present"] is True
    assert report["raw_execution_payload_exposed"] is False
    assert "recipient_email" not in report
    assert "gmail_draft_id" not in report


def test_apply_proactive_ooda_telegram_approval_callback_falls_back_when_materialization_module_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:packet-missing-module",
        staged_artifact_ref="safe_work_result:result-missing-module",
        approval_prompt="Approve this staged shortlist.",
        staged_action_url="https://example.com/candidate",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    calls: dict[str, int] = {"finalize": 0}

    def _materialization_failure_then_success(**_kwargs):
        calls["finalize"] += 1
        if calls["finalize"] == 1:
            raise ModuleNotFoundError("No module named 'scripts.materialize_proactive_ooda_operator_status'")
        return {
            "approval_outcome": {
                "outcome_id": "approval-2",
                "accepted": True,
                "outcome": "approved",
            },
            "gold_acceptance_path": tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json",
            "operator_status_materialization": {
                "status": "failed",
                "error": "ModuleNotFoundError: scripts.materialize_proactive_ooda_operator_status",
                "path": tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_operator_status.generated.json",
            },
            "gold_acceptance_materialization": {
                "status": "skipped",
                "error": "operator_status_materialization_failed",
                "path": tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json",
            },
        }

    monkeypatch.setattr(approval, "finalize_proactive_ooda_approval_outcome", _materialization_failure_then_success)

    result = approval.apply_proactive_ooda_telegram_approval_callback(
        callback_token=prepared["callback_token"],
        outcome="approved",
        principal_id="exec",
        actor="telegram:42",
        message_id="message-1b",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    assert result["status"] == "recorded"
    assert result["outcome"] == "approved"
    assert calls["finalize"] == 2


def test_expire_stale_proactive_ooda_telegram_approval_callbacks_marks_only_expired_pending_records(
    tmp_path: Path,
) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    old_pending = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:packet-expire-old",
        staged_artifact_ref="safe_work_result:result-expire-old",
        approval_prompt="Approve old.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        created_at="2026-06-28T10:00:00Z",
    )
    live_pending = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:packet-expire-live",
        staged_artifact_ref="safe_work_result:result-expire-live",
        approval_prompt="Approve live.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        created_at="2026-06-28T11:00:00Z",
    )
    recorded = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:packet-expire-recorded",
        staged_artifact_ref="safe_work_result:result-expire-recorded",
        approval_prompt="Approve recorded.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        created_at="2026-06-28T12:00:00Z",
    )
    other_pending = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:packet-expire-other",
        staged_artifact_ref="safe_work_result:result-expire-other",
        approval_prompt="Approve other.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        created_at="2026-06-28T13:00:00Z",
    )

    old_record = json.loads(old_pending["record_path"].read_text(encoding="utf-8"))
    old_record["expires_at"] = "2000-01-01T00:00:00Z"
    old_pending["record_path"].write_text(json.dumps(old_record, indent=2) + "\n", encoding="utf-8")
    live_record = json.loads(live_pending["record_path"].read_text(encoding="utf-8"))
    live_record["expires_at"] = "2099-01-01T00:00:00Z"
    live_pending["record_path"].write_text(json.dumps(live_record, indent=2) + "\n", encoding="utf-8")
    recorded_record = json.loads(recorded["record_path"].read_text(encoding="utf-8"))
    recorded_record["status"] = "approved"
    recorded_record["expires_at"] = "2000-01-01T00:00:00Z"
    recorded["record_path"].write_text(json.dumps(recorded_record, indent=2) + "\n", encoding="utf-8")
    other_record = json.loads(other_pending["record_path"].read_text(encoding="utf-8"))
    other_record["expires_at"] = "2099-01-01T00:00:00Z"
    other_pending["record_path"].write_text(json.dumps(other_record, indent=2) + "\n", encoding="utf-8")

    result = approval.expire_stale_proactive_ooda_telegram_approval_callbacks(
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        supersede_noncurrent=True,
        active_packet_ref="stage_packet:packet-expire-live",
        active_staged_artifact_ref="safe_work_result:result-expire-live",
    )

    assert result["status"] == "ok"
    assert result["inspected_count"] == 4
    assert result["expired_count"] == 1
    assert result["superseded_count"] == 1
    assert result["skipped_count"] == 2
    assert json.loads(old_pending["record_path"].read_text(encoding="utf-8"))["status"] == "expired"
    assert json.loads(live_pending["record_path"].read_text(encoding="utf-8"))["status"] == "pending"
    assert json.loads(recorded["record_path"].read_text(encoding="utf-8"))["status"] == "approved"
    assert json.loads(other_pending["record_path"].read_text(encoding="utf-8"))["status"] == "superseded"


def test_expire_stale_callbacks_supersedes_pending_records_when_no_current_packet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    pending = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:old-packet",
        staged_artifact_ref="safe_work_result:old-result",
        approval_prompt="Approve old.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        created_at="2026-06-28T10:00:00Z",
    )
    pending_record = json.loads(pending["record_path"].read_text(encoding="utf-8"))
    pending_record["expires_at"] = "2099-01-01T00:00:00Z"
    pending["record_path"].write_text(json.dumps(pending_record, indent=2) + "\n", encoding="utf-8")

    monkeypatch.setattr(approval, "_current_runtime_packet_refs", lambda **_kwargs: ("", ""))

    result = approval.expire_stale_proactive_ooda_telegram_approval_callbacks(
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
        supersede_noncurrent=True,
    )

    assert result["status"] == "ok"
    assert result["inspected_count"] == 1
    assert result["expired_count"] == 0
    assert result["superseded_count"] == 1
    assert result["skipped_count"] == 0
    stored = json.loads(pending["record_path"].read_text(encoding="utf-8"))
    assert stored["status"] == "superseded"
    assert stored["superseded_reason"] == "not_current_proactive_ooda_packet"


def test_apply_proactive_ooda_telegram_approval_callback_expires_old_pending_record_without_finalize(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:packet-old-button",
        staged_artifact_ref="safe_work_result:result-old-button",
        approval_prompt="Approve old button.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )
    record = json.loads(prepared["record_path"].read_text(encoding="utf-8"))
    record["expires_at"] = "2000-01-01T00:00:00Z"
    prepared["record_path"].write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        approval,
        "finalize_proactive_ooda_approval_outcome",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("expired callback must not finalize")),
    )

    result = approval.apply_proactive_ooda_telegram_approval_callback(
        callback_token=prepared["callback_token"],
        outcome="approved",
        principal_id="exec",
        actor="telegram:42",
        message_id="message-old-button",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    stored = json.loads(prepared["record_path"].read_text(encoding="utf-8"))
    assert result["status"] == "expired"
    assert result["outcome"] == "expired"
    assert stored["status"] == "expired"
    assert stored["previous_status"] == "pending"
    assert stored["expiration_reason"] == "callback_ttl_elapsed"


def test_apply_proactive_ooda_telegram_approval_callback_supersedes_noncurrent_pending_record_without_finalize(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:old-packet",
        staged_artifact_ref="safe_work_result:old-result",
        approval_prompt="Approve old packet.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)
    current_packet_ref = "stage_packet:current-packet"
    (stage_dir / "current.json").write_text(
        json.dumps(
            {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": current_packet_ref,
                "stage": {"kind": "approval_packet"},
                "approval": {"required": True},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (safe_dir / "current.json").write_text(
        json.dumps(
            {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:current-result",
                "source_packet_ref_hash": hashlib.sha256(current_packet_ref.encode("utf-8")).hexdigest(),
                "status": "staged_for_user_decision",
                "approval": {"required": True},
                "approval_prompt": "Approve current packet.",
                "recommended_option_or_draft": {"kind": "draft", "value": "Current"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        approval,
        "finalize_proactive_ooda_approval_outcome",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("superseded callback must not finalize")),
    )

    result = approval.apply_proactive_ooda_telegram_approval_callback(
        callback_token=prepared["callback_token"],
        outcome="approved",
        principal_id="exec",
        actor="telegram:42",
        message_id="message-old-packet",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="provider-ledger/proactive_ooda_latest_run.generated.json",
    )

    stored = json.loads(prepared["record_path"].read_text(encoding="utf-8"))
    assert result["status"] == "superseded"
    assert result["outcome"] == "superseded"
    assert stored["status"] == "superseded"
    assert stored["previous_status"] == "pending"
    assert stored["superseded_reason"] == "not_current_proactive_ooda_packet"


def test_apply_proactive_ooda_telegram_approval_callback_preserves_assistant_grade_pending_when_newer_runtime_packet_is_internal_action(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import proactive_ooda_telegram_approval as approval

    prepared = approval.prepare_proactive_ooda_telegram_approval(
        principal_id="exec",
        packet_ref="stage_packet:old-browse-packet",
        staged_artifact_ref="safe_work_result:old-browse-result",
        approval_prompt="Approve old packet.",
        chat_id="42",
        bot_token="telegram-token",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="state/proactive_ooda_latest_run.generated.json",
    )
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    run_dir = tmp_path / "state" / "proactive_ooda_run_receipts"
    run_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    old_packet_ref = "stage_packet:old-browse-packet"
    old_result_ref = "safe_work_result:old-browse-result"
    old_stage = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": old_packet_ref,
        "stage": {"kind": "decision_packet"},
        "approval": {"required": True},
    }
    old_safe = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": old_result_ref,
        "source_packet_ref_hash": hashlib.sha256(old_packet_ref.encode("utf-8")).hexdigest(),
        "status": "staged_for_user_decision",
        "approval": {"required": True},
        "approval_prompt": "Approve old packet.",
        "recommended_option_or_draft": {"kind": "draft", "value": "Current browse-backed option"},
    }
    internal_packet_ref = "stage_packet:current-internal-packet"
    internal_result_ref = "safe_work_result:current-internal-result"
    internal_stage = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": internal_packet_ref,
        "stage": {"kind": "internal_action"},
        "approval": {"required": True},
        "safe_work_order": {"work_type": "record_internal_action"},
    }
    internal_safe = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": internal_result_ref,
        "source_packet_ref_hash": hashlib.sha256(internal_packet_ref.encode("utf-8")).hexdigest(),
        "status": "staged_for_user_decision",
        "approval": {"required": True},
        "approval_prompt": "Open Google setup and add the work account as a test user.",
        "staged_action_url": "https://myexternalbrain.com/integrations/google",
        "work_type": "record_internal_action",
        "recommended_option_or_draft": {"kind": "draft", "value": "Internal action"},
    }
    (stage_dir / "old-browse.json").write_text(json.dumps(old_stage, indent=2) + "\n", encoding="utf-8")
    (safe_dir / "old-browse.json").write_text(json.dumps(old_safe, indent=2) + "\n", encoding="utf-8")
    (stage_dir / "current-internal.json").write_text(json.dumps(internal_stage, indent=2) + "\n", encoding="utf-8")
    (safe_dir / "current-internal.json").write_text(json.dumps(internal_safe, indent=2) + "\n", encoding="utf-8")

    browse_receipt = run_dir / "20260629T082402_159262_0000-deferred-browse.json"
    internal_receipt = run_dir / "20260703T092744_575415_0000-failed-internal.json"
    browse_receipt.write_text(
        json.dumps(
            {
                "notification_status": "sent",
                "item_count": 1,
                "message_ids": ["111"],
                "stage_packet_ref_hashes": [hashlib.sha256(old_packet_ref.encode("utf-8")).hexdigest()],
                "safe_work_result_ref_hashes": [hashlib.sha256(old_result_ref.encode("utf-8")).hexdigest()],
                "stage_packet_output_dir": str(stage_dir),
                "safe_work_result_output_dir": str(safe_dir),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    internal_receipt.write_text(
        json.dumps(
            {
                "notification_status": "failed",
                "item_count": 1,
                "message_ids": [],
                "stage_packet_ref_hashes": [hashlib.sha256(internal_packet_ref.encode("utf-8")).hexdigest()],
                "safe_work_result_ref_hashes": [hashlib.sha256(internal_result_ref.encode("utf-8")).hexdigest()],
                "stage_packet_output_dir": str(stage_dir),
                "safe_work_result_output_dir": str(safe_dir),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    primary_receipt = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    primary_receipt.write_text(internal_receipt.read_text(encoding="utf-8"), encoding="utf-8")
    os.utime(browse_receipt, (1000, 1000))
    os.utime(internal_receipt, (2000, 2000))
    os.utime(primary_receipt, (2000, 2000))

    calls: dict[str, object] = {}

    def fake_finalize(**kwargs):
        calls["kwargs"] = kwargs
        return {
            "approval_outcome": {
                "outcome_id": "approval-preserved-1",
                "accepted": True,
                "outcome": "approved",
            },
            "gold_acceptance_path": tmp_path / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json",
        }

    monkeypatch.setattr(approval, "finalize_proactive_ooda_approval_outcome", fake_finalize)

    result = approval.apply_proactive_ooda_telegram_approval_callback(
        callback_token=prepared["callback_token"],
        outcome="approved",
        principal_id="exec",
        actor="telegram:42",
        message_id="message-old-packet",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        receipt_path="state/proactive_ooda_latest_run.generated.json",
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
    )

    stored = json.loads(prepared["record_path"].read_text(encoding="utf-8"))
    assert result["status"] == "recorded"
    assert result["outcome"] == "approved"
    assert calls["kwargs"]["packet_ref"] == old_packet_ref
    assert calls["kwargs"]["staged_artifact_ref"] == old_result_ref
    assert stored["status"] == "approved"
