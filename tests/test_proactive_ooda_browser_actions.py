from __future__ import annotations

import json

from app.services.proactive_ooda_browser_actions import (
    BROWSER_ACTION_RECEIPT_SCHEMA,
    build_browser_action_receipt,
)
from app.services.proactive_ooda_safe_work import build_safe_work_result
from app.services.proactive_ooda_service import ProactiveOodaService
from app.services.proactive_ooda_stage_packets import build_stage_packets

import scripts.run_proactive_ooda as runner


def _browser_cart_packet() -> dict[str, object]:
    digest = ProactiveOodaService().build_digest(
        principal_id="cf-email:user@example.test",
        signals=[
            {
                "source_ref": "opportunity:pagro-cart",
                "signal_type": "telegram_message",
                "channel": "telegram",
                "title": "Put school supplies into the basket",
                "summary": "Use the provided shop account and prepare a reversible cart.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "A shop cart can be prepared."},
                        "orient": {"summary": "This is reversible until checkout."},
                        "decide": {"summary": "Approve whether EA should resume after handoff.", "approval_required": True},
                        "act": {
                            "summary": "Log in and prepare the cart, stopping before checkout.",
                            "stage": {
                                "kind": "cart_draft",
                                "summary": "Prepare a reversible school-supply cart.",
                                "work_type": "prepare_cart_or_link",
                                "cart_url": "https://www.pagro.at/cart",
                                "browser_task": {
                                    "site_url": "https://www.pagro.at/",
                                    "login_url": "https://www.pagro.at/customer/account/login/",
                                    "credential_ref": "vault://ea/shop/pagro",
                                    "login_email": "the.girscheles@example.test",
                                    "login_password": "never-store-this",
                                    "expected_account_email": "the.girscheles@example.test",
                                    "operations": ["authenticate", "search_site", "fill_cart"],
                                    "execution": {
                                        "blocker_code": "cloudflare_not_cleared",
                                        "attempted_operations": ["authenticate"],
                                        "page_text": "Nur einen Moment... Sicherheitsueberpruefung via Cloudflare",
                                    },
                                },
                            },
                            "external_action_policy": "Do not purchase, pay, book, send, post, cancel, or commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    return build_stage_packets(digest)[0]


def test_browser_action_receipt_redacts_credentials_and_requires_handoff() -> None:
    packet = _browser_cart_packet()

    receipt = build_browser_action_receipt(packet, generated_at="2026-06-29T08:00:00+00:00")
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt["schema"] == BROWSER_ACTION_RECEIPT_SCHEMA
    assert receipt["status"] == "blocked_human_handoff_required"
    assert receipt["user_action_required"] is True
    assert receipt["handoff"]["blocker_code"] == "cloudflare_not_cleared"
    assert receipt["handoff"]["next_action"] == "complete_browser_handoff_then_resume_ooda_task"
    assert receipt["policy"]["irreversible_actions_attempted"] == []
    assert receipt["security"]["credential_ref_present"] is True
    assert receipt["security"]["username_present"] is True
    assert receipt["security"]["password_input_present"] is True
    assert receipt["security"]["secret_values_stored"] is False
    assert receipt["privacy"]["raw_credentials_stored"] is False
    assert "never-store-this" not in serialized
    assert "the.girscheles@example.test" not in serialized
    assert "vault://ea/shop/pagro" not in serialized


def test_safe_work_result_turns_browser_challenge_into_user_handoff() -> None:
    packet = _browser_cart_packet()

    result = build_safe_work_result(packet, generated_at="2026-06-29T08:00:00+00:00")

    assert result["status"] == "blocked_human_handoff_required"
    assert result["browser_action_receipt"]["status"] == "blocked_human_handoff_required"
    assert result["execution_receipt"]["browser_action_user_action_required"] is True
    assert result["execution_receipt"]["browser_action_status"] == "blocked_human_handoff_required"
    assert "No purchase, booking, send, post, cancel, payment, or commitment" in result["approval_prompt"]


def test_runner_treats_browser_handoff_as_action_required(tmp_path) -> None:
    packet = _browser_cart_packet()
    result = build_safe_work_result(packet, generated_at="2026-06-29T08:00:00+00:00")
    stage_path = tmp_path / "stage.json"
    safe_path = tmp_path / "safe.json"
    stage_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    safe_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    approval_request = runner._notification_approval_request(
        stage_packet_paths=(stage_path,),
        safe_work_result_paths=(safe_path,),
    )

    assert approval_request is not None
    assert approval_request["packet_ref"] == packet["packet_ref"]
    assert approval_request["staged_artifact_ref"] == result["result_ref"]
    assert runner._notification_requires_user_action(approval_request) is True


def test_runner_allows_browser_handoff_delivery_when_user_action_required() -> None:
    assert runner._safe_work_allows_delivery_or_auto_execution(
        {
            "status": "blocked_human_handoff_required",
            "audit": {"status": "blocked"},
            "browser_action_receipt": {"user_action_required": True},
        }
    ) is True


def test_runner_blocks_browser_handoff_delivery_without_user_action_receipt() -> None:
    assert runner._safe_work_allows_delivery_or_auto_execution(
        {
            "status": "blocked_human_handoff_required",
            "audit": {"status": "blocked"},
            "browser_action_receipt": {"user_action_required": False},
        }
    ) is False


def test_runner_blocks_provider_reference_candidate_even_if_audit_passes() -> None:
    candidate = {
        "label": "Difference between ein, eine, einen, and einem in the German language",
        "url": "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/",
        "snippet": "German language grammar explainer article.",
        "reachable": True,
    }

    assert runner._safe_work_allows_delivery_or_auto_execution(
        {
            "status": "staged_for_user_decision",
            "work_type": "compare_options",
            "recommended_option_or_draft": {"kind": "shortlist_candidate", "value": candidate},
            "shortlist": [candidate],
            "execution_receipt": {
                "context_fit_receipt": {
                    "provider_discovery_relevant": True,
                }
            },
            "audit": {"status": "pass", "issues": []},
        }
    ) is False
