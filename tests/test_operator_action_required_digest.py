from __future__ import annotations

import json
from pathlib import Path

from scripts import materialize_operator_action_required_digest as digest
from scripts import verify_operator_action_required_digest as verify_digest


def _patch_source_state(monkeypatch) -> None:
    monkeypatch.setattr(digest, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(digest, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")
    monkeypatch.setattr(verify_digest, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(verify_digest, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")


def _action_row(**overrides):
    row = {
        "key": "pushbullet_delivery_setup",
        "operator_stream": "office_setup",
        "title": "Pushbullet delivery setup",
        "required_next_receipt": "Pushbullet delivery clients configured and live-verifiable for action-required delivery",
        "next_action": "create_missing_pushbullet_access_tokens",
        "next_action_label": "Open Pushbullet account settings",
        "next_action_form_href": "/admin/goals",
        "next_action_form_label": "Open goal evidence",
        "next_action_form_method": "get",
        "notification_policy": "default",
        "user_action_required": True,
        "instruction": "Create the missing Pushbullet token.",
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
                    token_missing_client_keys=["elisabeth"],
                    pushbullet_missing_token_envs=["PB_TOKEN_ELISABETH"],
                    pushbullet_token_envs=["PB_TOKEN_ELISABETH"],
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
                    key="proactive_ooda_packet_acceptance",
                    instruction="Record the approval outcome for the current proactive OODA packet.",
                    next_action="record_proactive_ooda_approval_outcome",
                    next_action_label="Record packet verdict",
                    user_action_required=True,
                    delivery_policy="action_required_only",
                    telegram_push_allowed=False,
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
    assert receipt["included_action_keys"] == ["pushbullet_delivery_setup"]
    assert receipt["notification_item_count"] == 1
    assert receipt["notification_action_keys"] == ["pushbullet_delivery_setup"]
    item = receipt["items"][0]
    assert item["operator_stream"] == "office_setup"
    assert item["action_required_reason"] == "real_world_acceptance_missing"
    assert item["source_action_packet_present"] is True
    assert item["source_action_packet_status"] == "action_required"
    assert item["required_form_fields"] == ["evidence_part", "source_kind", "evidence", "packet_ref"]
    assert item["external_setup_url"] == "https://www.pushbullet.com/#settings/account"
    assert item["token_missing_client_keys"] == ["elisabeth"]
    assert item["pushbullet_missing_token_envs"] == ["PB_TOKEN_ELISABETH"]
    assert item["pushbullet_token_envs"] == ["PB_TOKEN_ELISABETH"]
    assert "Create the missing Pushbullet token" in receipt["telegram_text"]
    assert "Setup: https://www.pushbullet.com/#settings/account" in receipt["telegram_text"]
    assert "Env: PB_TOKEN_ELISABETH" in receipt["telegram_text"]
    assert "Internal queue-only recovery" not in receipt["telegram_text"]
    assert "Record the approval outcome for the current proactive OODA packet" not in receipt["telegram_text"]
    assert receipt["counts"]["suppressed_queue_only_count"] == 1
    assert receipt["counts"]["suppressed_privacy_blocked_count"] == 1
    assert receipt["counts"]["suppressed_policy_blocked_count"] == 1
    assert receipt["privacy"]["raw_secret_exposed"] is False
    assert receipt["send_attempted"] is False
    assert output_path.exists()
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_telegram_text_avoids_duplicate_console_or_retry_details(tmp_path, monkeypatch) -> None:
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
                    key="google_workspace_oauth_setup",
                    instruction="Fallback instruction.",
                    telegram_message=(
                        "Action needed: Google auth still needs a manual Audience-page check. "
                        "Console: https://console.cloud.google.com/auth/audience?project=test"
                    ),
                    console_deep_link="https://console.cloud.google.com/auth/audience?project=test",
                    auth_link_template="https://myexternalbrain.com/app/actions/google/connect?scope_bundle=full_workspace",
                )
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

    text = receipt["telegram_text"]
    assert "1. Action needed: Google auth still needs a manual Audience-page check." in text
    assert text.count("https://console.cloud.google.com/auth/audience?project=test") == 1
    assert text.count("https://myexternalbrain.com/app/actions/google/connect?scope_bundle=full_workspace") == 1
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_telegram_text_uses_action_link_and_suppresses_redacted_retry(tmp_path, monkeypatch) -> None:
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
                    key="google_workspace_oauth_setup",
                    instruction="Retry Google auth with the approved work account.",
                    next_action_form_href="/integrations/google",
                    next_action_form_label="Retry Google auth",
                    auth_link_template=(
                        "https://myexternalbrain.com/app/actions/google/connect?"
                        "scope_bundle=full_workspace&expected_google_email=%3Credacted-email%3E"
                    ),
                )
            ],
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        queue_url="https://myexternalbrain.com/admin/goals",
        generated_at="2026-07-01T12:00:00Z",
    )

    text = receipt["telegram_text"]
    assert "Open: https://myexternalbrain.com/integrations/google" in text
    assert "Retry:" not in text
    assert "redacted-email" not in text
    assert "%3Credacted" not in text
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
    assert saved_state["last_item_hashes"]["pushbullet_delivery_setup"]
    assert saved_state["last_notification_item_keys"] == ["pushbullet_delivery_setup"]
    assert "principal-1" not in state_path.read_text(encoding="utf-8")
    assert verify_digest.verify_receipt(first) == []
    assert verify_digest.verify_receipt(second) == []


def test_digest_refreshes_default_posture_before_building(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / ".codex-studio" / "published" / "ea_continuous_improvement_goal_posture.generated.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(digest, "DEFAULT_INPUT", input_path)
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [
                _action_row(
                    key="google_workspace_oauth_setup",
                    instruction="Open Google Auth Platform and confirm the work account is allowed there, add it if missing, save, then retry the Full Workspace auth link.",
                    telegram_message=(
                        "Action needed: Google Full Workspace auth still needs a manual Audience-page check. "
                        "Open Google Auth Platform, confirm the requested work account is allowed there, add it if missing, save, then retry the auth link."
                    ),
                    console_deep_link="https://console.cloud.google.com/auth/audience?project=test",
                    auth_link_template="https://myexternalbrain.com/app/actions/google/connect?scope_bundle=full_workspace",
                )
            ],
        },
    )

    refreshed_posture = {
        "status": "active_with_blockers",
        "operator_action_queue": [
            _action_row(
                key="google_workspace_oauth_setup",
                instruction="Retry the Full Workspace auth link and explicitly choose the approved work Google account.",
                telegram_message=(
                    "Action needed: Google Full Workspace auth is still denied even though the work account is already approved. "
                    "Retry the auth link, explicitly choose the approved account, and if Google still blocks it re-open the Audience page to confirm the save."
                ),
                console_deep_link="https://console.cloud.google.com/auth/audience?project=test",
                auth_link_template="https://myexternalbrain.com/app/actions/google/connect?scope_bundle=full_workspace",
            )
        ],
    }

    def fake_refresher(*, root: Path, output_path: Path):
        assert root == tmp_path
        assert output_path == input_path
        _write_json(output_path, refreshed_posture)
        return refreshed_posture

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        refresh_source=True,
        posture_refresher=fake_refresher,
        generated_at="2026-07-01T12:06:00Z",
    )

    assert receipt["status"] == "ready_to_send"
    assert receipt["source_refresh"]["attempted"] is True
    assert receipt["source_refresh"]["status"] == "materialized"
    assert receipt["notification_action_keys"] == ["google_workspace_oauth_setup"]
    assert "already approved" in receipt["telegram_text"]
    assert "add it if missing" not in receipt["telegram_text"]
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_refresh_failure_falls_back_to_existing_posture_and_records_failure(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / ".codex-studio" / "published" / "ea_continuous_improvement_goal_posture.generated.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(digest, "DEFAULT_INPUT", input_path)
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [
                _action_row(
                    key="google_workspace_oauth_setup",
                    instruction="Open Google Auth Platform and confirm the work account is allowed there, add it if missing, save, then retry the Full Workspace auth link.",
                )
            ],
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        refresh_source=True,
        posture_refresher=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("refresh_failed")),
        generated_at="2026-07-01T12:07:00Z",
    )

    assert receipt["status"] == "ready_to_send"
    assert receipt["source_refresh"]["attempted"] is True
    assert receipt["source_refresh"]["status"] == "failed"
    assert "RuntimeError:refresh_failed" == receipt["source_refresh"]["error"]
    assert "add it if missing" in receipt["telegram_text"]
    assert verify_digest.verify_receipt(receipt) == []


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
        telegram_sender=lambda *_args: {"sent": True, "reason": "sent", "message_ids": ["1004"], "message_count": 1},
    )

    assert receipt["status"] == "sent"
    assert receipt["dedupe_suppressed"] is False
    assert receipt["notification_mode"] == "head_promoted"
    assert receipt["notification_item_count"] == 1
    assert receipt["notification_action_keys"] == ["whatsapp_audiobook_live_delivery"]
    assert "Pair WhatsApp Web." in receipt["telegram_text"]
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_does_not_notify_lower_priority_new_item_from_legacy_state(tmp_path, monkeypatch) -> None:
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

    assert receipt["status"] == "suppressed_duplicate"
    assert receipt["item_count"] == 2
    assert receipt["included_action_keys"] == [
        "weekly_signal_to_decision_review_acceptance",
        "google_workspace_oauth_setup",
    ]
    assert receipt["notification_mode"] == "covered_by_previous_send"
    assert receipt["notification_item_count"] == 0
    assert receipt["notification_action_keys"] == []
    assert receipt["telegram_text"] == ""
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "last_digest_sha256": "legacy-digest",
        "last_item_keys": ["weekly_signal_to_decision_review_acceptance"],
        "last_sent_at": "2026-07-01T12:00:00Z",
        "message_id_count": 1,
    }
    assert len(calls) == 0
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_notifies_new_tail_items_when_hash_backed_state_exists(tmp_path, monkeypatch) -> None:
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
    legacy_hash = digest._item_hash(digest._sanitize_action_item(old_item))
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
    assert receipt["notification_mode"] == "new_items_behind_existing_head"
    assert receipt["notification_item_count"] == 1
    assert receipt["notification_action_keys"] == ["pushbullet_delivery_setup"]
    assert "Create the missing Pushbullet token." in receipt["telegram_text"]
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(saved_state["last_item_hashes"]) == {
        "weekly_signal_to_decision_review_acceptance",
        "pushbullet_delivery_setup",
    }
    assert len(calls) == 1
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_notifies_tail_item_not_covered_by_previous_notification(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    google = _action_row(
        key="google_workspace_oauth_setup",
        instruction="Open Google Auth Platform and confirm the work account is allowed.",
        operator_stream="office_setup",
    )
    pushbullet = _action_row(
        key="pushbullet_delivery_setup",
        instruction="Create the missing Pushbullet token.",
        operator_stream="office_setup",
        external_setup_url="https://www.pushbullet.com/#settings/account",
    )
    posture = {"status": "active_with_blockers", "operator_action_queue": [google, pushbullet]}
    _write_json(input_path, posture)
    selected, _counts = digest._select_items(posture)
    _write_json(
        state_path,
        {
            "last_digest_sha256": digest._sha256_json(digest._digest_material(selected, digest.DEFAULT_QUEUE_URL)),
            "last_item_keys": ["google_workspace_oauth_setup", "pushbullet_delivery_setup"],
            "last_item_hashes": digest._item_hashes_by_key(selected),
            "last_notification_item_keys": ["google_workspace_oauth_setup"],
            "last_sent_at": "2026-07-01T12:00:00Z",
            "message_id_count": 1,
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:05:00Z",
    )

    assert receipt["status"] == "ready_to_send"
    assert receipt["dedupe_suppressed"] is False
    assert receipt["notification_mode"] == "new_items_behind_existing_head"
    assert receipt["notification_item_count"] == 1
    assert receipt["notification_action_keys"] == ["pushbullet_delivery_setup"]
    assert "Create the missing Pushbullet token." in receipt["telegram_text"]
    assert "Open Google Auth Platform" not in receipt["telegram_text"]
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_notifies_changed_head_and_new_tail_items_together(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    current_head = _action_row(
        key="proactive_ooda_packet_acceptance",
        instruction="Record the approval outcome before 2026-07-12T11:52:01Z.",
        notification_policy="exclusive_head",
    )
    previous_head = _action_row(
        key="proactive_ooda_packet_acceptance",
        instruction="Record the approval outcome before 2026-07-11T11:52:01Z.",
        notification_policy="exclusive_head",
    )
    old_tail = _action_row(
        key="weekly_signal_to_decision_review_acceptance",
        instruction="Already queued review request.",
        operator_stream="office_loop",
    )
    new_setup = _action_row(
        key="google_workspace_oauth_setup",
        instruction="Open Google Auth Platform and confirm the work account is allowed.",
        operator_stream="office_setup",
    )
    new_pushbullet = _action_row(
        key="pushbullet_delivery_setup",
        instruction="Create the missing Pushbullet token.",
        operator_stream="office_setup",
        external_setup_url="https://www.pushbullet.com/#settings/account",
        notification_policy="head_only",
    )
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [current_head, old_tail, new_setup, new_pushbullet],
        },
    )
    _write_json(
        state_path,
        {
            "last_digest_sha256": "digest-before-head-delta",
            "last_item_keys": [
                "proactive_ooda_packet_acceptance",
                "weekly_signal_to_decision_review_acceptance",
            ],
            "last_item_hashes": {
                "proactive_ooda_packet_acceptance": digest._item_hash(digest._sanitize_action_item(previous_head)),
                "weekly_signal_to_decision_review_acceptance": digest._item_hash(digest._sanitize_action_item(old_tail)),
            },
            "last_notification_item_keys": ["proactive_ooda_packet_acceptance"],
            "last_sent_at": "2026-07-01T12:00:00Z",
            "message_id_count": 1,
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:05:00Z",
    )

    assert receipt["status"] == "ready_to_send"
    assert receipt["notification_mode"] == "head_delta"
    assert receipt["notification_action_keys"] == ["proactive_ooda_packet_acceptance"]
    assert "Record the approval outcome before 2026-07-12T11:52:01Z." in receipt["telegram_text"]
    assert "Open Google Auth Platform and confirm the work account is allowed." not in receipt["telegram_text"]
    assert "Create the missing Pushbullet token." not in receipt["telegram_text"]
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_exclusive_head_suppresses_new_tail_items_until_head_is_resolved(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    current_head = _action_row(
        key="proactive_ooda_packet_acceptance",
        instruction="Record the approval outcome before 2026-07-12T11:52:01Z.",
        notification_policy="exclusive_head",
    )
    new_setup = _action_row(
        key="google_workspace_oauth_setup",
        instruction="Open Google Auth Platform and confirm the work account is allowed.",
        operator_stream="office_setup",
    )
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [current_head, new_setup],
        },
    )
    _write_json(
        state_path,
        {
            "last_digest_sha256": "digest-before-tail-change",
            "last_item_keys": ["proactive_ooda_packet_acceptance"],
            "last_item_hashes": {
                "proactive_ooda_packet_acceptance": digest._item_hash(digest._sanitize_action_item(current_head)),
            },
            "last_notification_item_keys": ["proactive_ooda_packet_acceptance"],
            "last_sent_at": "2026-07-01T12:00:00Z",
            "message_id_count": 1,
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:06:00Z",
    )

    assert receipt["status"] == "suppressed_duplicate"
    assert receipt["notification_mode"] == "covered_by_previous_send"
    assert receipt["notification_item_count"] == 0
    assert receipt["notification_action_keys"] == []
    assert receipt["dedupe_suppressed"] is True
    assert "Open Google Auth Platform and confirm the work account is allowed." not in receipt["telegram_text"]
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_head_only_notification_policy_suppresses_tail_but_not_head(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    current_head = _action_row(
        key="pushbullet_delivery_setup",
        instruction="Create the missing Pushbullet token.",
        notification_policy="head_only",
    )
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [current_head],
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:07:00Z",
    )

    assert receipt["status"] == "ready_to_send"
    assert receipt["notification_mode"] == "head_full"
    assert receipt["notification_action_keys"] == ["pushbullet_delivery_setup"]
    assert "Create the missing Pushbullet token." in receipt["telegram_text"]
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_default_stream_filter_suppresses_media_archive_items(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_delivery_policy": {
                "default_action_digest_streams": ["office_loop", "office_setup", "recovery"],
            },
            "operator_action_queue": [
                _action_row(
                    key="proactive_ooda_packet_acceptance",
                    operator_stream="office_loop",
                    instruction="Record the approval outcome.",
                ),
                _action_row(
                    key="telegram_audiobook_live_delivery",
                    operator_stream="media_archive",
                    instruction="Choose one Telegram audiobook voice sample.",
                    action_digest_eligible=False,
                    default_action_digest_suppressed_reason="operator_stream_not_in_default_action_digest",
                ),
            ],
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:04:00Z",
    )

    assert receipt["status"] == "ready_to_send"
    assert receipt["allowed_operator_streams"] == ["office_loop", "office_setup", "recovery"]
    assert receipt["item_count"] == 1
    assert receipt["included_action_keys"] == ["proactive_ooda_packet_acceptance"]
    assert receipt["counts"]["suppressed_out_of_scope_count"] == 1
    assert "Choose one Telegram audiobook voice sample." not in receipt["telegram_text"]
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_respects_explicit_action_digest_ineligible_flag(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_delivery_policy": {
                "default_action_digest_streams": ["office_loop", "office_setup", "recovery"],
            },
            "operator_action_queue": [
                _action_row(
                    key="google_workspace_oauth_setup",
                    operator_stream="office_setup",
                    instruction="Retry Google auth.",
                    action_digest_eligible=False,
                    default_action_digest_suppressed_reason="telegram_push_not_allowed",
                ),
            ],
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:04:00Z",
    )

    assert receipt["status"] == "no_user_action_required"
    assert receipt["item_count"] == 0
    assert receipt["counts"]["suppressed_out_of_scope_count"] == 1
    assert receipt["telegram_text"] == ""
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_cold_start_notifies_only_queue_head(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [
                _action_row(key="proactive_ooda_packet_acceptance", instruction="Record the approval outcome."),
                _action_row(key="pushbullet_delivery_setup", instruction="Create the missing Pushbullet token."),
            ],
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:06:00Z",
    )

    assert receipt["status"] == "ready_to_send"
    assert receipt["item_count"] == 2
    assert receipt["included_action_keys"] == [
        "proactive_ooda_packet_acceptance",
        "pushbullet_delivery_setup",
    ]
    assert receipt["notification_mode"] == "head_full"
    assert receipt["notification_item_count"] == 1
    assert receipt["notification_action_keys"] == ["proactive_ooda_packet_acceptance"]
    assert "Record the approval outcome." in receipt["telegram_text"]
    assert "Create the missing Pushbullet token." not in receipt["telegram_text"]
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_file_verifier_rejects_stale_source_posture_hash(tmp_path, monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    input_path = tmp_path / "posture.json"
    output_path = tmp_path / "digest.json"
    state_path = tmp_path / "state.json"
    _write_json(input_path, {"status": "active_with_blockers", "operator_action_queue": [_action_row()]})

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:05:00Z",
    )
    assert verify_digest.verify(output_path, root=tmp_path) == []

    _write_json(
        input_path,
        {
            "status": "active_with_blockers",
            "operator_action_queue": [
                _action_row(),
                _action_row(key="google_workspace_oauth_setup", instruction="Retry Google auth."),
            ],
        },
    )

    issues = verify_digest.verify(output_path, root=tmp_path)

    assert "source_receipt.sha256 stale" in issues
    assert verify_digest.verify_receipt(receipt) == []


def test_digest_excludes_observed_google_email_exposure(tmp_path, monkeypatch) -> None:
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
                    key="google_workspace_oauth_setup",
                    instruction="Retry Google auth.",
                    raw_observed_google_email_exposed=True,
                )
            ],
        },
    )

    receipt = digest.build_operator_action_required_digest(
        root=tmp_path,
        input_path=input_path,
        output_path=output_path,
        state_path=state_path,
        generated_at="2026-07-01T12:06:00Z",
    )

    assert receipt["status"] == "no_user_action_required"
    assert receipt["item_count"] == 0
    assert receipt["counts"]["suppressed_privacy_blocked_count"] == 1
    assert receipt["privacy"]["raw_observed_google_email_exposed"] is False
    assert verify_digest.verify(output_path, root=tmp_path) == []


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
