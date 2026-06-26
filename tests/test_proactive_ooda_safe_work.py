from __future__ import annotations

import json
from io import BytesIO
from datetime import datetime, timedelta, timezone

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
    assert result["staged_action_url"] == "https://example.test/cart/private"
    assert result["shortlist"] == [{"label": "Candidate A", "url": "https://example.test/item-a"}]
    assert result["comparison_table"][0]["recommended"] is True
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


def test_build_safe_work_result_enriches_live_page_checks_and_prefers_reachable_candidate(monkeypatch) -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"]["cart_url"] = ""  # type: ignore[index]
    packet["stage"]["payload"]["candidate_items"] = [  # type: ignore[index]
        {"label": "Candidate A", "url": "https://example.test/item-a"},
        {"label": "Candidate B", "url": "https://example.test/item-b"},
    ]

    class Response:
        def __init__(self, url: str, html: str, status: int = 200):
            self._url = url
            self.status = status
            self.headers = type("Headers", (), {"get": lambda self, key, default=None: "text/html; charset=utf-8" if key == "Content-Type" else default, "get_content_charset": lambda self: "utf-8"})()
            self._body = html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, *_args):
            return self._body

        def geturl(self):
            return self._url

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/item-a"):
            raise RuntimeError("first_candidate_unreachable")
        return Response("https://example.test/item-b", "<html><head><title>Candidate B Live</title></head></html>")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = build_safe_work_result(packet, network_fetch_enabled=True, network_fetch_limit=4, network_fetch_timeout_seconds=3)

    assert result["execution_receipt"]["network_fetch_enabled"] is True
    assert result["execution_receipt"]["network_fetch_count"] == 2
    assert result["execution_receipt"]["network_fetch_success_count"] == 1
    assert result["recommended_option_or_draft"]["kind"] == "reversible_cart_or_link"
    assert result["recommended_option_or_draft"]["value"] == "https://example.test/item-b"
    assert result["staged_action_url"] == "https://example.test/item-b"
    assert result["shortlist"][0]["label"] == "Candidate B"
    assert result["shortlist"][0]["reachable"] is True
    assert result["shortlist"][0]["page_title"] == "Candidate B Live"
    assert result["shortlist"][1]["label"] == "Candidate A"
    assert result["shortlist"][1]["reachable"] is False
    assert "Live page checks verified 1/2 URLs." in result["summary"]
    candidate_refs = [ref for ref in result["evidence_refs"] if ref["kind"] == "candidate"]
    assert candidate_refs[0]["page_title"] == "Candidate B Live"
    assert result["comparison_table"][0]["label"] == "Candidate B"
    assert result["comparison_table"][0]["recommended"] is True


def test_build_safe_work_result_scores_candidates_against_budget_preferences_and_reversibility() -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"]["kind"] = "shortlist"  # type: ignore[index]
    packet["stage"]["payload"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["stage"]["payload"]["approval_url"] = ""  # type: ignore[index]
    packet["safe_work_order"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["stage"]["payload"]["candidate_items"] = [  # type: ignore[index]
        {
            "label": "Candidate A",
            "url": "https://example.test/item-a",
            "price_value": 89,
            "currency": "EUR",
            "reversible_before_approval": True,
            "delivery_days": 4,
            "tags": ["cool weather", "outdoor"],
        },
        {
            "label": "Candidate B",
            "url": "https://example.test/item-b",
            "price_value": 129,
            "currency": "EUR",
            "reversible_before_approval": True,
            "delivery_days": 1,
            "tags": ["outdoor"],
        },
        {
            "label": "Candidate C",
            "url": "https://example.test/item-c",
            "price_value": 79,
            "currency": "USD",
            "reversible_before_approval": False,
            "delivery_days": 2,
            "tags": ["indoor"],
        },
    ]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "selection_criteria": ["reversible before approval", "price", "timing"],
        "preferences": ["cool weather"],
        "budget": {"max": 100, "currency": "EUR"},
        "expected_artifacts": ["shortlist"],
        "private_payload_available": True,
    }

    result = build_safe_work_result(packet)

    assert result["recommended_option_or_draft"]["kind"] == "shortlist_candidate"
    assert result["recommended_option_or_draft"]["value"]["label"] == "Candidate A"
    assert [item["label"] for item in result["shortlist"]] == ["Candidate A", "Candidate B", "Candidate C"]
    assert result["comparison_table"][0]["label"] == "Candidate A"
    assert result["comparison_table"][0]["recommended"] is True
    assert "within budget <= 100" in result["comparison_table"][0]["matched_criteria"]
    assert "reversible before approval" in result["comparison_table"][0]["matched_criteria"]
    assert any("over budget" in value for value in result["comparison_table"][1]["constraint_violations"])
    assert any("currency mismatch" in value for value in result["comparison_table"][2]["constraint_violations"])
    assert any("not reversible" in value for value in result["comparison_table"][2]["constraint_violations"])


def test_build_safe_work_result_uses_profile_assessment_and_timing_window() -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"]["kind"] = "shortlist"  # type: ignore[index]
    packet["stage"]["payload"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["safe_work_order"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["stage"]["payload"]["approval_url"] = ""  # type: ignore[index]
    deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "selection_criteria": ["timing", "reversible before approval"],
        "deadline": deadline,
        "expected_artifacts": ["shortlist"],
        "private_payload_available": True,
    }
    packet["stage"]["payload"]["candidate_items"] = [  # type: ignore[index]
        {
            "label": "Candidate A",
            "url": "https://example.test/item-a",
            "delivery_days": 2,
            "reversible_before_approval": True,
            "preference_assessment": {
                "fit_score": 82.0,
                "recommendation": "shortlist",
                "match_reasons_json": ["Matches stored profile"],
                "mismatch_reasons_json": [],
                "blocking_constraints_json": [],
            },
        },
        {
            "label": "Candidate B",
            "url": "https://example.test/item-b",
            "delivery_days": 5,
            "reversible_before_approval": True,
            "preference_assessment": {
                "fit_score": 28.0,
                "recommendation": "reject",
                "match_reasons_json": [],
                "mismatch_reasons_json": ["Conflicts with stored preferences"],
                "blocking_constraints_json": [],
            },
        },
    ]

    result = build_safe_work_result(packet)

    assert [item["label"] for item in result["shortlist"]] == ["Candidate A", "Candidate B"]
    assert result["comparison_table"][0]["label"] == "Candidate A"
    assert "profile fit 82" in result["comparison_table"][0]["matched_criteria"]
    assert any("meets timing window" in value for value in result["comparison_table"][0]["recommendation_reasons"])
    assert any("misses timing window" in value for value in result["comparison_table"][1]["constraint_violations"])
    assert any("Conflicts with stored preferences" in value for value in result["comparison_table"][1]["constraint_violations"])


def test_build_safe_work_result_keeps_stable_result_id_across_regeneration() -> None:
    packet = _packet_with_cart_work()

    first = build_safe_work_result(packet, generated_at="2026-06-26T12:00:00+00:00")
    second = build_safe_work_result(packet, generated_at="2026-06-27T12:00:00+00:00")

    assert first["result_id"] == second["result_id"]
    assert first["result_ref"] == second["result_ref"]


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


def test_persist_safe_work_results_from_paths_refreshes_existing_result(tmp_path) -> None:
    packet = _packet_with_cart_work()
    stage_dir = tmp_path / "stage"
    result_dir = tmp_path / "results"
    stage_dir.mkdir()
    stage_path = stage_dir / f"{packet['packet_id']}.json"
    stage_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    first = persist_safe_work_results_from_paths(stage_packet_paths=(stage_path,), result_dir=result_dir)
    second = persist_safe_work_results_from_paths(stage_packet_paths=(stage_path,), result_dir=result_dir)

    assert not first.errors
    assert not second.errors
    assert first.result_refs == second.result_refs
    assert len(list(result_dir.glob("*.json"))) == 1


def test_persist_safe_work_results_from_paths_can_disable_network_fetch(monkeypatch, tmp_path) -> None:
    packet = _packet_with_cart_work()
    stage_dir = tmp_path / "stage"
    result_dir = tmp_path / "results"
    stage_dir.mkdir()
    stage_path = stage_dir / f"{packet['packet_id']}.json"
    stage_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seen: list[str] = []

    def fake_urlopen(request, timeout):
        seen.append(request.full_url)
        return BytesIO(b"")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = persist_safe_work_results_from_paths(
        stage_packet_paths=(stage_path,),
        result_dir=result_dir,
        network_fetch_enabled=False,
    )

    assert not result.errors
    assert seen == []


def test_default_safe_work_result_dir_sits_next_to_stage_packet_dir(tmp_path) -> None:
    assert default_safe_work_result_dir(tmp_path / "state" / "proactive_ooda_stage_packets") == (
        tmp_path / "state" / "proactive_ooda_safe_work_results"
    )
