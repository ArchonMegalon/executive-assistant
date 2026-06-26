from __future__ import annotations

import json

from app.services.proactive_ooda_safe_work import (
    SAFE_WORK_RESULT_SCHEMA,
    build_safe_work_result,
    default_safe_work_result_dir,
    persist_safe_work_results,
    persist_safe_work_results_from_paths,
)
from app.services.proactive_ooda_service import ProactiveOodaService
from app.services.proactive_ooda_stage_packets import build_stage_packets, persist_stage_packets


def _packet_with_cart_work() -> dict[str, object]:
    digest = ProactiveOodaService().build_digest(
        principal_id="cf-email:user@example.test",
        signals=[
            {
                "source_ref": "opportunity:private-cart",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Prepare a reversible cart candidate",
                "summary": "Private shopping context.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "A reversible cart can be prepared."},
                        "orient": {"summary": "This is useful but must remain approval gated."},
                        "decide": {"summary": "Approve whether EA should proceed.", "approval_required": True},
                        "act": {
                            "summary": "Prepare a reversible cart link.",
                            "stage": {
                                "kind": "cart_draft",
                                "summary": "One cart candidate ready for approval.",
                                "artifacts": ["comparison", "cart_or_link", "approval_prompt"],
                                "work_type": "prepare_cart_or_link",
                                "cart_url": "https://example.test/cart/private",
                                "candidate_items": [
                                    {"label": "Candidate A", "url": "https://example.test/item-a"}
                                ],
                                "selection_criteria": ["fits constraints", "reversible before approval"],
                                "constraints": {"budget_max": 100, "currency": "EUR"},
                                "approval_gate": "User must approve before purchase.",
                            },
                            "external_action_policy": "Do not buy, book, send, cancel, post, or commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    return build_stage_packets(digest)[0]


def test_build_safe_work_result_materializes_reversible_cart_contract() -> None:
    packet = _packet_with_cart_work()

    result = build_safe_work_result(packet, generated_at="2026-06-26T12:00:00+00:00")
    serialized = json.dumps(result, sort_keys=True)

    assert result["schema"] == SAFE_WORK_RESULT_SCHEMA
    assert result["result_ref"].startswith("safe_work_result:proactive-ooda-safe-work-")
    assert result["status"] == "staged_for_user_decision"
    assert result["work_type"] == "prepare_cart_or_link"
    assert result["recommended_option_or_draft"] == {
        "kind": "reversible_cart_or_link",
        "value": "https://example.test/cart/private",
        "source": "stage_payload",
    }
    assert result["shortlist"] == [{"label": "Candidate A", "url": "https://example.test/item-a"}]
    assert result["approval"]["required"] is True
    assert result["execution_receipt"]["external_actions_attempted"] == []
    assert result["execution_receipt"]["irreversible_actions_attempted"] == []
    assert "purchase" in result["execution_receipt"]["forbidden_without_explicit_approval"]
    assert "cf-email:user@example.test" not in serialized
    assert "opportunity:private-cart" not in serialized


def test_build_safe_work_result_blocks_when_no_research_input_exists() -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"] = {"kind": "research_packet", "summary": "Research is needed."}  # type: ignore[index]
    packet["safe_work_order"]["work_type"] = "research"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {"expected_artifacts": [], "private_payload_available": False}  # type: ignore[index]

    result = build_safe_work_result(packet, generated_at="2026-06-26T12:00:00+00:00")

    assert result["status"] == "blocked_needs_research_input"
    assert result["recommended_option_or_draft"] == {}
    assert "research further" in result["approval_prompt"]
    assert result["execution_receipt"]["external_actions_attempted"] == []


def test_persist_safe_work_results_writes_private_result_files(tmp_path) -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:compare",
                "title": "Compare vendor options",
                "summary": "Review options before renewal.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "decide": {"summary": "Approve whether to proceed.", "approval_required": True},
                        "act": {
                            "summary": "Compare two vendor options.",
                            "stage": {
                                "kind": "shortlist",
                                "summary": "Two options ready for review.",
                                "work_type": "compare_options",
                                "candidate_items": [{"label": "Option A"}, {"label": "Option B"}],
                            },
                            "external_action_policy": "Do not commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    stage_dir = tmp_path / "stage"
    result_dir = tmp_path / "results"
    stage_result = persist_stage_packets(digest=digest, output_dir=stage_dir)

    result = persist_safe_work_results(stage_packet_dir=stage_dir, result_dir=result_dir)

    assert not stage_result.errors
    assert not result.errors
    assert len(result.paths) == 1
    assert len(result.result_refs) == 1
    payload = json.loads((result_dir / f"{result.result_refs[0].removeprefix('safe_work_result:')}.json").read_text(encoding="utf-8"))
    assert payload["schema"] == SAFE_WORK_RESULT_SCHEMA
    assert payload["work_type"] == "compare_options"


def test_persist_safe_work_results_from_paths_only_materializes_current_packets(tmp_path) -> None:
    stage_dir = tmp_path / "stage"
    result_dir = tmp_path / "results"
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:current",
                "title": "Prepare current packet",
                "summary": "Review this packet.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "decide": {"summary": "Approve whether to proceed.", "approval_required": True},
                        "act": {
                            "summary": "Stage the current packet.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "Current packet ready.",
                                "candidate_items": [{"label": "Current"}],
                            },
                            "external_action_policy": "Do not commit without explicit approval.",
                        },
                    }
                },
            },
            {
                "source_ref": "opportunity:also-current",
                "title": "Prepare second packet",
                "summary": "Review this second packet.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "decide": {"summary": "Approve whether to proceed.", "approval_required": True},
                        "act": {
                            "summary": "Stage the second packet.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "Second packet ready.",
                                "candidate_items": [{"label": "Second"}],
                            },
                            "external_action_policy": "Do not commit without explicit approval.",
                        },
                    }
                },
            },
        ],
    )
    stage_result = persist_stage_packets(digest=digest, output_dir=stage_dir)

    result = persist_safe_work_results_from_paths(stage_packet_paths=stage_result.paths[:1], result_dir=result_dir)

    assert not result.errors
    assert len(stage_result.paths) == 2
    assert len(result.paths) == 1
    assert len(result.result_refs) == 1


def test_default_safe_work_result_dir_sits_next_to_stage_packet_dir(tmp_path) -> None:
    assert default_safe_work_result_dir(tmp_path / "state" / "proactive_ooda_stage_packets") == (
        tmp_path / "state" / "proactive_ooda_safe_work_results"
    )
