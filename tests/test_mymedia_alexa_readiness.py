from __future__ import annotations

import json

from scripts import materialize_mymedia_alexa_readiness as materializer
from scripts import verify_mymedia_alexa_readiness as verifier


def _patch_source_state(monkeypatch) -> None:
    monkeypatch.setattr(materializer, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(materializer, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")
    monkeypatch.setattr(verifier, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(verifier, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")


def test_materialize_mymedia_readiness_carries_pairing_resume_handoff(monkeypatch, tmp_path) -> None:
    _patch_source_state(monkeypatch)
    monkeypatch.setattr(
        materializer.ea_live_ops,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "pairing_session_surface_kind": "waiting_for_code",
            "pairing_ready": False,
            "container_running": True,
            "api_reachable": True,
            "watch_folder_count": 1,
            "tracks": 0,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": True,
            "public_surface_configured": True,
            "public_surface_scope": "public",
            "public_surface_probe_attempted": True,
            "public_surface_ready": False,
            "public_surface_status": "blocked_by_cloudflare",
            "public_surface_reason": "mymedia_public_console_blocked_by_cloudflare",
            "public_surface_http_status_code": 403,
            "public_surface_access_protected": False,
            "public_surface_cloudflare_blocked": True,
            "public_surface_redirect_host": "",
            "public_surface_content_type": "text/html; charset=UTF-8",
            "public_surface_next_action": "repair_mymedia_public_console_route",
            "public_surface_next_action_href": "https://mymedia.girschele.com",
            "public_surface_next_action_label": "Open public My Media URL",
            "public_surface_next_action_method": "get",
            "public_surface_source": "http.public_surface_probe",
            "observed_at": "2026-07-04T13:00:00Z",
            "source": "docker.inspect+mymedia.api+xml_mount",
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
                "raw_pairing_resume_url_exposed": False,
                "raw_public_surface_redirect_exposed": False,
                "raw_public_surface_response_body_exposed": False,
            },
        },
    )
    monkeypatch.setattr(
        materializer.ea_live_ops,
        "send_mymedia_amazon_pairing_telegram",
        lambda **_kwargs: {
            "status": "waiting_for_code",
            "reason": "mfa_code_requested",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "surface_kind": "waiting_for_code",
            "site": "na.account.amazon.com",
            "otp_channel": "whatsapp",
            "phone_suffix": "419",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "source": "mymedia_setup.saved_session",
            "observed_at": "2026-07-04T13:00:05Z",
            "telegram_delivery": {
                "sent": False,
                "reason": "dry_run",
                "ready": True,
                "principal_id": "cf-email:tibor.girschele@gmail.com",
                "binding_id": "binding-1",
                "chat_ref_present": True,
                "chat_ref_sha256": "chatsha",
                "delivery_transport": "telegram_bot",
                "runtime_container": "ea-api",
                "bot_handle": "ea_concierge_bot",
                "message_count": 0,
                "message_ids": [],
                "next_action_href": "http://127.0.0.1:52051/index.html#!/setup",
                "source": "scripts.ea_live_ops.send_mymedia_amazon_pairing_telegram",
            },
        },
    )

    receipt = materializer.build_receipt(output_path=tmp_path / "mymedia_alexa_readiness.generated.json")

    assert receipt["status"] == "blocked_pairing_required"
    assert receipt["pairing_resume_ready"] is True
    assert receipt["pairing_resume_command"] == "make submit-mymedia-amazon-pairing-code OTP_CODE=123456"
    assert receipt["public_console_surface"]["configured"] is True
    assert receipt["public_console_surface"]["status"] == "blocked_by_cloudflare"
    assert receipt["public_console_surface"]["reason"] == "mymedia_public_console_blocked_by_cloudflare"
    assert receipt["operator_action"]["user_action_required"] is True
    assert receipt["operator_action"]["delivery_policy"] == "action_required_only"
    assert receipt["operator_action"]["telegram_delivery_ready"] is True
    assert receipt["pairing_telegram_delivery"]["dry_run"] is True
    assert receipt["pairing_telegram_delivery"]["uses_saved_session"] is True
    assert receipt["pairing_telegram_delivery"]["telegram_delivery"]["reason"] == "dry_run"
    assert receipt["pairing_telegram_delivery"]["telegram_delivery"]["principal_id_present"] is True
    assert receipt["pairing_telegram_delivery"]["telegram_delivery"]["binding_id_present"] is True
    assert "principal_id" not in receipt["pairing_telegram_delivery"]["telegram_delivery"]
    assert "binding_id" not in receipt["pairing_telegram_delivery"]["telegram_delivery"]
    assert "message_ids" not in receipt["pairing_telegram_delivery"]["telegram_delivery"]
    assert receipt["pairing_telegram_delivery"]["telegram_delivery"]["next_action_href"].startswith("host-local:///index.html")
    assert verifier.verify_receipt_for_test(receipt) == []


def test_materialize_mymedia_readiness_background_scan_receipt_is_queue_only(monkeypatch, tmp_path) -> None:
    _patch_source_state(monkeypatch)
    monkeypatch.setattr(
        materializer.ea_live_ops,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready_library_scan_in_progress",
            "reason": "mymedia_library_scan_in_progress",
            "next_action": "wait_for_mymedia_library_scan",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/tables",
            "next_action_label": "Open Watch Folders",
            "next_action_method": "get",
            "pairing_resume_ready": False,
            "pairing_ready": True,
            "container_running": True,
            "api_reachable": True,
            "watch_folder_count": 1,
            "tracks": 42,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": False,
            "observed_at": "2026-07-04T13:02:00Z",
            "source": "docker.inspect+mymedia.api+xml_mount",
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
                "raw_pairing_resume_url_exposed": False,
            },
        },
    )
    monkeypatch.setattr(
        materializer.ea_live_ops,
        "send_mymedia_amazon_pairing_telegram",
        lambda **_kwargs: {
            "status": "already_paired",
            "reason": "no_operator_action_required",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "surface_kind": "local_console",
            "site": "127.0.0.1",
            "otp_channel": "whatsapp",
            "phone_suffix": "419",
            "pairing_resume_ready": False,
            "pairing_session_pending": False,
            "source": "mymedia_pairing.telegram",
            "observed_at": "2026-07-04T13:02:05Z",
            "telegram_delivery": {
                "sent": False,
                "reason": "no_operator_action_required",
                "ready": False,
                "delivery_transport": "telegram_bot",
                "message_count": 0,
                "message_ids": [],
            },
        },
    )

    receipt = materializer.build_receipt(output_path=tmp_path / "mymedia_alexa_readiness.generated.json")

    assert receipt["ready"] is True
    assert receipt["status"] == "ready_library_scan_in_progress"
    assert receipt["next_action"] == "wait_for_mymedia_library_scan"
    assert receipt["next_action_href"].startswith("host-local:///index.html")
    assert receipt["operator_action"]["delivery_policy"] == "queue_only"
    assert receipt["pairing_resume_command"] == ""
    assert receipt["pairing_telegram_delivery"]["live_message_claim_allowed"] is False
    assert verifier.verify_receipt_for_test(receipt) == []


def test_materialize_mymedia_readiness_stale_pairing_session_keeps_probe_pending_truth(monkeypatch, tmp_path) -> None:
    _patch_source_state(monkeypatch)
    monkeypatch.setattr(
        materializer.ea_live_ops,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "complete_amazon_pairing_then_rescan_library",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/setup",
            "next_action_label": "Open My Media setup",
            "next_action_method": "get",
            "pairing_resume_ready": False,
            "pairing_session_pending": True,
            "pairing_session_stale": True,
            "pairing_ready": False,
            "container_running": True,
            "api_reachable": True,
            "watch_folder_count": 1,
            "tracks": 0,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": True,
            "observed_at": "2026-07-04T15:12:00Z",
            "source": "docker.inspect+mymedia.api+xml_mount",
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
                "raw_pairing_resume_url_exposed": False,
            },
        },
    )
    monkeypatch.setattr(
        materializer.ea_live_ops,
        "send_mymedia_amazon_pairing_telegram",
        lambda **_kwargs: {
            "status": "dry_run",
            "reason": "",
            "next_action": "request_mymedia_pairing_code",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "surface_kind": "dry_run",
            "site": "127.0.0.1",
            "otp_channel": "whatsapp",
            "phone_suffix": "419",
            "pairing_resume_ready": False,
            "pairing_session_pending": False,
            "source": "mymedia_setup.playwright",
            "observed_at": "2026-07-04T15:12:05Z",
            "telegram_delivery": {},
        },
    )

    receipt = materializer.build_receipt(output_path=tmp_path / "mymedia_alexa_readiness.generated.json")

    assert receipt["pairing_resume_ready"] is False
    assert receipt["pairing_resume_command"] == ""
    assert receipt["pairing_telegram_delivery"]["pairing_session_pending"] is True
    assert receipt["pairing_telegram_delivery"]["delivery_reason"] == "request_mymedia_pairing_code"
    assert receipt["next_action_href"].startswith("host-local:///index.html")
    assert receipt["operator_action"]["telegram_delivery_ready"] is False
    assert verifier.verify_receipt_for_test(receipt) == []


def test_verify_mymedia_readiness_rejects_secret_and_resume_overclaim(monkeypatch, tmp_path) -> None:
    _patch_source_state(monkeypatch)
    monkeypatch.setattr(
        materializer.ea_live_ops,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "complete_amazon_pairing_then_rescan_library",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/setup",
            "next_action_label": "Open My Media setup",
            "next_action_method": "get",
            "pairing_resume_ready": False,
            "pairing_ready": False,
            "container_running": True,
            "api_reachable": True,
            "watch_folder_count": 1,
            "tracks": 0,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": True,
            "observed_at": "2026-07-04T13:04:00Z",
            "source": "docker.inspect+mymedia.api+xml_mount",
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
                "raw_pairing_resume_url_exposed": False,
            },
        },
    )
    monkeypatch.setattr(
        materializer.ea_live_ops,
        "send_mymedia_amazon_pairing_telegram",
        lambda **_kwargs: {
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "complete_amazon_pairing_then_rescan_library",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/setup",
            "next_action_label": "Open My Media setup",
            "next_action_method": "get",
            "surface_kind": "",
            "site": "127.0.0.1",
            "otp_channel": "whatsapp",
            "phone_suffix": "419",
            "pairing_resume_ready": False,
            "pairing_session_pending": False,
            "source": "mymedia_pairing.telegram",
            "observed_at": "2026-07-04T13:04:05Z",
            "telegram_delivery": {
                "sent": False,
                "reason": "no_actionable_pairing_state",
                "ready": False,
                "delivery_transport": "telegram_bot",
                "message_count": 0,
                "message_ids": [],
            },
        },
    )

    receipt_path = tmp_path / "mymedia_alexa_readiness.generated.json"
    receipt = materializer.build_receipt(output_path=receipt_path)
    receipt["privacy"]["raw_refresh_token_exposed"] = True
    receipt["probe"]["privacy"]["raw_pairing_resume_url_exposed"] = True
    receipt["pairing_resume_ready"] = True
    receipt["pairing_resume_command"] = ""
    receipt["operator_action"]["pairing_resume_ready"] = False
    receipt["operator_action"]["telegram_delivery_ready"] = False
    receipt["operator_action"]["raw_private_context_exposed"] = True
    receipt["pairing_telegram_delivery"]["privacy"]["raw_message_text_exposed"] = True
    receipt["pairing_telegram_delivery"]["pairing_resume_ready"] = False
    receipt["pairing_telegram_delivery"]["next_action"] = "complete_amazon_pairing_then_rescan_library"
    receipt["pairing_telegram_delivery"]["telegram_delivery"]["ready"] = True
    receipt["pairing_telegram_delivery"]["telegram_delivery"]["reason"] = "sent"
    receipt["pairing_telegram_delivery"]["telegram_delivery"]["principal_id"] = "cf-email:tibor.girschele@gmail.com"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    issues = verifier.verify(receipt_path, root=tmp_path)

    assert "privacy.raw_refresh_token_exposed must be false" in issues
    assert "probe.privacy.raw_pairing_resume_url_exposed must be false" in issues
    assert "operator_action.pairing_resume_ready must match receipt" in issues
    assert "operator_action.telegram_delivery_ready must match pairing_telegram_delivery.telegram_delivery.ready" in issues
    assert "pairing_resume_command required when pairing_resume_ready" in issues
    assert "pairing_resume_ready requires a pairing resume next_action" in issues
    assert "operator_action.raw_private_context_exposed must be false" in issues
    assert "pairing_telegram_delivery.privacy.raw_message_text_exposed must be false" in issues
    assert "pairing_telegram_delivery.pairing_resume_ready must match receipt" in issues
    assert "pairing_telegram_delivery.telegram_delivery must not expose principal_id" in issues
