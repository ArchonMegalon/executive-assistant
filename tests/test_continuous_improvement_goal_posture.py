from __future__ import annotations

import json
from pathlib import Path

from scripts.materialize_continuous_improvement_goal_posture import build_goal_posture
import scripts.materialize_continuous_improvement_goal_posture as posture_module
import scripts.verify_continuous_improvement_goal_posture as verifier_module
from scripts.verify_continuous_improvement_goal_posture import verify


def _write_receipt(root: Path, relative_path: str, *, status: str, **extra: object) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "contract_name": f"test.{path.stem}"}
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


def _write_teable_recovery_proof_receipt(root: Path, *, status: str = "pass", source_git_head: str = "") -> None:
    extra = {"source_git_head": source_git_head} if source_git_head else {}
    _write_receipt(
        root,
        ".codex-studio/published/teable_env_recovery_proof.generated.json",
        status=status,
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
        **extra,
    )


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
        status="blocked",
        next_action="choose_explicit_replacement_voice_or_restore_selected_provider",
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
    assert any(
        "ea_proactive_ooda_gold_acceptance.generated.json" in surface
        for surface in proof_requirements["proactive_ooda_packet_acceptance"]["capture_surfaces"]
    )
    assert proof_requirements["fresh_host_teable_recovery_drill"]["lens"] == "recover"
    assert proof_requirements["fresh_host_teable_recovery_drill"]["evidence_kind"] == "fresh_host_recovery_drill"
    assert proof_requirements["telegram_audiobook_live_delivery"]["evidence_kind"] == "live_delivery_receipt"
    assert (
        proof_requirements["telegram_audiobook_live_delivery"]["next_action"]
        == "choose_explicit_replacement_voice_or_restore_selected_provider"
    )
    assert "Telegram is an action surface, not a progress log; proactive delivery must stay quiet unless the user needs to approve, choose, unblock, review, or answer something." in receipt["rules"]
    assert "Proactive OODA packets must pass a context/provider-fit auditor before user delivery; reachable URLs, extracted email addresses, or generic search hits are not sufficient." in receipt["rules"]
    assert "Pocket.ai or other consented audio transcripts may feed OODA only as approved signals with privacy, retention, source, and current/stale status preserved." in receipt["rules"]
    assert "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth." in receipt["rules"]

    lenses = {lens["key"]: lens for lens in receipt["lenses"]}
    assert lenses["detect"]["status"] == "ready_local_packet_pending_operator_acceptance"
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
