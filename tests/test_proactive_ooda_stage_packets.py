from __future__ import annotations

import json
from dataclasses import replace

from app.services.proactive_ooda_service import ProactiveOodaService
from app.services.proactive_ooda_stage_packets import (
    SAFE_WORK_ORDER_SCHEMA,
    STAGE_PACKET_SCHEMA,
    build_stage_packets,
    default_stage_packet_dir,
    persist_stage_packets,
)


def _digest_with_stage():
    return ProactiveOodaService().build_digest(
        principal_id="cf-email:user@example.test",
        signals=[
            {
                "source_ref": "opportunity:private-source",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Private summary.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "Review a reversible vendor candidate"},
                        "orient": {"summary": "The window is useful but not urgent."},
                        "decide": {
                            "summary": "Approve whether EA should proceed.",
                            "approval_required": True,
                        },
                        "act": {
                            "summary": "Stage the vendor candidate for approval.",
                            "action_plan": ["Compare constraints", "Prepare approval packet"],
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "One vendor candidate ready for approval.",
                                "artifacts": ["shortlist", "approval_prompt"],
                                "candidate_items": [
                                    {"label": "Candidate A", "url": "https://example.test/candidate-a"}
                                ],
                                "approval_url": "https://example.test/approve",
                                "work_type": "prepare_cart_or_link",
                                "research_query": "Find a vendor option that matches the private constraints.",
                                "target_sites": ["https://example.test"],
                                "selection_criteria": ["fits constraints", "reversible before approval"],
                                "budget": {"max": 100, "currency": "EUR"},
                                "approval_gate": "User must approve before any purchase or booking.",
                            },
                            "external_action_policy": "Do not buy, book, send, cancel, or commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )


def test_stage_packet_preserves_reversible_action_contract_without_raw_identity() -> None:
    digest = _digest_with_stage()

    packets = build_stage_packets(digest)
    serialized = json.dumps(packets[0], sort_keys=True)

    assert len(packets) == 1
    packet = packets[0]
    assert packet["schema"] == STAGE_PACKET_SCHEMA
    assert packet["packet_ref"].startswith("stage_packet:proactive-ooda-stage-")
    assert packet["stage"]["kind"] == "approval_packet"
    assert packet["stage"]["payload"]["candidate_items"] == [
        {"label": "Candidate A", "url": "https://example.test/candidate-a"}
    ]
    assert packet["stage"]["payload"]["approval_url"] == "https://example.test/approve"
    assert packet["approval"]["required"] is True
    assert packet["approval"]["irreversible_actions_require_explicit_approval"] is True
    assert "purchase" in packet["execution_policy"]["forbidden_without_explicit_approval"]
    assert packet["safe_work_order"]["schema"] == SAFE_WORK_ORDER_SCHEMA
    assert packet["safe_work_order"]["status"] == "queued"
    assert packet["safe_work_order"]["work_type"] == "prepare_cart_or_link"
    assert packet["safe_work_order"]["primary_allowed_operation"] == "prepare_cart_or_link"
    assert "prepare_cart_or_link" in packet["safe_work_order"]["allowed_operations"]
    assert "purchase" in packet["safe_work_order"]["forbidden_without_explicit_approval"]
    assert packet["safe_work_order"]["handoff_policy"]["human_approval_required_before_irreversible_action"] is True
    assert packet["safe_work_order"]["input_contract"]["research_query"] == "Find a vendor option that matches the private constraints."
    assert packet["safe_work_order"]["input_contract"]["target_sites"] == ["https://example.test"]
    assert packet["safe_work_order"]["input_contract"]["selection_criteria"] == [
        "fits constraints",
        "reversible before approval",
    ]
    assert packet["safe_work_order"]["quality_gate"]["pre_user_audit_required"] is True
    assert packet["safe_work_order"]["quality_gate"]["notification_policy"] == "action_required_only"
    assert "source_relevance" in packet["safe_work_order"]["quality_gate"]["checks"]
    assert "candidate_quality_failed" in packet["safe_work_order"]["quality_gate"]["fail_closed_if"]
    assert "final_surface_url" in packet["safe_work_order"]["quality_gate"]["browser_receipt_required_fields"]
    assert "quality_gate" in packet["safe_work_order"]["output_contract"]["must_include"]
    assert "audit_receipt" in packet["safe_work_order"]["output_contract"]["must_include"]
    assert "approval_prompt" in packet["safe_work_order"]["output_contract"]["must_include"]
    assert "cf-email:user@example.test" not in serialized
    assert "opportunity:private-source" not in serialized


def test_stage_packet_requires_generic_pre_user_audit_for_provider_outreach_draft() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="cf-email:tibor@example.test",
        signals=[
            {
                "source_ref": "telegram:vendor-draft-quality-gate",
                "signal_type": "telegram_message",
                "channel": "telegram",
                "title": "Suche einen Rauchfangkehrer",
                "summary": "Find a chimney sweep and save a Gmail draft.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "The user asked EA to find a provider and create a draft."},
                        "orient": {"summary": "Use stored Vienna context and validate the provider before drafting."},
                        "decide": {"summary": "EA can draft only after candidate quality passes.", "approval_required": False},
                        "act": {
                            "summary": "Find a provider and draft the inquiry.",
                            "stage": {
                                "kind": "research_packet",
                                "summary": "Research-backed inquiry draft.",
                                "work_type": "draft",
                                "draft_mode": "research_backed_inquiry",
                                "request": "suche mir rauchfangkehrer fuer ein Gutachten in 1200 Wien",
                                "expected_counterparty_type": "rauchfangkehrer",
                                "required_location": "1200 Wien",
                                "required_locale": "de-AT",
                                "contact_channel_required": "email",
                                "source_relevance_requirements": [
                                    "direct Rauchfangkehrer or chimney-sweep provider page",
                                    "Vienna or Austria service area",
                                    "visible contact path",
                                ],
                                "known_bad_source_patterns": [
                                    "grammar lesson",
                                    "language translation",
                                    "generic reference page",
                                ],
                                "candidate_items": [
                                    {
                                        "label": "Difference between ein, eine, einen, and einem in German",
                                        "url": "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/",
                                        "snippet": "German language grammar lesson",
                                    }
                                ],
                            },
                            "external_action_policy": "Draft only; do not send externally.",
                        },
                    }
                },
            }
        ],
    )

    packet = build_stage_packets(digest)[0]
    order = packet["safe_work_order"]
    quality_gate = order["quality_gate"]
    input_contract = order["input_contract"]

    assert order["work_type"] == "draft"
    assert input_contract["expected_counterparty_type"] == "rauchfangkehrer"
    assert input_contract["required_location"] == "1200 Wien"
    assert input_contract["contact_channel_required"] == "email"
    assert "grammar lesson" in input_contract["known_bad_source_patterns"]
    assert quality_gate["pre_user_audit_required"] is True
    assert quality_gate["expected_counterparty_type"] == "rauchfangkehrer"
    assert quality_gate["required_location"] == "1200 Wien"
    assert quality_gate["required_locale"] == "de-AT"
    assert quality_gate["requires_validated_contact_for_draft"] is True
    assert "counterparty_type_match" in quality_gate["checks"]
    assert "geography_or_locality_fit" in quality_gate["checks"]
    assert "draft_recipient_validity" in quality_gate["checks"]
    assert "irrelevant_source_for_requested_counterparty" in quality_gate["fail_closed_if"]
    assert "wrong_country_or_location" in quality_gate["fail_closed_if"]
    assert "missing_contact_channel_for_draft" in quality_gate["fail_closed_if"]
    assert "quality_gate_failed" in quality_gate["accepted_stop_conditions"]
    assert "irreversible_actions_attempted" in quality_gate["browser_receipt_required_fields"]


def test_persist_stage_packets_writes_private_packet_files(tmp_path) -> None:
    digest = _digest_with_stage()

    result = persist_stage_packets(digest=digest, output_dir=tmp_path)

    assert not result.errors
    assert len(result.paths) == 1
    assert len(result.packet_refs) == 1
    packet = json.loads((tmp_path / f"{result.packet_refs[0].removeprefix('stage_packet:')}.json").read_text(encoding="utf-8"))
    assert packet["packet_ref"] == result.packet_refs[0]
    assert packet["stage"]["summary"] == "One vendor candidate ready for approval."


def test_persist_stage_packets_refreshes_existing_artifact_for_same_signal(tmp_path) -> None:
    digest = _digest_with_stage()
    first = persist_stage_packets(digest=digest, output_dir=tmp_path)

    refreshed = replace(digest, generated_at="2026-06-27T12:00:00+00:00")
    second = persist_stage_packets(digest=refreshed, output_dir=tmp_path)

    assert not first.errors
    assert not second.errors
    assert first.packet_refs == second.packet_refs
    assert len(list(tmp_path.glob("*.json"))) == 1
    packet = json.loads((tmp_path / f"{first.packet_refs[0].removeprefix('stage_packet:')}.json").read_text(encoding="utf-8"))
    assert packet["generated_at"] == "2026-06-27T12:00:00+00:00"


def test_persist_stage_packets_reports_directory_errors(tmp_path) -> None:
    digest = _digest_with_stage()
    blocked_path = tmp_path / "blocked"
    blocked_path.write_text("not a directory", encoding="utf-8")

    result = persist_stage_packets(digest=digest, output_dir=blocked_path)

    assert result.paths == ()
    assert result.packet_refs == ()
    assert result.errors == ("stage_packet_dir:FileExistsError",)


def test_default_stage_packet_dir_sits_next_to_state_file(tmp_path) -> None:
    target = default_stage_packet_dir(root=tmp_path, state_path="state/proactive_ooda_notified.json")

    assert target == tmp_path / "state" / "proactive_ooda_stage_packets"
