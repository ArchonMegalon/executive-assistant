from __future__ import annotations

import json
from pathlib import Path

from scripts import materialize_operator_action_required_dedupe_proof as proof
from scripts import materialize_operator_action_required_digest as digest
from scripts import verify_operator_action_required_dedupe_proof as verify_proof


def _patch_source_state(monkeypatch) -> None:
    monkeypatch.setattr(digest, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(digest, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")


def _action_row() -> dict:
    return {
        "key": "weekly_signal_to_decision_review_acceptance",
        "title": "Weekly signal-to-decision review acceptance",
        "required_next_receipt": "real weekly signal-to-decision review acceptance receipt",
        "next_action": "record_weekly_signal_to_decision_review_acceptance",
        "next_action_label": "Record signal review evidence",
        "next_action_form_href": "/admin/goals",
        "next_action_form_label": "Open goal evidence",
        "next_action_form_method": "get",
        "user_action_required": True,
        "instruction": "Record redacted evidence that the weekly signal-to-decision review was actually reviewed.",
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "interruption_budget": "action_required",
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_voice_ids_exposed": False,
        "raw_pair_url_exposed": False,
        "raw_qr_payload_exposed": False,
        "raw_whatsapp_session_ref_exposed": False,
        "callback_tokens_exposed": False,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_inputs(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    posture_path = tmp_path / "posture.json"
    state_path = tmp_path / "state.json"
    sent_path = tmp_path / "sent.json"
    posture = {"overall_status": "active_with_blockers", "operator_action_queue": [_action_row()]}
    _write_json(posture_path, posture)
    items, _counts = digest._select_items(posture)
    digest_sha256 = digest._sha256_json(digest._digest_material(items, digest.DEFAULT_QUEUE_URL))
    _write_json(
        state_path,
        {
            "last_digest_sha256": digest_sha256,
            "last_item_keys": ["weekly_signal_to_decision_review_acceptance"],
            "last_sent_at": "2026-07-01T12:11:06Z",
            "message_id_count": 1,
        },
    )
    _write_json(
        sent_path,
        {
            "status": "sent",
            "notification_status": "sent",
            "digest_sha256": digest_sha256,
            "send_result": {"message_count": 1},
        },
    )
    return posture_path, state_path, sent_path, digest_sha256


def test_dedupe_proof_materializes_sanitized_pass_receipt(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    posture_path, state_path, sent_path, digest_sha256 = _seed_inputs(tmp_path)
    output_path = tmp_path / "proof.json"

    receipt = proof.build_operator_action_required_dedupe_proof(
        root=tmp_path,
        input_path=posture_path,
        state_path=state_path,
        sent_receipt_path=sent_path,
        output_path=output_path,
        generated_at="2026-07-01T12:20:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["current_digest_sha256"] == digest_sha256
    assert receipt["send_attempted"] is False
    assert receipt["would_send_without_force"] is False
    assert receipt["suppressed_duplicate_expected"] is True
    assert receipt["state"]["last_digest_match"] is True
    assert receipt["state"]["raw_chat_ref_stored"] is False
    assert receipt["privacy"]["raw_pair_url_exposed"] is False
    assert receipt["privacy"]["raw_qr_payload_exposed"] is False
    assert receipt["privacy"]["raw_whatsapp_session_ref_exposed"] is False
    assert receipt["source_receipts"]["sent_digest"]["digest_match"] is True
    assert output_path.exists()
    assert verify_proof.verify_receipt(receipt) == []


def test_dedupe_proof_blocks_when_state_does_not_match_current_digest(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    posture_path, state_path, sent_path, _digest_sha256 = _seed_inputs(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["last_digest_sha256"] = "wrong"
    _write_json(state_path, state)

    receipt = proof.build_operator_action_required_dedupe_proof(
        root=tmp_path,
        input_path=posture_path,
        state_path=state_path,
        sent_receipt_path=sent_path,
        output_path=tmp_path / "proof.json",
        generated_at="2026-07-01T12:20:00Z",
    )

    assert receipt["status"] == "blocked"
    issues = verify_proof.verify_receipt(receipt)
    assert "status must be pass" in issues
    assert "would_send_without_force must be false" in issues
    assert "suppressed_duplicate_expected must be true" in issues
    assert "state.last_digest_match must be true" in issues
