from __future__ import annotations

import json
from pathlib import Path

from scripts.materialize_continuous_improvement_goal_posture import build_goal_posture
import scripts.materialize_continuous_improvement_goal_posture as posture_module
import scripts.verify_continuous_improvement_goal_posture as verifier_module
from scripts.verify_continuous_improvement_goal_posture import verify


def _write_receipt(
    root: Path,
    relative_path: str,
    *,
    status: str,
    source_git_head: str = "source-head",
    source_state_fingerprint: str = "source-fingerprint",
    **extra: object,
) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "contract_name": f"test.{path.stem}"}
    if source_git_head:
        payload["source_git_head"] = source_git_head
    if source_state_fingerprint:
        payload["source_state_fingerprint"] = source_state_fingerprint
    payload.update(extra)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _set_source_state(monkeypatch, *, head: str = "source-head", fingerprint: str = "source-fingerprint") -> None:
    monkeypatch.setattr(posture_module, "_git_head", lambda _root: head)
    monkeypatch.setattr(posture_module, "_source_fingerprint", lambda _root: fingerprint)
    monkeypatch.setattr(verifier_module, "_git_head", lambda _root: head)
    monkeypatch.setattr(verifier_module, "_source_fingerprint", lambda _root: fingerprint)


def _write_proactive_ooda_receipts(
    root: Path,
    *,
    source_git_head: str = "source-head",
    source_state_fingerprint: str = "source-fingerprint",
    gold_status: str = "ready_for_approval_outcome_capture",
    gold_claim_allowed: bool = False,
    gold_remaining_external_proofs: list[str] | None = None,
    gold_approval_accepted: bool = False,
) -> None:
    extra = {"source_git_head": source_git_head} if source_git_head else {}
    if source_state_fingerprint:
        extra["source_state_fingerprint"] = source_state_fingerprint
    if gold_remaining_external_proofs is None:
        gold_remaining_external_proofs = ["redacted explicit approval outcome for the proactive OODA packet"]
    _write_receipt(
        root,
        ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
        status=gold_status,
        gold_claim_allowed=gold_claim_allowed,
        remaining_external_proofs=gold_remaining_external_proofs,
        proofs={"approval_outcome": {"accepted": gold_approval_accepted}},
        **extra,
    )
    _write_receipt(
        root,
        ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
        status="ready_with_live_receipt",
        **extra,
    )


def _write_teable_recovery_proof_receipt(
    root: Path,
    *,
    status: str = "pass",
    source_git_head: str = "",
    source_state_fingerprint: str = "",
) -> None:
    _write_receipt(
        root,
        ".codex-studio/published/teable_env_recovery_proof.generated.json",
        status=status,
        source_git_head=source_git_head,
        source_state_fingerprint=source_state_fingerprint,
        generated_by="scripts/materialize_teable_env_recovery_proof.py",
        recovery_status="recovered" if status == "pass" else "failed",
        fresh_host_api_key_source="process_env",
        secret_values_redacted=True,
        drill_output_removed=True,
        privacy={
            "raw_paths_exposed": False,
            "raw_table_id_exposed": False,
            "raw_api_key_exposed": False,
            "secret_values_exposed": False,
        },
        env_files=[
            {
                "scope": "ea_root",
                "path_sha256": "1",
                "path_recorded": True,
                "restored": 1,
                "hash_verified": 1,
                "hash_mismatch_count": 0,
                "backup_created": False,
                "mode": "0o600",
            },
            {
                "scope": "ea_root_local",
                "path_sha256": "2",
                "path_recorded": True,
                "restored": 1,
                "hash_verified": 1,
                "hash_mismatch_count": 0,
                "backup_created": False,
                "mode": "0o600",
            },
            {
                "scope": "ea_service",
                "path_sha256": "3",
                "path_recorded": True,
                "restored": 1,
                "hash_verified": 1,
                "hash_mismatch_count": 0,
                "backup_created": False,
                "mode": "0o600",
            },
        ],
        referenced_files={
            "restored": 0,
            "hash_verified": 0,
            "hash_mismatch_count": 0,
            "backup_count": 0,
            "path_count": 0,
            "path_sha256": [],
            "modes": [],
        },
        verification={
            "status": "pass" if status == "pass" else "fail",
            "expected_rows": 3,
            "same_hash": 3 if status == "pass" else 0,
            "missing_count": 0,
            "different_hash_count": 0,
            "missing_secret_value_count": 0,
            "extra_restorable_count": 0,
        },
    )


def _write_acceptance_receipt_with_morning_brief_accepted(root: Path) -> None:
    accepted_row = {
        "accepted": True,
        "status": "accepted_redacted",
        "source_kind": "operator_admin",
        "recorded_at": "2026-06-30T10:41:57Z",
        "evidence_sha256": "evidence-hash",
        "actor_sha256": "actor-hash",
        "object_ref_sha256": "object-hash",
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }
    _write_receipt(
        root,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="partial_real_world_acceptance_evidence",
        acceptance_keys={"real_daily_morning_brief_accepted": accepted_row},
        acceptance_capture_requirements=[
            {
                "key": "real_daily_morning_brief_accepted",
                "proof_key": "real_daily_morning_brief_accepted",
                "accepted": True,
                "status": "accepted_redacted",
            }
        ],
    )


def _write_acceptance_receipt_with_pending_quality_keys(root: Path) -> None:
    accepted_row = {
        "accepted": True,
        "status": "accepted_redacted",
        "source_kind": "operator_admin",
        "recorded_at": "2026-06-30T10:41:57Z",
        "evidence_sha256": "evidence-hash",
        "actor_sha256": "actor-hash",
        "object_ref_sha256": "object-hash",
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }
    pending_keys = [
        "real_commitment_recovered_or_closed",
        "real_approved_action_audited",
        "real_provider_failure_recovered",
    ]
    acceptance_keys = {
        "real_daily_morning_brief_accepted": accepted_row,
        **{
            key: {
                "accepted": False,
                "status": "missing_or_invalid",
                "source_kind": "unknown",
                "recorded_at": "",
                "evidence_sha256": "",
                "actor_sha256": "",
                "object_ref_sha256": "",
                "raw_evidence_exposed": False,
                "raw_actor_exposed": False,
                "raw_object_ref_exposed": False,
            }
            for key in pending_keys
        },
    }
    _write_receipt(
        root,
        ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json",
        status="partial_real_world_acceptance_evidence",
        acceptance_keys=acceptance_keys,
        acceptance_capture_requirements=[
            {
                "key": "real_daily_morning_brief_accepted",
                "proof_key": "real_daily_morning_brief_accepted",
                "accepted": True,
                "status": "accepted_redacted",
            },
            *[
                {
                    "key": key,
                    "proof_key": key,
                    "accepted": False,
                    "status": "pending_real_world_evidence",
                }
                for key in pending_keys
            ],
        ],
    )


def test_stale_source_action_context_is_queue_only_and_redacted() -> None:
    context = posture_module._stale_source_action_context(
        receipts=[
            {
                "path": ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
                "present": True,
                "source_fresh_to_current_source": False,
            },
            {
                "path": ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
                "present": True,
                "source_fresh_to_current_source": True,
            },
        ],
        refresh_commands=[
            "PYTHONPATH=ea python3 ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
            "python3 scripts/verify_continuous_improvement_goal_posture.py --pretty",
        ],
    )

    assert context["kind"] == "stale_source_evidence_refresh"
    assert context["user_action_required"] is False
    assert context["delivery_policy"] == "queue_only"
    assert context["telegram_push_allowed"] is False
    assert context["non_action_progress_push_allowed"] is False
    assert context["stale_source_receipts"] == ["whatsapp_audiobook_live_delivery.generated.json"]
    assert "materialize_whatsapp_audiobook_live_delivery_receipt.py" in context["refresh_commands"][0]
    assert context["raw_private_context_exposed"] is False
    assert context["raw_chat_ids_exposed"] is False
    assert context["raw_token_exposed"] is False
    assert context["raw_secret_exposed"] is False


def test_accepted_morning_brief_evidence_is_satisfied_not_operator_action(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_acceptance_receipt_with_morning_brief_accepted(tmp_path)

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-06-22T15:00:00Z",
    )

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    morning_requirement = proof_requirements["morning_brief_operator_acceptance"]
    assert morning_requirement["status"] == "satisfied"
    assert morning_requirement["action_context"]["user_action_required"] is False
    assert morning_requirement["action_context"]["delivery_policy"] == "queue_only"
    assert morning_requirement["action_context"]["telegram_push_allowed"] is False
    assert morning_requirement["action_context"]["interruption_budget"] == "none"
    assert "real operator acceptance that the morning brief was worth reading" not in receipt["required_next_receipts"]
    assert "morning_brief_operator_acceptance" not in {
        item["key"] for item in receipt["operator_action_queue"]
    }


def test_pending_quality_acceptance_keys_become_action_required_queue_items(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_acceptance_receipt_with_pending_quality_keys(tmp_path)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(
        root=tmp_path,
        output_path=output,
        generated_at="2026-06-22T15:00:00Z",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    expected = {
        "ea_real_commitment_recovered_or_closed": "real_commitment_recovered_or_closed",
        "ea_real_approved_action_audited": "real_approved_action_audited",
        "ea_real_provider_failure_recovered": "real_provider_failure_recovered",
    }
    for proof_key, acceptance_key in expected.items():
        requirement = proof_requirements[proof_key]
        assert requirement["status"] == "pending_real_world_evidence"
        assert requirement["next_action_href"] == "/admin/actions/acceptance-evidence"
        assert requirement["next_action_method"] == "post"
        assert (
            requirement["next_action_form_href"]
            == f"/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key={acceptance_key}"
        )
        assert requirement["next_action_form_method"] == "get"
        context = requirement["action_context"]
        assert context["kind"] == "real_world_acceptance_capture"
        assert context["proof_key"] == acceptance_key
        assert (
            context["next_action_form_href"]
            == f"/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key={acceptance_key}"
        )
        assert context["user_action_required"] is True
        assert context["delivery_policy"] == "action_required_only"
        assert context["telegram_push_allowed"] is True
        assert context["interruption_budget"] == "action_required"
        assert context["raw_acceptance_text_exposed"] is False
        assert context["raw_actor_identity_exposed"] is False
        assert context["raw_object_reference_exposed"] is False

    queue = {item["key"]: item for item in receipt["operator_action_queue"]}
    assert receipt["next_action_key"] == "ea_real_commitment_recovered_or_closed"
    assert receipt["next_action"] == "record_redacted_real_commitment_recovery_evidence"
    assert receipt["operator_action_queue"][0]["key"] == "ea_real_commitment_recovered_or_closed"
    for proof_key, acceptance_key in expected.items():
        assert proof_key in queue
        assert queue[proof_key]["proof_key"] == acceptance_key
        assert (
            queue[proof_key]["next_action_form_href"]
            == f"/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key={acceptance_key}"
        )
        assert queue[proof_key]["user_action_required"] is True
        assert queue[proof_key]["delivery_policy"] == "action_required_only"
        assert queue[proof_key]["telegram_push_allowed"] is True
    assert verify(output, root=tmp_path) == []


def test_build_goal_posture_emits_required_lenses_and_conservative_claims(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="blocked_realtime_prerequisites",
        next_action="capture a consented real STT fixture",
        current_label="Memorial public-origin gold: blocked",
        room_audio_attestation={
            "status": "ready",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "required_check_ids": [
                "actual_device_checked",
                "actual_speaker_checked",
                "normal_spoken_turn_confirmed",
            ],
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
        next_action="collect real principal acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
        summary="Teable recovery command surface is mirrored and documented locally; a seeded fresh-host drill receipt is still required before any pass claim.",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/pocket_audio_archive_receipt.generated.json",
        status="pass",
        transcript_ingest_ready=True,
        evidence_mode="filesystem_archive_scan",
        next_action="maintain_pocket_ai_audio_transcript_archive",
        archive_files={
            "audio_file_total": 2,
            "metadata_json_total": 2,
            "raw_archive_root_exposed": False,
        },
        database_index={"latest_non_dismissed_missing_transcript_total": 0},
        privacy={
            "raw_transcript_text_exposed": False,
            "raw_archive_root_exposed": False,
            "raw_credential_exposed": False,
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_business_signal_readiness.generated.json",
        status="blocked_setup_required",
        business_mode=True,
        webhook_path="/v1/channels/telegram/business/ingest",
        allowed_updates=[
            "business_connection",
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
        ],
        missing_setup=["chat_allowlist_configured"],
        bot_registry={
            "token_present": True,
            "ingest_secret_present": True,
            "default_principal_present": True,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_principal_id_exposed": False,
        },
        chat_allowlist={
            "configured": False,
            "raw_chat_ids_exposed": False,
            "raw_chat_hashes_exposed": False,
        },
        privacy={
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_chat_ids_exposed": False,
            "raw_webhook_url_exposed": False,
            "raw_payload_exposed": False,
        },
        operator_action={
            "user_action_required": True,
            "instruction": "Connect the EA bot as Telegram Business/Secretary bot, allow only selected chats, configure the Business webhook, and set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES.",
            "missing_setup": ["chat_allowlist_configured"],
            "setup_checklist": [
                {
                    "key": "chat_allowlist_configured",
                    "label": "Choose Telegram Business chats EA may read",
                    "how": "Set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS.",
                }
            ],
            "telegram_message": "Action needed: Telegram Business/Secretary ingest is not live yet. Missing: Choose Telegram Business chats EA may read.",
            "raw_private_context_exposed": False,
            "raw_chat_ids_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="blocked",
        next_action="choose_sent_replacement_voice_sample",
        operator_action_packet={
            "user_action_required": True,
            "instruction": "Choose one sent replacement voice sample in Telegram.",
            "sent_samples_cover_expected": True,
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
        duplicate_suppression={
            "action_required_only": True,
            "only_current_jobs_can_require_user_action": True,
            "superseded_duplicate_candidate_count": 3,
            "suppressed_pending_voice_duplicate_count": 1,
            "active_pending_voice_job_count": 1,
            "duplicate_active_pending_source_key_count": 0,
            "duplicate_active_pending_source_keys_sha256": [],
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
        pending_user_selected_voice_jobs=[
            {
                "replacement_candidate_count": 1,
                "replacement_candidate_labels": ["Dieter"],
                "author_gender_signal": "male",
                "author_gender_match_count": 1,
                "author_gender_mismatch_count": 0,
                "author_gender_matched_candidates_only": True,
                "voice_sample_delivery_status": "sent",
                "voice_sample_delivery_sent_count": 1,
                "voice_sample_delivery_expected_count": 1,
                "raw_voice_ids_exposed": False,
                "callback_tokens_exposed": False,
            }
        ],
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="blocked",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="waiting",
    )
    _write_proactive_ooda_receipts(tmp_path)

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-06-22T15:00:00Z",
    )

    assert receipt["contract_name"] == "ea.continuous_improvement_goal_posture.v1"
    assert receipt["execution_lenses"] == ["detect", "decide", "deliver", "recover", "prove"]
    assert receipt["overall_status"] == "blocked_real_world_acceptance"
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["real_use_claim_allowed"] is False
    assert "paid-human-assistant-grade proactive OODA" in receipt["goal_shorthand"]
    assert "transcript-aware ingest" in receipt["goal_shorthand"]
    assert "auditor-passed decision-ready packets" in receipt["goal_shorthand"]
    assert "Teable-mirrored current/stale state" in receipt["goal_shorthand"]
    assert "real proactive OODA packet accepted with action-required-only routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, stale-approval, and decision facts, and explicit approval outcome" in receipt["required_next_receipts"]
    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    assert set(proof_requirements) == {
        "morning_brief_operator_acceptance",
        "weekly_signal_to_decision_review_acceptance",
        "proactive_ooda_packet_acceptance",
        "fresh_host_teable_recovery_drill",
        "telegram_business_signal_setup",
        "manfred_stt_tts_realtime_conversation",
        "telegram_audiobook_live_delivery",
        "whatsapp_audiobook_live_delivery",
    }
    assert {item["required_next_receipt"] for item in proof_requirements.values()} == set(receipt["required_next_receipts"])
    assert proof_requirements["proactive_ooda_packet_acceptance"]["evidence_kind"] == "approval_outcome"
    assert (
        proof_requirements["proactive_ooda_packet_acceptance"]["next_action"]
        == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    )
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_href"] == "/admin/proactive-ooda/approval"
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_label"] == "Open approval capture"
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_method"] == "get"
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_form_href"] == "/admin/proactive-ooda/approval"
    assert proof_requirements["proactive_ooda_packet_acceptance"]["next_action_form_method"] == "get"
    assert proof_requirements["morning_brief_operator_acceptance"]["next_action_href"] == "/admin/actions/acceptance-evidence"
    assert proof_requirements["morning_brief_operator_acceptance"]["next_action_method"] == "post"
    assert (
        proof_requirements["morning_brief_operator_acceptance"]["next_action_form_href"]
        == "/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_daily_morning_brief_accepted"
    )
    assert proof_requirements["morning_brief_operator_acceptance"]["next_action_form_method"] == "get"
    morning_context = proof_requirements["morning_brief_operator_acceptance"]["action_context"]
    assert morning_context["kind"] == "real_world_acceptance_capture"
    assert morning_context["proof_key"] == "real_daily_morning_brief_accepted"
    assert morning_context["user_action_required"] is True
    assert morning_context["delivery_policy"] == "action_required_only"
    assert morning_context["telegram_push_allowed"] is True
    assert morning_context["non_action_progress_push_allowed"] is False
    assert morning_context["raw_acceptance_text_exposed"] is False
    assert morning_context["raw_actor_identity_exposed"] is False
    assert morning_context["raw_object_reference_exposed"] is False
    assert proof_requirements["weekly_signal_to_decision_review_acceptance"]["next_action_href"] == "/admin/actions/signal-to-decision-evidence"
    assert proof_requirements["weekly_signal_to_decision_review_acceptance"]["next_action_method"] == "post"
    assert (
        proof_requirements["weekly_signal_to_decision_review_acceptance"]["next_action_form_href"]
        == "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review"
    )
    assert proof_requirements["weekly_signal_to_decision_review_acceptance"]["next_action_form_method"] == "get"
    weekly_context = proof_requirements["weekly_signal_to_decision_review_acceptance"]["action_context"]
    assert weekly_context["kind"] == "real_world_acceptance_capture"
    assert weekly_context["evidence_part"] == "review"
    assert weekly_context["user_action_required"] is True
    assert weekly_context["delivery_policy"] == "action_required_only"
    assert weekly_context["telegram_push_allowed"] is True
    assert weekly_context["non_action_progress_push_allowed"] is False
    assert any(
        "ea_proactive_ooda_gold_acceptance.generated.json" in surface
        for surface in proof_requirements["proactive_ooda_packet_acceptance"]["capture_surfaces"]
    )
    assert proof_requirements["fresh_host_teable_recovery_drill"]["lens"] == "recover"
    assert proof_requirements["fresh_host_teable_recovery_drill"]["evidence_kind"] == "fresh_host_recovery_drill"
    assert proof_requirements["telegram_business_signal_setup"]["evidence_kind"] == "secretary_bot_signal_ingest_setup"
    telegram_business_context = proof_requirements["telegram_business_signal_setup"]["action_context"]
    assert telegram_business_context["user_action_required"] is True
    assert telegram_business_context["missing_setup"] == ["chat_allowlist_configured"]
    assert telegram_business_context["setup_checklist"] == [
        {
            "key": "chat_allowlist_configured",
            "label": "Choose Telegram Business chats EA may read",
            "how": "Set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS.",
        }
    ]
    assert "Action needed:" in telegram_business_context["telegram_message"]
    assert telegram_business_context["raw_chat_ids_exposed"] is False
    assert telegram_business_context["raw_token_exposed"] is False
    assert telegram_business_context["raw_secret_exposed"] is False
    assert proof_requirements["telegram_audiobook_live_delivery"]["evidence_kind"] == "live_delivery_receipt"
    assert (
        proof_requirements["telegram_audiobook_live_delivery"]["next_action"]
        == "choose_sent_replacement_voice_sample"
    )
    assert proof_requirements["telegram_audiobook_live_delivery"]["next_action_href"] == "/integrations/telegram"
    assert proof_requirements["telegram_audiobook_live_delivery"]["next_action_method"] == "get"
    manfred_context = proof_requirements["manfred_stt_tts_realtime_conversation"]["action_context"]
    assert manfred_context["kind"] == "manual_room_audio_attestation"
    assert manfred_context["user_action_required"] is True
    assert manfred_context["delivery_policy"] == "action_required_only"
    assert manfred_context["telegram_push_allowed"] is True
    assert manfred_context["manual_only"] is True
    assert manfred_context["ci_must_not_auto_assert"] is True
    assert manfred_context["required_check_count"] == 3
    assert manfred_context["required_check_ids"] == [
        "actual_device_checked",
        "actual_speaker_checked",
        "normal_spoken_turn_confirmed",
    ]
    assert manfred_context["raw_transcript_fields_exposed"] is False
    assert manfred_context["candidate_raw_text_fields_exposed"] is False
    telegram_action_context = proof_requirements["telegram_audiobook_live_delivery"]["action_context"]
    assert telegram_action_context["kind"] == "telegram_audiobook_voice_choice"
    assert telegram_action_context["operator_action"] == "choose_sent_replacement_voice_sample"
    assert telegram_action_context["user_action_required"] is True
    assert telegram_action_context["instruction"] == "Choose one sent replacement voice sample in Telegram."
    assert telegram_action_context["sent_samples_cover_expected"] is True
    assert telegram_action_context["candidate_labels"] == ["Dieter"]
    assert telegram_action_context["candidate_label_count"] == 1
    assert telegram_action_context["distinct_candidate_label_count"] == 1
    assert telegram_action_context["candidate_labels_distinct"] is True
    assert telegram_action_context["author_gender_signal"] == "male"
    assert telegram_action_context["author_gender_match_count"] == 1
    assert telegram_action_context["author_gender_mismatch_count"] == 0
    assert telegram_action_context["author_gender_matched_candidates_only"] is True
    assert telegram_action_context["voice_sample_delivery_status"] == "sent"
    assert telegram_action_context["raw_voice_ids_exposed"] is False
    assert telegram_action_context["callback_tokens_exposed"] is False
    duplicate_suppression = telegram_action_context["duplicate_suppression"]
    assert duplicate_suppression["action_required_only"] is True
    assert duplicate_suppression["only_current_jobs_can_require_user_action"] is True
    assert duplicate_suppression["active_pending_voice_job_count"] == 1
    assert duplicate_suppression["duplicate_active_pending_source_key_count"] == 0
    assert duplicate_suppression["raw_voice_ids_exposed"] is False
    assert duplicate_suppression["callback_tokens_exposed"] is False
    assert receipt["next_action_key"] == "morning_brief_operator_acceptance"
    assert receipt["next_action"] == "record_redacted_operator_acceptance_for_real_morning_brief"
    assert receipt["next_action_href"] == "/admin/actions/acceptance-evidence"
    assert receipt["next_action_label"] == "Record a real-use outcome"
    assert receipt["next_action_method"] == "post"
    assert (
        receipt["next_action_form_href"]
        == "/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_daily_morning_brief_accepted"
    )
    assert receipt["next_action_form_method"] == "get"
    assert receipt["next_action_instruction"] == "Record redacted real-world acceptance evidence for the morning brief."
    assert receipt["operator_action_queue"][0]["key"] == "morning_brief_operator_acceptance"
    assert receipt["operator_action_queue"][0]["user_action_required"] is True
    assert receipt["operator_action_queue"][0]["delivery_policy"] == "action_required_only"
    assert receipt["operator_action_queue"][0]["telegram_push_allowed"] is True
    assert receipt["operator_action_queue"][0]["interruption_budget"] == "action_required"
    assert receipt["operator_action_queue"][0]["quiet_hours_respected"] is True
    assert receipt["operator_action_queue"][0]["non_action_progress_push_allowed"] is False
    assert receipt["operator_action_queue"][0]["irreversible_actions_consent_gated"] is True
    assert receipt["operator_action_queue"][0]["raw_private_context_exposed"] is False
    telegram_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "telegram_audiobook_live_delivery"
    )
    assert telegram_action["candidate_labels"] == ["Dieter"]
    assert telegram_action["candidate_labels_distinct"] is True
    assert telegram_action["author_gender_signal"] == "male"
    assert telegram_action["author_gender_matched_candidates_only"] is True
    assert telegram_action["sent_samples_cover_expected"] is True
    assert telegram_action["duplicate_suppression"]["active_pending_voice_job_count"] == 1
    manfred_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "manfred_stt_tts_realtime_conversation"
    )
    assert manfred_action["user_action_required"] is True
    assert manfred_action["delivery_policy"] == "action_required_only"
    assert manfred_action["telegram_push_allowed"] is True
    assert manfred_action["manual_only"] is True
    assert manfred_action["ci_must_not_auto_assert"] is True
    assert manfred_action["required_check_count"] == 3
    assert manfred_action["raw_transcript_fields_exposed"] is False
    assert manfred_action["candidate_raw_text_fields_exposed"] is False
    morning_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "morning_brief_operator_acceptance"
    )
    assert morning_action["user_action_required"] is True
    assert morning_action["delivery_policy"] == "action_required_only"
    assert morning_action["telegram_push_allowed"] is True
    assert morning_action["interruption_budget"] == "action_required"
    assert morning_action["proof_key"] == "real_daily_morning_brief_accepted"
    assert (
        morning_action["next_action_form_href"]
        == "/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_daily_morning_brief_accepted"
    )
    assert morning_action["raw_acceptance_text_exposed"] is False
    assert morning_action["raw_actor_identity_exposed"] is False
    assert morning_action["raw_object_reference_exposed"] is False
    weekly_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "weekly_signal_to_decision_review_acceptance"
    )
    assert weekly_action["user_action_required"] is True
    assert weekly_action["delivery_policy"] == "action_required_only"
    assert weekly_action["telegram_push_allowed"] is True
    assert weekly_action["evidence_part"] == "review"
    assert (
        weekly_action["next_action_form_href"]
        == "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review"
    )
    assert weekly_action["non_action_progress_push_allowed"] is False
    telegram_business_action = next(
        item for item in receipt["operator_action_queue"] if item["key"] == "telegram_business_signal_setup"
    )
    assert telegram_business_action["user_action_required"] is True
    assert telegram_business_action["delivery_policy"] == "action_required_only"
    assert telegram_business_action["telegram_push_allowed"] is True
    assert telegram_business_action["interruption_budget"] == "action_required"
    assert telegram_business_action["missing_setup"] == ["chat_allowlist_configured"]
    assert telegram_business_action["setup_checklist"] == [
        {
            "key": "chat_allowlist_configured",
            "label": "Choose Telegram Business chats EA may read",
            "how": "Set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS.",
        }
    ]
    assert "Action needed:" in telegram_business_action["telegram_message"]
    assert telegram_business_action["raw_private_context_exposed"] is False
    assert telegram_business_action["raw_chat_ids_exposed"] is False
    assert telegram_business_action["raw_token_exposed"] is False
    assert telegram_business_action["raw_secret_exposed"] is False
    assert receipt["operator_delivery_policy"] == {
        "action_required_only": True,
        "non_action_progress_push_allowed": False,
        "quiet_hours_respected": True,
        "irreversible_actions_consent_gated": True,
        "telegram_push_allowed_for_next_action": True,
        "next_action_requires_user": True,
        "next_action_delivery_policy": "action_required_only",
    }
    for row in receipt["operator_action_queue"][1:]:
        if row["user_action_required"]:
            assert row["delivery_policy"] == "action_required_only"
            assert row["telegram_push_allowed"] is True
            assert row["interruption_budget"] == "action_required"
            continue
        assert row["delivery_policy"] == "queue_only"
        assert row["telegram_push_allowed"] is False
        assert row["interruption_budget"] == "none"
        assert row["quiet_hours_respected"] is True
        assert row["non_action_progress_push_allowed"] is False
        assert row["irreversible_actions_consent_gated"] is True
    assert {item["key"] for item in receipt["operator_action_queue"]} == {
        key for key, item in proof_requirements.items() if item["status"] != "satisfied"
    }
    assert "Telegram is an action surface, not a progress log; proactive delivery must stay quiet unless the user needs to approve, choose, unblock, review, or answer something." in receipt["rules"]
    assert "Proactive OODA packets must pass a context/provider-fit auditor before user delivery; reachable URLs, extracted email addresses, or generic search hits are not sufficient." in receipt["rules"]
    assert "Pocket.ai or other consented audio transcripts may feed OODA only as approved signals with privacy, retention, source, and current/stale status preserved." in receipt["rules"]
    assert "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth." in receipt["rules"]

    lenses = {lens["key"]: lens for lens in receipt["lenses"]}
    assert lenses["detect"]["status"] == "ready_local_packet_pending_operator_acceptance"
    assert "Pocket/audio transcript ingest is pass" in lenses["detect"]["summary"]
    transcript_evidence = lenses["detect"]["transcript_ingest_evidence"]
    assert transcript_evidence["key"] == "pocket_ai_audio_transcripts"
    assert transcript_evidence["status"] == "pass"
    assert transcript_evidence["transcript_ingest_ready"] is True
    assert transcript_evidence["archive_audio_file_total"] == 2
    assert transcript_evidence["archive_metadata_json_total"] == 2
    assert transcript_evidence["missing_transcript_total"] == 0
    assert transcript_evidence["raw_transcript_text_exposed"] is False
    assert transcript_evidence["raw_archive_root_exposed"] is False
    assert transcript_evidence["raw_credential_exposed"] is False
    assert lenses["decide"]["status"] == "ready_local_evidence"
    assert lenses["deliver"]["status"] == "mixed_local_progress"
    assert lenses["recover"]["status"] == "ready_local_audit"
    assert "make probe-teable-recovery" in lenses["recover"]["verifier_commands"]
    assert lenses["prove"]["status"] == "blocked_real_world_acceptance"
    assert "proactive OODA shortlist" in lenses["detect"]["summary"]
    assert "proactive OODA packet loop" in lenses["decide"]["summary"]

    deliver_components = {component["key"]: component for component in lenses["deliver"]["components"]}
    assert deliver_components["promo_media"]["status"] == "ready_local_evidence"
    assert deliver_components["manfred_speech"]["status"] == "blocked_realtime_prerequisites"
    assert deliver_components["telegram_audiobook"]["status"] == "blocked"
    assert deliver_components["whatsapp_audiobook"]["status"] == "blocked"
    assert "deliver:manfred_speech=blocked_realtime_prerequisites" in receipt["blocking_reasons"]
    assert "deliver:telegram_audiobook=blocked" in receipt["blocking_reasons"]
    assert "deliver:whatsapp_audiobook=blocked" in receipt["blocking_reasons"]

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    assert verify(output) == []

    receipt["acceptance_proof_requirements"] = [
        item
        for item in list(receipt["acceptance_proof_requirements"])
        if item["key"] != "telegram_audiobook_live_delivery"
    ]
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    assert (
        "active blocker deliver:telegram_audiobook must have acceptance proof requirement telegram_audiobook_live_delivery"
        in verify(output)
    )


def test_build_goal_posture_marks_recover_pass_when_mirrored_fresh_host_proof_exists(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass", source_git_head="source-head")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(tmp_path)

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-06-29T20:00:00Z",
    )

    lenses = {lens["key"]: lens for lens in receipt["lenses"]}
    proof_keys = {item["key"] for item in receipt["acceptance_proof_requirements"]}
    assert lenses["recover"]["status"] == "pass"
    assert "fresh_host_teable_recovery_drill" not in proof_keys
    assert "fresh-host Teable recovery drill receipt mirrored into the repo" not in receipt["required_next_receipts"]


def test_build_goal_posture_keeps_recover_audit_when_recovery_proof_is_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass", source_git_head="old-head")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(tmp_path)

    receipt = build_goal_posture(
        root=tmp_path,
        output_path=Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
        generated_at="2026-06-29T20:05:00Z",
    )

    lenses = {lens["key"]: lens for lens in receipt["lenses"]}
    proof_keys = {item["key"] for item in receipt["acceptance_proof_requirements"]}
    assert lenses["recover"]["status"] == "ready_local_audit"
    assert "source-state evidence is stale" in lenses["recover"]["summary"]
    assert "fresh_host_teable_recovery_drill" in proof_keys
    recovery_sources = {
        Path(source["path"]).name: source
        for source in lenses["recover"]["source_receipts"]
    }
    assert recovery_sources["teable_env_recovery_proof.generated.json"]["source_fresh_to_current_source"] is False


def test_goal_posture_verifier_rejects_recover_pass_with_stale_recovery_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass", source_git_head="old-head")
    receipt = {
        "contract_name": "ea.continuous_improvement_goal_posture.v1",
        "goal_doc": ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md",
        "goal_completion_claim_allowed": False,
        "goal_shorthand": "paid-human-assistant-grade proactive OODA governed by owning truth planes",
        "source_git_head": "source-head",
        "source_state_fingerprint": "source-fingerprint",
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "execution_lenses": ["detect", "decide", "deliver", "recover", "prove"],
        "overall_status": "blocked_real_world_acceptance",
        "blocking_reasons": [],
        "required_next_receipts": [],
        "acceptance_proof_requirements": [],
        "rules": [
            "The recover lens may use a mirrored local readiness receipt, but it must not claim pass until a source-fresh fresh-host Teable recovery drill receipt is mirrored.",
            "Irreversible purchases, bookings, cancellations, outbound commitments, and sent messages must stay consent-gated even when proactive OODA staging is automated.",
            "Telegram is an action surface, not a progress log; proactive delivery must stay quiet unless the user needs to approve, choose, unblock, review, or answer something.",
            "Proactive OODA packets must pass a context/provider-fit auditor before user delivery; reachable URLs, extracted email addresses, or generic search hits are not sufficient.",
            "Pocket.ai or other consented audio transcripts may feed OODA only as approved signals with privacy, retention, source, and current/stale status preserved.",
            "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth.",
        ],
        "lenses": [
            {"key": "detect", "status": "ready_local_packet_pending_operator_acceptance", "verifier_commands": ["cmd"], "source_receipts": []},
            {"key": "decide", "status": "ready_local_evidence", "verifier_commands": ["cmd"], "source_receipts": []},
            {"key": "deliver", "status": "mixed_local_progress", "verifier_commands": ["cmd"], "components": [
                {"key": "promo_media", "status": "ready_local_evidence"},
                {"key": "manfred_speech", "status": "pass"},
                {"key": "telegram_audiobook", "status": "pass"},
                {"key": "whatsapp_audiobook", "status": "pass"},
            ]},
            {
                "key": "recover",
                "status": "pass",
                "verifier_commands": ["cmd"],
                "source_receipts": [
                    {
                        "path": ".codex-studio/published/teable_env_recovery_readiness.generated.json",
                        "present": True,
                        "status": "ready_local_audit",
                    },
                    {
                        "path": ".codex-studio/published/teable_env_recovery_proof.generated.json",
                        "present": True,
                        "status": "pass",
                        "source_fresh_to_current_source": False,
                    },
                ],
            },
            {"key": "prove", "status": "blocked_real_world_acceptance", "verifier_commands": ["cmd"], "source_receipts": []},
        ],
    }
    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    assert "recover lens pass requires a source-fresh Teable recovery proof receipt" in verify(output, root=tmp_path)


def test_goal_posture_verifier_accepts_materialized_receipt(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="blocked_realtime_prerequisites",
        next_action="capture a consented real STT fixture",
        current_label="Memorial public-origin gold: blocked",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
        next_action="collect real principal acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
        summary="Teable recovery command surface is mirrored and documented locally; a seeded fresh-host drill receipt is still required before any pass claim.",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="blocked",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="waiting",
    )
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:00:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output)
    assert issues == []


def test_goal_posture_verifier_rejects_uncovered_acceptance_proof_requirement(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
        next_action="maintain consented real STT fixture",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
        next_action="collect real principal acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:15:00Z")
    receipt["acceptance_proof_requirements"] = [
        item
        for item in list(receipt["acceptance_proof_requirements"])
        if item["key"] != "proactive_ooda_packet_acceptance"
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output)
    assert "acceptance_proof_requirements must cover every required_next_receipts item exactly" in issues
    assert "acceptance_proof_requirements must include proactive_ooda_packet_acceptance" in issues


def test_goal_posture_verifier_requires_acceptance_requirement_action_surface(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="blocked_realtime_prerequisites",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="blocked",
        next_action="choose_sent_replacement_voice_sample",
    )
    for relative_path in (
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
    ):
        _write_receipt(tmp_path, relative_path, status="pass")
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-30T05:15:00Z")
    receipt["acceptance_proof_requirements"][0]["next_action_href"] = ""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output, root=tmp_path)

    assert "acceptance proof requirement morning_brief_operator_acceptance missing next_action_href" in issues
    assert (
        "acceptance proof requirement morning_brief_operator_acceptance next_action_href must target "
        "/admin/actions/acceptance-evidence"
    ) in issues


def test_goal_posture_verifier_rejects_stale_proactive_ooda_source_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch, head="fresh-source-head", fingerprint="fresh-source-fingerprint")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        source_git_head="stale-source-head",
        source_state_fingerprint="stale-source-fingerprint",
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:25:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output, root=tmp_path)
    assert (
        "proactive_ooda_packet_acceptance source receipt stale: .codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
        in issues
    )
    assert (
        "proactive_ooda_packet_acceptance source receipt stale: .codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
        in issues
    )


def test_goal_posture_marks_passed_proactive_ooda_gold_as_satisfied(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="pass",
        gold_claim_allowed=True,
        gold_remaining_external_proofs=[],
        gold_approval_accepted=True,
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-30T05:00:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    proactive = proof_requirements["proactive_ooda_packet_acceptance"]
    assert proactive["status"] == "satisfied"
    assert proactive["next_action"] == "maintain_proactive_ooda_gold_acceptance_evidence"
    assert proactive["next_action_href"] == "/app/today"
    assert proactive["next_action_method"] == "get"
    assert posture_module.PROACTIVE_OODA_ACCEPTANCE_RECEIPT not in receipt["required_next_receipts"]
    assert verify(output, root=tmp_path) == []


def test_goal_posture_verifier_accepts_waiting_for_live_epub_component_status(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="blocked_realtime_prerequisites",
        next_action="capture a consented real STT fixture",
        current_label="Memorial public-origin gold: blocked",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
        next_action="collect real principal acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
        next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
        summary="Teable recovery command surface is mirrored and documented locally; a seeded fresh-host drill receipt is still required before any pass claim.",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="ready_for_live_epub_delivery_test",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="waiting_for_live_epub",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="waiting_for_live_epub",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="waiting",
    )
    _write_proactive_ooda_receipts(tmp_path)

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:30:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verify(output)
    assert issues == []


def test_goal_posture_models_failed_whatsapp_playback_as_queue_only_repair(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(tmp_path, status="pass")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="failed",
        failed=1,
        attempted=1,
        results=[
            {
                "status": "failed",
                "passed": False,
                "reason": "play_failed",
                "track_response_status": 500,
                "track_content_type": "text/html",
                "media_error": True,
                "media_error_code": 4,
                "public_share_host": "audiobookshelf.example.test",
                "raw_url_exposed": False,
            }
        ],
        privacy={"raw_public_share_url_exposed": False, "raw_track_url_exposed": False},
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="pass",
        gold_claim_allowed=True,
        gold_remaining_external_proofs=[],
        gold_approval_accepted=True,
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-30T09:00:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    whatsapp = proof_requirements["whatsapp_audiobook_live_delivery"]
    assert whatsapp["action_context"]["kind"] == "public_share_playback_failure"
    assert whatsapp["action_context"]["user_action_required"] is False
    assert whatsapp["action_context"]["telegram_push_allowed"] is False
    assert whatsapp["action_context"]["track_response_status"] == 500
    assert whatsapp["action_context"]["track_content_type"] == "text/html"
    queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "whatsapp_audiobook_live_delivery")
    assert queue_row["user_action_required"] is False
    assert queue_row["telegram_push_allowed"] is False
    assert queue_row["track_response_status"] == 500
    assert queue_row["raw_public_share_url_exposed"] is False
    assert queue_row["raw_track_url_exposed"] is False
    assert "deliver:whatsapp_audiobook=failed" in receipt["blocking_reasons"]
    assert verify(output, root=tmp_path) == []


def test_goal_posture_models_blocked_whatsapp_playback_as_queue_only_repair(tmp_path: Path, monkeypatch) -> None:
    _set_source_state(monkeypatch)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_delivery_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_business_signal_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/pocket_audio_archive_receipt.generated.json",
        status="pass",
        transcript_ingest_ready=True,
        archive_audio_file_total=1,
        archive_metadata_json_total=1,
        missing_transcript_total=0,
    )
    _write_teable_recovery_proof_receipt(tmp_path)
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="blocked",
        recommended_action="fix_whatsapp_action_processor_run",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="blocked",
        next_action="run_public_share_machine_playback_e2e_before_claiming_live_delivery",
        failed_codes=["valid_live_audiobook_delivery_missing", "machine_playback_e2e_not_verified"],
        selected_delivery={
            "failed_codes": ["machine_playback_e2e_not_verified"],
            "machine_playback_e2e_reason": "play_failed",
            "machine_playback_e2e_track_response_status": 500,
            "machine_playback_e2e_track_content_type": "text/html",
            "machine_playback_e2e_media_error_present": True,
            "machine_playback_e2e_media_error_code": 4,
            "public_share_host": "audiobookshelf.example.test",
        },
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="blocked",
        failed=0,
        attempted=0,
        results=[],
        privacy={"raw_public_share_url_exposed": False, "raw_track_url_exposed": False},
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        gold_status="pass",
        gold_claim_allowed=True,
        gold_remaining_external_proofs=[],
        gold_approval_accepted=True,
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-30T09:00:00Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    proof_requirements = {item["key"]: item for item in receipt["acceptance_proof_requirements"]}
    whatsapp = proof_requirements["whatsapp_audiobook_live_delivery"]
    assert whatsapp["action_context"]["kind"] == "public_share_playback_failure"
    assert whatsapp["action_context"]["user_action_required"] is False
    assert whatsapp["action_context"]["telegram_push_allowed"] is False
    assert whatsapp["action_context"]["failed_playback_count"] == 1
    assert whatsapp["action_context"]["attempted_playback_count"] == 1
    assert whatsapp["action_context"]["track_response_status"] == 500
    assert whatsapp["action_context"]["track_content_type"] == "text/html"
    assert whatsapp["action_context"]["raw_public_share_url_exposed"] is False
    assert whatsapp["action_context"]["raw_track_url_exposed"] is False
    queue_row = next(item for item in receipt["operator_action_queue"] if item["key"] == "whatsapp_audiobook_live_delivery")
    assert queue_row["user_action_required"] is False
    assert queue_row["delivery_policy"] == "queue_only"
    assert queue_row["telegram_push_allowed"] is False
    assert queue_row["track_response_status"] == 500
    assert queue_row["track_content_type"] == "text/html"
    assert queue_row["raw_public_share_url_exposed"] is False
    assert queue_row["raw_track_url_exposed"] is False
    assert "deliver:whatsapp_audiobook=blocked" in receipt["blocking_reasons"]
    assert verify(output, root=tmp_path) == []


def test_goal_posture_verifier_accepts_post_commit_head_change_when_source_fingerprint_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_source_state(monkeypatch, head="new-head", fingerprint="source-fingerprint")
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json",
        status="ready_local_packet_pending_operator_acceptance",
        next_action="review packet with operator",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_office_loop_goal.generated.json",
        status="ready_local_evidence",
        next_action="collect office-loop acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/active_media_ltd_goal_bundle.generated.json",
        status="ready_local_evidence",
        next_action="collect external media proofs",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json",
        status="blocked_real_world_acceptance",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        status="ready_local_audit",
    )
    _write_teable_recovery_proof_receipt(
        tmp_path,
        status="pass",
        source_git_head="old-head",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json",
        status="pass",
    )
    _write_receipt(
        tmp_path,
        ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
        status="pass",
    )
    _write_proactive_ooda_receipts(
        tmp_path,
        source_git_head="old-head",
        source_state_fingerprint="source-fingerprint",
    )

    output = tmp_path / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
    receipt = build_goal_posture(root=tmp_path, output_path=output, generated_at="2026-06-22T15:40:00Z")
    receipt["source_git_head"] = "old-head"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    assert verify(output, root=tmp_path) == []
