from __future__ import annotations

import json
from pathlib import Path

from scripts import materialize_operator_action_required_digest as digest
from scripts import verify_operator_action_required_digest as verify_digest


def _patch_source_state(monkeypatch) -> None:
    monkeypatch.setattr(digest, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(digest, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")


def _action_row(**overrides):
    row = {
        "key": "telegram_audiobook_live_delivery",
        "title": "Telegram audiobook live delivery",
        "required_next_receipt": "passing Telegram audiobook live delivery receipt",
        "next_action": "choose_sent_replacement_voice_sample",
        "next_action_label": "Choose voice sample",
        "next_action_form_href": "/admin/goals",
        "next_action_form_label": "Open goal evidence",
        "next_action_form_method": "get",
        "user_action_required": True,
        "instruction": "Choose one sent replacement voice sample in Telegram.",
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "interruption_budget": "action_required",
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_email_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
    }
    row.update(overrides)
    return row


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_digest_filters_only_action_required_telegram_items(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [
                _action_row(
                    action_required_reason="real_world_acceptance_missing",
                    source_action_packet_present=True,
                    source_action_packet_status="action_required",
                    required_form_fields=["evidence_part", "source_kind", "evidence", "packet_ref"],
                    external_setup_url="https://www.pushbullet.com/#settings/account",
                ),
                _action_row(
                    key="whatsapp_audiobook_live_delivery",
                    instruction="Internal queue-only recovery.",
                    user_action_required=False,
                    delivery_policy="queue_only",
                    telegram_push_allowed=False,
                    interruption_budget="none",
                ),
                _action_row(
                    key="unsafe_private_item",
                    instruction="This should be blocked.",
                    raw_secret_exposed=True,
                ),
            ],
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:00:00Z",
    )

    assert receipt["status"] == "ready_to_send"
    assert receipt["item_count"] == 1
    assert receipt["included_action_keys"] == ["telegram_audiobook_live_delivery"]
    assert receipt["notification_item_count"] == 1
    assert receipt["notification_action_keys"] == ["telegram_audiobook_live_delivery"]
    item = receipt["items"][0]
    assert item["action_required_reason"] == "real_world_acceptance_missing"
    assert item["source_action_packet_present"] is True
    assert item["source_action_packet_status"] == "action_required"
    assert item["required_form_fields"] == ["evidence_part", "source_kind", "evidence", "packet_ref"]
    assert item["external_setup_url"] == "https://www.pushbullet.com/#settings/account"
    assert "Choose one sent replacement voice sample" in receipt["telegram_text"]
    assert "Setup: https://www.pushbullet.com/#settings/account" in receipt["telegram_text"]
    assert "Internal queue-only recovery" not in receipt["telegram_text"]
    assert receipt["counts"]["suppressed_queue_only_count"] == 1
    assert receipt["counts"]["suppressed_privacy_blocked_count"] == 1
    assert receipt["privacy"]["raw_secret_exposed"] is False
    assert receipt["send_attempted"] is False
    assert output_path.exists()
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_send_updates_state_and_suppresses_duplicate(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    _write_json(input_path, {"status": "active_with_blockers", "operator_action_queue": [_action_row()]})
    calls = []

    def fake_sender(principal_id: str, text: str, dry_run: bool, timeout_seconds: float):
        calls.append((principal_id, text, dry_run, timeout_seconds))
        return {"sent": True, "reason": "sent", "message_ids": ["1001"], "message_count": 1}

    first = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        principal_id="principal-1",
        send=True,
        generated_at="2026-07-01T12:00:00Z",
        telegram_sender=fake_sender,
    )
    second = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        principal_id="principal-1",
        send=True,
        generated_at="2026-07-01T12:01:00Z",
        telegram_sender=fake_sender,
    )

    assert first["status"] == "sent"
    assert first["state_updated"] is True
    assert second["status"] == "suppressed_duplicate"
    assert second["dedupe_suppressed"] is True
    assert len(calls) == 1
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved_state["last_digest_sha256"] == first["digest_sha256"]
    assert saved_state["last_item_hashes"]["telegram_audiobook_live_delivery"]
    assert saved_state["last_notification_item_keys"] == ["telegram_audiobook_live_delivery"]
    assert "principal-1" not in state_path.read_text(encoding="utf-8")
    assert verify_digest.verify_receipt(first) == []
    assert verify_digest.verify_receipt(second) == []


def test_digest_does_not_resend_when_only_prior_action_was_removed(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    original_posture = {
        "status": "active_with_blockers",
        "operator_action_queue": [
            _action_row(key="google_workspace_oauth_setup", instruction="Add the work Google account."),
            _action_row(key="whatsapp_audiobook_live_delivery", instruction="Pair WhatsApp Web."),
        ],
    }
    _write_json(input_path, original_posture)
    items, _counts = digest._select_items(original_posture)
    _write_json(
        state_path,
        {
            "last_digest_sha256": digest._sha256_json(digest._digest_material(items, digest.DEFAULT_QUEUE_URL)),
            "last_item_keys": ["google_workspace_oauth_setup", "whatsapp_audiobook_live_delivery"],
            "last_item_hashes": digest._item_hashes_by_key(items),
            "last_sent_at": "2026-07-01T12:00:00Z",
            "message_id_count": 1,
        },
    )
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [
                _action_row(key="whatsapp_audiobook_live_delivery", instruction="Pair WhatsApp Web."),
            ],
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        send=True,
        generated_at="2026-07-01T12:03:00Z",
        telegram_sender=lambda *_args: {"sent": True, "reason": "should_not_send"},
    )

    assert receipt["status"] == "suppressed_duplicate"
    assert receipt["dedupe_suppressed"] is True
    assert receipt["notification_mode"] == "covered_by_previous_send"
    assert receipt["notification_item_count"] == 0
    assert receipt["notification_action_keys"] == []
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_sends_only_new_action_item_from_legacy_state(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [
                _action_row(key="weekly_signal_to_decision_review_acceptance", instruction="Already sent item."),
                _action_row(key="google_workspace_oauth_setup", instruction="Add the work Google account as an OAuth test user."),
            ],
        },
    )
    _write_json(
        state_path,
        {
            "last_digest_sha256": "legacy-digest",
            "last_item_keys": ["weekly_signal_to_decision_review_acceptance"],
            "last_sent_at": "2026-07-01T12:00:00Z",
            "message_id_count": 1,
        },
    )
    calls = []

    def fake_sender(principal_id: str, text: str, dry_run: bool, timeout_seconds: float):
        calls.append((principal_id, text, dry_run, timeout_seconds))
        return {"sent": True, "reason": "sent", "message_ids": ["1002"], "message_count": 1}

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        principal_id="principal-1",
        send=True,
        generated_at="2026-07-01T12:02:00Z",
        telegram_sender=fake_sender,
    )

    assert receipt["status"] == "sent"
    assert receipt["item_count"] == 2
    assert receipt["included_action_keys"] == [
        "weekly_signal_to_decision_review_acceptance",
        "google_workspace_oauth_setup",
    ]
    assert receipt["notification_mode"] == "delta_legacy_key_state"
    assert receipt["notification_item_count"] == 1
    assert receipt["notification_action_keys"] == ["google_workspace_oauth_setup"]
    assert "Add the work Google account" in receipt["telegram_text"]
    assert "Already sent item" not in receipt["telegram_text"]
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved_state["last_digest_sha256"] == receipt["digest_sha256"]
    assert saved_state["last_item_keys"] == [
        "weekly_signal_to_decision_review_acceptance",
        "google_workspace_oauth_setup",
    ]
    assert saved_state["last_notification_item_keys"] == ["google_workspace_oauth_setup"]
    assert set(saved_state["last_item_hashes"]) == set(saved_state["last_item_keys"])
    assert len(calls) == 1
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_external_setup_url_hash_preserves_legacy_items(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    old_item = _action_row(key="weekly_signal_to_decision_review_acceptance", instruction="Already sent item.")
    new_item = _action_row(
        key="pushbullet_delivery_setup",
        instruction="Create the missing Pushbullet token.",
        next_action="create_missing_pushbullet_access_tokens",
        external_setup_url="https://www.pushbullet.com/#settings/account",
    )
    _write_json(input_path, {"status": "active_with_blockers", "operator_action_queue": [old_item, new_item]})
    legacy_hash = digest._sha256_json(
        {
            "key": "weekly_signal_to_decision_review_acceptance",
            "instruction": "Already sent item.",
            "next_action": "choose_sent_replacement_voice_sample",
            "next_action_form_href": "/admin/goals",
        }
    )
    _write_json(
        state_path,
        {
            "last_digest_sha256": "legacy-digest-before-external-setup-url",
            "last_item_keys": ["weekly_signal_to_decision_review_acceptance"],
            "last_item_hashes": {"weekly_signal_to_decision_review_acceptance": legacy_hash},
            "last_sent_at": "2026-07-01T12:00:00Z",
            "message_id_count": 1,
        },
    )
    calls = []

    def fake_sender(principal_id: str, text: str, dry_run: bool, timeout_seconds: float):
        calls.append((principal_id, text, dry_run, timeout_seconds))
        return {"sent": True, "reason": "sent", "message_ids": ["1003"], "message_count": 1}

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        principal_id="principal-1",
        send=True,
        generated_at="2026-07-01T12:04:00Z",
        telegram_sender=fake_sender,
    )

    assert receipt["status"] == "sent"
    assert receipt["notification_mode"] == "delta"
    assert receipt["notification_action_keys"] == ["pushbullet_delivery_setup"]
    assert "Create the missing Pushbullet token" in receipt["telegram_text"]
    assert "Setup: https://www.pushbullet.com/#settings/account" in receipt["telegram_text"]
    assert "Already sent item" not in receipt["telegram_text"]
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(saved_state["last_item_hashes"]) == {
        "weekly_signal_to_decision_review_acceptance",
        "pushbullet_delivery_setup",
    }
    assert len(calls) == 1
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_dry_run_checks_sender_without_persisting_state(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    _write_json(input_path, {"status": "active_with_blockers", "operator_action_queue": [_action_row()]})

    def fake_sender(_principal_id: str, _text: str, dry_run: bool, _timeout_seconds: float):
        assert dry_run is True
        return {"sent": False, "reason": "dry_run", "ready": True, "message_count": 0}

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        send=True,
        dry_run=True,
        generated_at="2026-07-01T12:00:00Z",
        telegram_sender=fake_sender,
    )

    assert receipt["status"] == "ready_to_send"
    assert receipt["notification_status"] == "dry_run_ready"
    assert receipt["send_attempted"] is True
    assert receipt["state_updated"] is False
    assert not state_path.exists()
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_verifier_requires_dry_run_ready_to_prove_zero_send() -> None:
    receipt = {
        "contract_name": "ea.operator_action_required_digest.v1",
        "status": "ready_to_send",
        "notification_status": "dry_run_ready",
        "delivery_policy": "action_required_only",
        "non_action_progress_push_allowed": False,
        "quiet_hours_respected": True,
        "irreversible_actions_consent_gated": True,
        "item_count": 1,
        "included_action_keys": ["needs_action"],
        "notification_item_count": 1,
        "notification_action_keys": ["needs_action"],
        "items": [
            {
                "key": "needs_action",
                "instruction": "Choose one item.",
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": True,
                "interruption_budget": "action_required",
                "quiet_hours_respected": True,
                "non_action_progress_push_allowed": False,
                "irreversible_actions_consent_gated": True,
            }
        ],
        "notification_items": [
            {
                "key": "needs_action",
                "instruction": "Choose one item.",
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": True,
                "interruption_budget": "action_required",
                "quiet_hours_respected": True,
                "non_action_progress_push_allowed": False,
                "irreversible_actions_consent_gated": True,
            }
        ],
        "counts": {"included_count": 1},
        "privacy": {flag: False for flag in verify_digest.PRIVATE_EXPOSURE_FLAGS},
        "notification_digest_sha256": "notification-hash",
        "send_requested": True,
        "send_attempted": True,
        "dry_run": True,
        "state_updated": False,
        "send_result": {
            "ready": False,
            "sent": True,
            "message_count": 1,
        },
        "telegram_text": "Action needed for EA:\n1. Choose one item.",
        "source_receipt": {"path": "source.json"},
    }

    issues = verify_digest.verify_receipt(receipt)

    assert "dry_run_ready requires send_result.ready=true" in issues
    assert "dry_run_ready requires send_result.sent=false" in issues
    assert "dry_run_ready requires send_result.message_count=0" in issues


def test_digest_verifier_requires_sent_receipt_to_prove_message_and_dedupe_state() -> None:
    receipt = {
        "contract_name": "ea.operator_action_required_digest.v1",
        "status": "sent",
        "notification_status": "ready_to_send",
        "delivery_policy": "action_required_only",
        "non_action_progress_push_allowed": False,
        "quiet_hours_respected": True,
        "irreversible_actions_consent_gated": True,
        "item_count": 1,
        "included_action_keys": ["needs_action"],
        "notification_item_count": 1,
        "notification_action_keys": ["needs_action"],
        "items": [
            {
                "key": "needs_action",
                "instruction": "Choose one item.",
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": True,
                "interruption_budget": "action_required",
                "quiet_hours_respected": True,
                "non_action_progress_push_allowed": False,
                "irreversible_actions_consent_gated": True,
            }
        ],
        "notification_items": [
            {
                "key": "needs_action",
                "instruction": "Choose one item.",
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": True,
                "interruption_budget": "action_required",
                "quiet_hours_respected": True,
                "non_action_progress_push_allowed": False,
                "irreversible_actions_consent_gated": True,
            }
        ],
        "counts": {"included_count": 1},
        "privacy": {flag: False for flag in verify_digest.PRIVATE_EXPOSURE_FLAGS},
        "notification_digest_sha256": "notification-hash",
        "send_requested": True,
        "send_attempted": False,
        "dry_run": True,
        "state_updated": False,
        "send_result": {
            "sent": True,
            "message_count": 0,
        },
        "telegram_text": "Action needed for EA:\n1. Choose one item.",
        "source_receipt": {"path": "source.json"},
    }

    issues = verify_digest.verify_receipt(receipt)

    assert "sent status requires notification_status=sent" in issues
    assert "sent status requires send_attempted=true" in issues
    assert "sent status requires dry_run=false" in issues
    assert "sent status requires state_updated=true" in issues
    assert "sent status requires send_result.message_count>0" in issues


def test_digest_verifier_blocks_private_exposure() -> None:
    receipt = {
        "contract_name": "ea.operator_action_required_digest.v1",
        "status": "ready_to_send",
        "delivery_policy": "action_required_only",
        "non_action_progress_push_allowed": False,
        "quiet_hours_respected": True,
        "irreversible_actions_consent_gated": True,
        "item_count": 1,
        "included_action_keys": ["leaky"],
        "notification_item_count": 1,
        "notification_action_keys": ["leaky"],
        "items": [
            {
                "key": "leaky",
                "instruction": "Act on this.",
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": True,
                "interruption_budget": "action_required",
                "quiet_hours_respected": True,
                "non_action_progress_push_allowed": False,
                "irreversible_actions_consent_gated": True,
                "raw_secret_exposed": True,
            }
        ],
        "notification_items": [
            {
                "key": "leaky",
                "instruction": "Act on this.",
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": True,
                "interruption_budget": "action_required",
                "quiet_hours_respected": True,
                "non_action_progress_push_allowed": False,
                "irreversible_actions_consent_gated": True,
                "raw_secret_exposed": True,
            }
        ],
        "counts": {"included_count": 1},
        "privacy": {
            "raw_private_context_exposed": False,
            "raw_chat_ids_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": True,
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
            "raw_public_share_url_exposed": False,
            "raw_track_url_exposed": False,
            "raw_acceptance_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_object_reference_exposed": False,
            "raw_transcript_fields_exposed": False,
            "candidate_raw_text_fields_exposed": False,
        },
        "notification_digest_sha256": "notification-hash",
        "send_attempted": False,
        "send_requested": False,
        "telegram_text": "Action needed for EA:\n1. Act on this.",
        "source_receipt": {"path": "source.json"},
    }

    issues = verify_digest.verify_receipt(receipt)

    assert "privacy.raw_secret_exposed must be false" in issues
    assert "item must not expose raw_secret_exposed: leaky" in issues
