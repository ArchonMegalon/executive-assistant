from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from scripts.source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "materialize_proactive_ooda_gold_acceptance.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("materialize_proactive_ooda_gold_acceptance", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module._operator_status_prefers_live_runtime_bundle = lambda operator_status=None: False  # noqa: SLF001
    return module


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _approval_capture_ready() -> dict[str, object]:
    return {
        "checked": True,
        "probe_ok": True,
        "ready": True,
        "status": "ready",
        "source": "docker_compose_exec:proactive_approval_capture",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-06-29T06:55:20Z",
        "blocking_reason": "",
        "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
        "callback_dir_exists": True,
        "callback_record_count": 1,
        "current_packet_ref_sha256": "a" * 64,
        "current_staged_artifact_ref_sha256": "b" * 64,
        "current_packet_refs_present": True,
        "current_packet_callback_record_count": 1,
        "current_packet_live_pending_count": 1,
        "current_packet_callback_latest_status": "pending",
        "current_packet_callback_latest_expired": False,
        "current_packet_callback_latest_age_seconds": 91,
        "current_packet_callback_latest_seconds_until_expiry": 1200,
        "callback_principal_hash_present": True,
        "candidate_principal_hash_count": 3,
        "principal_match_ready": True,
        "telegram_binding_ready": True,
        "telegram_blocking_reason": "",
        "telegram_chat_ref_present": True,
        "telegram_chat_ref_sha256": "c" * 64,
        "telegram_bot_key_present": True,
        "telegram_bot_token_present": True,
        "privacy": {
            "raw_callback_token_exposed": False,
            "raw_principal_id_exposed": False,
            "raw_chat_ref_exposed": False,
            "raw_packet_ref_exposed": False,
            "raw_staged_artifact_ref_exposed": False,
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "ea_proactive_ooda_operator_status.generated.json" and "approval_capture" not in payload:
        payload = {
            **payload,
            "approval_capture": _approval_capture_ready(),
            "source_state_fingerprint": str(payload.get("source_state_fingerprint") or resolve_source_worktree_fingerprint(ROOT)),
            "context_grounding": dict(payload.get("context_grounding") or {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 2,
                "recipient_location_count": 1,
            }),
        }
    elif path.name == "ea_proactive_ooda_operator_status.generated.json" and "source_state_fingerprint" not in payload:
        payload = {
            **payload,
            "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        }
    if path.name == "ea_proactive_ooda_operator_status.generated.json" and "context_grounding" not in payload:
        payload = {
            **payload,
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 2,
                "recipient_location_count": 1,
            },
        }
    if "notification_status" in payload and "stage_packet_output_dir" not in payload and "safe_work_result_output_dir" not in payload:
        isolated_stage_dir = path.parent / "stage_packets"
        isolated_safe_dir = path.parent / "safe_work_results"
        isolated_stage_dir.mkdir(parents=True, exist_ok=True)
        isolated_safe_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            **payload,
            "stage_packet_output_dir": str(isolated_stage_dir),
            "safe_work_result_output_dir": str(isolated_safe_dir),
        }
    if payload.get("schema") == "proactive_ooda.safe_work_result.v1" and "audit" not in payload:
        payload = {**payload, "audit": {"status": "pass", "issues": []}}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_operator_runtime_source_coverage_posture_ignores_property_exclusion_noise() -> None:
    module = _load_script()

    ready, detail = module._operator_runtime_source_coverage_posture(  # noqa: SLF001
        {
            "source_coverage": {
                "checked": True,
                "status": "ready",
                "lane_count": 8,
                "observed_lane_count": 8,
                "missing_lane_keys": [],
                "lanes": [],
            }
        }
    )

    assert ready is True
    assert "source_coverage_flat_search_enabled" not in detail
    assert "source_coverage_excluded_event_types" not in detail
    assert "source_coverage_excluded_event_type_counts" not in detail


def test_operator_runtime_context_grounding_posture_blocks_ungrounded_actionable_items() -> None:
    module = _load_script()

    ready, detail = module._operator_runtime_context_grounding_posture(  # noqa: SLF001
        {
            "context_grounding": {
                "grounded": False,
                "item_count": 2,
                "grounded_item_count": 1,
                "ungrounded_item_count": 1,
                "applied_context_count": 3,
                "recipient_location_count": 1,
            }
        }
    )

    assert ready is False
    assert detail["context_grounding_ready"] is False
    assert detail["context_grounding_recorded"] is True
    assert detail["context_grounding_item_count"] == 2
    assert detail["context_grounding_ungrounded_item_count"] == 1
    assert detail["next_action"] == "repair_proactive_context_grounding"


def test_operator_runtime_suppressed_projection_posture_blocks_recovery() -> None:
    module = _load_script()

    ready, detail = module._operator_runtime_suppressed_projection_posture(  # noqa: SLF001
        {
            "suppressed_projection": {
                "present": True,
                "status": "suppressed",
                "requires_recovery": True,
                "blocking_reason": "suppressed_safe_work_projection",
                "suppressed_item_count": 2,
                "suppressed_safe_work_review_count": 2,
                "suppressed_projection_reasons": ["safe_work_audit_review"],
                "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                "teable_status": "synced",
                "projection_record_count": 1,
                "packet_projection_record_count": 0,
            }
        }
    )

    assert ready is False
    assert detail["suppressed_projection_ready"] is False
    assert detail["suppressed_projection_item_count"] == 2
    assert detail["suppressed_projection_issue_codes"] == ["no_decision_ready_material"]
    assert detail["next_action"] == "repair_proactive_safe_work_audit"


def test_operator_runtime_suppressed_projection_posture_allows_non_material_quiet_suppression() -> None:
    module = _load_script()

    ready, detail = module._operator_runtime_suppressed_projection_posture(  # noqa: SLF001
        {
            "suppressed_projection": {
                "present": True,
                "status": "suppressed_non_material",
                "requires_recovery": False,
                "blocking_reason": "",
                "suppressed_non_material": True,
                "suppressed_non_material_reason": "quiet_no_decision_ready_material",
                "suppressed_item_count": 2,
                "suppressed_safe_work_review_count": 2,
                "suppressed_projection_reasons": ["safe_work_audit_review"],
                "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                "teable_status": "synced",
                "projection_record_count": 1,
                "packet_projection_record_count": 0,
            }
        }
    )

    assert ready is True
    assert detail["suppressed_projection_ready"] is True
    assert detail["suppressed_projection_requires_recovery"] is False
    assert detail["suppressed_projection_item_count"] == 2
    assert detail["suppressed_projection_issue_codes"] == ["no_decision_ready_material"]
    assert detail["next_action"] == ""


def test_materialize_proactive_ooda_gold_acceptance_passes_with_full_proof_chain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    monkeypatch.setattr(module, "_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})
    monkeypatch.setattr(module, "_live_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_id": "pkt-1",
        "packet_ref": "stage_packet:pkt-1",
        "stage": {"kind": "approval_packet", "summary": "One packet is staged."},
        "approval": {"required": True},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-1",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A"}, {"label": "Vendor B"}],
        "approval": {"required": True},
        "audit": {"status": "pass", "issues": []},
        "execution_receipt": {
            "network_fetch_count": 2,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-1.json", stage_packet)
    _write_json(safe_dir / "res-1.json", safe_work_result)
    _write_json(
        operator_status_path,
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_live_receipt",
                "generated_at": "2026-06-26T18:29:00Z",
                "source_git_head": "source-head-123",
                "source_state_fingerprint": "source-fingerprint-123",
                "delivery_route_ready": True,
                "live_receipt_checked": True,
                "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 2,
                "recipient_location_count": 1,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        approval_outcome_input={
            "outcome": "approved",
            "source_kind": "operator",
            "evidence": "Approved after reviewing the live shortlist.",
            "actor": "operator-admin-1",
            "packet_ref": "stage_packet:pkt-1",
            "staged_artifact_ref": "safe_work_result:res-1",
            "recorded_at": "2026-06-26T18:30:00Z",
        },
        generated_at="2026-06-26T18:31:00Z",
    )

    assert receipt["contract_name"] == "ea.proactive_ooda_gold_acceptance.v1"
    assert receipt["generated_by"] == "scripts/materialize_proactive_ooda_gold_acceptance.py"
    assert receipt["source_git_head"] == "source-head-123"
    assert receipt["status"] == "pass"
    assert receipt["gold_claim_allowed"] is True
    assert receipt["remaining_external_proofs"] == []
    assert receipt["proofs"]["routed_delivery"]["present"] is True
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is True
    assert receipt["proofs"]["action_required_only_delivery"]["policy_probe_checked"] is True
    assert receipt["proofs"]["action_required_only_delivery"]["policy_probe_status"] == "pass"
    assert receipt["proofs"]["action_required_only_delivery"]["low_value_research_prompt_requires_user_action"] is False
    assert receipt["proofs"]["action_required_only_delivery"]["internal_proof_packet_requires_user_action"] is False
    assert receipt["proofs"]["action_required_only_delivery"]["executable_draft_prompt_requires_user_action"] is True
    assert receipt["proofs"]["action_required_only_delivery"]["raw_policy_prompt_exposed"] is False
    assert receipt["proofs"]["browser_action_contract"]["present"] is True
    assert receipt["proofs"]["browser_action_contract"]["required_for_selected_packet"] is False
    assert receipt["proofs"]["live_browse_evidence"]["present"] is True
    assert receipt["proofs"]["chosen_candidate"]["present"] is True
    assert receipt["proofs"]["staged_reversible_artifact"]["present"] is True
    assert receipt["proofs"]["teable_projection"]["present"] is True
    assert receipt["proofs"]["approval_outcome"]["accepted"] is True
    assert receipt["proofs"]["approval_outcome"]["evidence_sha256"]
    assert receipt["evidence_receipts"]["stage_packet"]["path"].endswith("pkt-1.json")
    assert receipt["evidence_receipts"]["safe_work_result"]["path"].endswith("res-1.json")

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"
    assert persisted["proofs"]["approval_outcome"]["source_kind"] == "operator"
    assert persisted["evidence_receipts"]["operator_status"]["generated_at"] == "2026-06-26T18:29:00Z"
    assert persisted["evidence_receipts"]["operator_status"]["source_git_head"] == "source-head-123"


def test_materialize_proactive_ooda_gold_acceptance_counts_archived_sent_delivery_when_only_followthrough_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    run_receipt_dir = tmp_path / "state" / "proactive_ooda_run_receipts"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    run_receipt_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-archived-sent",
        "stage": {"kind": "approval_packet", "summary": "One packet is staged."},
        "approval": {"required": True},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-archived-sent",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A"}, {"label": "Vendor B"}],
        "approval": {"required": True},
        "audit": {"status": "pass", "issues": []},
        "execution_receipt": {
            "network_fetch_count": 2,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-archived-sent.json", stage_packet)
    _write_json(safe_dir / "res-archived-sent.json", safe_work_result)
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "generated_at": "2026-07-07T07:10:00Z",
            "source_git_head": "source-head-123",
            "source_state_fingerprint": "source-fingerprint-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {
                "ok": False,
                "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/runtime-sent.json",
                "errors": ["followthrough_artifacts_missing"],
                "archived_sent_receipt_used": True,
                "notification_status": "sent",
                "delivery_mode": "telegram_sent",
                "delivery_channel": "telegram",
                "delivery_message_count": 1,
                "telegram_message_count": 1,
            },
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 2,
                "recipient_location_count": 1,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )
    _write_json(
        run_receipt_dir / "20260707T070500Z-deferred-quiet.json",
        {
            "dry_run": False,
            "error_code": "no_user_action_required",
            "generated_at": "2026-07-07T07:05:00+00:00",
            "item_count": 4,
            "notification_status": "deferred",
            "delivery_message_ids": [],
            "telegram_message_ids": [],
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-07-07T07:11:00Z",
    )

    assert receipt["proofs"]["routed_delivery"]["present"] is True
    assert receipt["proofs"]["routed_delivery"]["delivery_mode"] == "telegram_sent"
    assert receipt["proofs"]["routed_delivery"]["live_receipt_ok"] is False
    assert receipt["proofs"]["routed_delivery"]["live_receipt_archived_sent_receipt_used"] is True
    assert receipt["proofs"]["routed_delivery"]["live_receipt_blocking_delivery_errors"] == []
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is True
    assert "routed delivery proof for a real proactive OODA packet" not in receipt["remaining_external_proofs"]
    assert "action-required-only Telegram delivery proof for the proactive OODA packet" not in receipt["remaining_external_proofs"]


def test_materialize_proactive_ooda_gold_acceptance_refreshes_operator_status_snapshot_after_runtime_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-current")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-current")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "reason": "ready",
            "generated_at": "2026-06-30T02:00:00Z",
            "source_git_head": "source-head-old",
            "source_state_fingerprint": "source-fingerprint-old",
            "next_action": "maintain_proactive_ooda_runtime",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/run.json", "delivery_channel": "telegram"},
            "approval_capture": _approval_capture_ready(),
        },
    )

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-1",
        "stage": {"kind": "research_packet", "summary": "One packet is staged."},
        "approval": {"required": True},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-1",
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A"}, {"label": "Vendor B"}],
        "approval": {"required": True},
        "audit": {"status": "pass", "issues": []},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
        },
    }
    run_receipt = {
        "notification_status": "sent",
        "item_count": 1,
        "delivery_channel": "telegram",
        "delivery_message_ids": ["msg-1"],
        "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
        "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
        "teable_sync": {
            "status": "synced",
            "projection_summary": {
                "tables": {
                    "proactive_ooda_items": {"record_count": 1},
                    "proactive_ooda_safe_work": {"record_count": 1},
                    "proactive_ooda_approval_outcomes": {"record_count": 1},
                    "proactive_ooda_approval_surfaces": {"record_count": 1},
                }
            },
        },
    }
    approval_outcome = {
        "status": "accepted_redacted",
        "accepted": True,
        "approval_outcome_recorded": True,
        "outcome": "approved",
        "source_kind": "telegram_button",
        "recorded_at": "2026-06-30T02:01:00Z",
        "evidence_sha256": _sha256("Approved after operator review."),
        "actor_sha256": _sha256("operator"),
        "packet_ref_sha256": _sha256(stage_packet["packet_ref"]),
        "staged_artifact_sha256": _sha256(safe_work_result["result_ref"]),
    }

    def _runtime_bundle(**_kwargs):
        _write_json(
            operator_status_path,
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_live_receipt",
                "reason": "ready",
                "generated_at": "2026-06-30T02:05:00Z",
                "source_git_head": "source-head-new",
                "source_state_fingerprint": "source-fingerprint-new",
                "next_action": "maintain_proactive_ooda_runtime",
                "delivery_route_ready": True,
                "live_receipt_checked": True,
                "delivery_route": {"selected_channel": "telegram"},
                "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/run.json", "delivery_channel": "telegram"},
                "approval_capture": _approval_capture_ready(),
            },
        )
        return (
            {
                "run_receipt_path": tmp_path / "state" / "proactive_ooda_latest_run.generated.json",
                "run_receipt": run_receipt,
                "action_required_only_quiet_receipt_path": None,
                "action_required_only_quiet_receipt": {},
                "stage_packet_dir": tmp_path / "state" / "proactive_ooda_stage_packets",
                "safe_work_result_dir": tmp_path / "state" / "proactive_ooda_safe_work_results",
                "stage_packet_path": tmp_path / "state" / "proactive_ooda_stage_packets" / "pkt.json",
                "stage_packet": stage_packet,
                "safe_work_result_path": tmp_path / "state" / "proactive_ooda_safe_work_results" / "res.json",
                "safe_work_result": safe_work_result,
                "approval_outcome_path": tmp_path / "state" / "proactive_ooda_latest_approval_outcome.generated.json",
                "approval_outcome": approval_outcome,
                "current_packet_callback_outcome": {},
                "approval_callback_dir": tmp_path / "state" / "proactive_ooda_approval_callbacks",
                "approval_callback_dir_exists": True,
                "approval_callback_dir_writable": True,
                "approval_callback_record_count": 1,
                "approval_callback_pending_count": 0,
                "approval_callback_raw_pending_count": 0,
                "approval_callback_live_pending_count": 0,
                "approval_callback_unexpired_pending_count": 0,
                "approval_callback_noncurrent_pending_count": 0,
                "approval_callback_stale_pending_count": 0,
                "approval_callback_expired_pending_count": 0,
                "approval_callback_recorded_count": 1,
                "approval_callback_expired_count": 0,
                "approval_callback_superseded_count": 0,
                "approval_callback_terminal_count": 1,
                "current_packet_callback_record_count": 1,
                "current_packet_callback_pending_count": 0,
                "current_packet_callback_raw_pending_count": 0,
                "current_packet_callback_stale_pending_count": 0,
                "current_packet_callback_expired_pending_count": 0,
                "current_packet_callback_recorded_count": 1,
                "current_packet_callback_expired_count": 0,
                "current_packet_callback_superseded_count": 0,
                "current_packet_live_callback_record_count": 1,
                "current_packet_live_pending_count": 0,
                "current_packet_callback_latest_status": "approved",
                "current_packet_callback_latest_expired": False,
                "current_packet_callback_latest_created_at": "2026-06-30T02:01:00Z",
                "current_packet_callback_latest_expires_at": "2026-07-07T02:01:00Z",
                "current_packet_callback_latest_age_seconds": 60,
                "current_packet_callback_latest_seconds_until_expiry": 604740,
            },
            True,
        )

    monkeypatch.setattr(module, "_runtime_artifact_bundle", _runtime_bundle)

    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
        operator_status_path=operator_status_path,
        generated_at="2026-06-30T02:06:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["evidence_receipts"]["operator_status"]["generated_at"] == "2026-06-30T02:05:00Z"
    assert receipt["evidence_receipts"]["operator_status"]["source_git_head"] == "source-head-new"
    assert receipt["evidence_receipts"]["operator_status"]["source_state_fingerprint"] == "source-fingerprint-new"


def test_materialize_proactive_ooda_gold_acceptance_blocks_without_packet_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})
    monkeypatch.setattr(module, "_live_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 2,
                "recipient_location_count": 1,
            },
            "runtime_actionable_count": 0,
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-06-26T18:40:00Z",
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["gold_claim_allowed"] is False
    assert "routed delivery proof for a real proactive OODA packet" in receipt["remaining_external_proofs"]
    assert "live browse evidence for a real proactive OODA packet" in receipt["remaining_external_proofs"]
    assert "mirrored Teable projection for the proactive OODA packet" in receipt["remaining_external_proofs"]
    assert receipt["proofs"]["routed_delivery"]["present"] is False
    assert receipt["proofs"]["live_browse_evidence"]["present"] is False


def test_materialize_proactive_ooda_gold_acceptance_blocks_audit_review_packet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)
    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_id": "pkt-review",
        "packet_ref": "stage_packet:pkt-review",
        "stage": {"kind": "approval_packet", "summary": "One packet is staged."},
        "approval": {"required": True},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-review",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A", "url": "https://example.test/vendor-a"}],
        "approval": {"required": True},
        "audit": {"status": "review", "issues": [{"code": "top_candidate_not_provider_like"}]},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-review.json", stage_packet)
    _write_json(safe_dir / "res-review.json", safe_work_result)
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "source_git_head": "source-head-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "approval_capture_pending",
                "user_action_required": True,
                "pending_approval_surface": True,
            },
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        approval_outcome_input={
            "outcome": "approved",
            "source_kind": "operator",
            "evidence": "Approved after review.",
            "actor": "operator-admin-1",
            "packet_ref": "stage_packet:pkt-review",
            "staged_artifact_ref": "safe_work_result:res-review",
            "recorded_at": "2026-06-26T18:30:00Z",
        },
        generated_at="2026-06-26T18:31:00Z",
    )

    assert receipt["status"] == "blocked_low_quality_packet_evidence"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["proofs"]["assistant_grade_packet_quality"]["present"] is False
    assert "safe_work_audit_not_pass" in receipt["proofs"]["assistant_grade_packet_quality"]["issues"]


def test_materialize_proactive_ooda_gold_acceptance_accepts_browser_handoff_contract_but_not_as_gold(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_id": "pkt-browser",
        "packet_ref": "stage_packet:pkt-browser",
        "stage": {"kind": "cart_draft", "summary": "Prepare a cart."},
        "approval": {"required": True},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-browser",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "blocked_human_handoff_required",
        "recommended_option_or_draft": {
            "kind": "reversible_cart_or_link",
            "value": "https://www.pagro.at/cart",
        },
        "shortlist": [{"label": "Pagro cart", "url": "https://www.pagro.at/cart"}],
        "approval": {"required": True},
        "approval_prompt": "Complete the browser challenge, then approve resume.",
        "browser_action_receipt": {
            "schema": "proactive_ooda.browser_action_receipt.v1",
            "status": "blocked_human_handoff_required",
            "user_action_required": True,
            "staged_artifact_present": False,
            "handoff": {
                "required": True,
                "blocker_code": "cloudflare_not_cleared",
            },
            "security": {
                "secret_values_stored": False,
            },
            "policy": {
                "irreversible_actions_attempted": [],
            },
            "privacy": {
                "raw_credentials_stored": False,
                "raw_cookie_or_session_stored": False,
            },
        },
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://www.pagro.at", "reachable": True}],
            "irreversible_actions_attempted": [],
            "browser_action_user_action_required": True,
        },
    }
    _write_json(stage_dir / "pkt-browser.json", stage_packet)
    _write_json(safe_dir / "res-browser.json", safe_work_result)
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "generated_at": "2026-06-29T08:10:00Z",
            "source_git_head": "source-head-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-06-29T08:11:00Z",
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["proofs"]["browser_action_contract"]["present"] is True
    assert receipt["proofs"]["browser_action_contract"]["required_for_selected_packet"] is True
    assert receipt["proofs"]["browser_action_contract"]["handoff_required"] is True
    assert receipt["proofs"]["browser_action_contract"]["blocker_code"] == "cloudflare_not_cleared"
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is True
    assert receipt["proofs"]["staged_reversible_artifact"]["present"] is False


def test_materialize_proactive_ooda_gold_acceptance_blocks_when_operator_runtime_posture_is_not_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_id": "pkt-1",
        "packet_ref": "stage_packet:pkt-1",
        "stage": {"kind": "approval_packet", "summary": "One packet is staged."},
        "approval": {"required": True},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-1",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A"}, {"label": "Vendor B"}],
        "approval": {"required": True},
        "execution_receipt": {
            "network_fetch_count": 2,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-1.json", stage_packet)
    _write_json(safe_dir / "res-1.json", safe_work_result)
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "blocked_local_runtime",
            "reason": "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant",
            "next_action": "reauthorize_google_workspace_binding",
            "generated_at": "2026-06-28T13:51:17Z",
            "source_git_head": "source-head-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "context_grounding": {
                "grounded": False,
                "item_count": 1,
                "grounded_item_count": 0,
                "ungrounded_item_count": 1,
                "applied_context_count": 0,
                "recipient_location_count": 0,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        approval_outcome_input={
            "outcome": "approved",
            "source_kind": "operator",
            "evidence": "Approved after reviewing the live shortlist.",
            "actor": "operator-admin-1",
            "packet_ref": "stage_packet:pkt-1",
            "staged_artifact_ref": "safe_work_result:res-1",
            "recorded_at": "2026-06-28T13:52:00Z",
        },
        generated_at="2026-06-28T13:53:00Z",
    )

    assert receipt["status"] == "blocked_operator_runtime_posture"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["next_action_href"] == (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    assert receipt["next_action_label"] == "Reconnect Google workspace"
    assert receipt["next_action_method"] == "get"
    assert receipt["proofs"]["operator_runtime_posture"]["present"] is False
    assert receipt["proofs"]["operator_runtime_posture"]["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["proofs"]["operator_runtime_posture"]["next_action_href"] == (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    assert receipt["proofs"]["operator_runtime_posture"]["context_grounding_recorded"] is True
    assert receipt["proofs"]["operator_runtime_posture"]["context_grounding_grounded"] is False
    assert receipt["proofs"]["operator_runtime_posture"]["context_grounding_ungrounded_item_count"] == 1
    assert receipt["proofs"]["approval_outcome"]["accepted"] is True
    assert "healthy operator runtime posture across approved proactive sources" in receipt["remaining_external_proofs"]


def test_materialize_proactive_ooda_gold_acceptance_prefers_source_health_recovery_action_over_coverage_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-source-health",
        "stage": {"kind": "approval_packet", "summary": "One packet is staged."},
        "approval": {"required": True},
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-source-health",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A"}],
        "approval": {"required": True},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-source-health.json", stage_packet)
    _write_json(safe_dir / "res-source-health.json", safe_work_result)
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_recovery_action",
            "reason": "source_health_google_workspace:google_oauth_invalid_grant",
            "next_action": "reauthorize_google_workspace_binding",
            "generated_at": "2026-07-06T12:52:00Z",
            "source_git_head": "source-head-123",
            "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "source_coverage": {
                "checked": True,
                "status": "ready_with_gaps",
                "lane_count": 2,
                "observed_lane_count": 1,
                "missing_lane_keys": ["postgres_observations"],
                "lanes": [
                    {
                        "key": "postgres_observations",
                        "observed": False,
                        "next_action": "verify_postgres_observation_source",
                        "missing_required_event_types": [],
                    },
                    {"key": "google_workspace", "observed": True, "missing_required_event_types": []},
                ],
            },
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 1,
                "recipient_location_count": 1,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-07-06T12:53:00Z",
    )

    assert receipt["status"] == "blocked_operator_runtime_posture"
    assert receipt["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["next_action_href"] == (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    assert receipt["proofs"]["operator_runtime_posture"]["next_action"] == "reauthorize_google_workspace_binding"


def test_materialize_proactive_ooda_gold_acceptance_does_not_request_approval_capture_for_non_recordable_recovery_packet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-recovery",
        "stage": {"kind": "research_packet", "summary": "One reversible research packet is staged."},
        "approval": {"required": False},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-recovery",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "draft_text",
            "value": "Draft to review: short reversible note.",
        },
        "shortlist": [{"label": "Candidate A"}],
        "approval": {"required": False},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/candidate-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-recovery.json", stage_packet)
    _write_json(safe_dir / "res-recovery.json", safe_work_result)
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_recovery_action",
            "reason": "source_health_google_workspace:google_oauth_invalid_grant",
            "next_action": "reauthorize_google_workspace_binding",
            "generated_at": "2026-07-06T13:02:00Z",
            "source_git_head": "source-head-123",
            "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "source_health": {
                "present": True,
                "status": "recovery_required",
                "operator_action_required": True,
                "user_action_required": True,
                "issues": [
                    {
                        "source_key": "google_workspace",
                        "source_type": "google_workspace",
                        "error_code": "google_oauth_invalid_grant",
                        "operator_action_required": True,
                        "user_action_required": True,
                        "next_action": "reauthorize_google_workspace_binding",
                    }
                ],
            },
            "source_coverage": {
                "checked": True,
                "status": "ready",
                "lane_count": 2,
                "observed_lane_count": 2,
                "missing_lane_keys": [],
                "lanes": [
                    {"key": "postgres_observations", "observed": True, "missing_required_event_types": []},
                    {"key": "google_workspace", "observed": True, "missing_required_event_types": []},
                ],
            },
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 1,
                "recipient_location_count": 1,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-07-06T13:03:00Z",
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["proofs"]["approval_capture_readiness"]["required"] is False
    assert receipt["proofs"]["approval_capture_readiness"]["ready"] is False
    assert "current recordable proactive OODA packet acceptance evidence" in receipt["remaining_external_proofs"]
    assert "redacted approval-capture readiness for the proactive OODA packet" not in receipt["remaining_external_proofs"]
    assert "redacted explicit approval outcome for the proactive OODA packet" not in receipt["remaining_external_proofs"]


def test_concrete_operator_recovery_action_prefers_source_health_issue_over_generic_followthrough() -> None:
    module = _load_script()

    assert module._concrete_operator_recovery_action(
        {
            "status": "ready_with_recovery_action",
            "reason": "followthrough_artifacts_missing",
            "next_action": "repair_proactive_operator_runtime_posture",
            "source_health": {
                "operator_action_required": True,
                "issues": [
                    {
                        "source_key": "google_workspace",
                        "error_code": "google_oauth_invalid_grant",
                        "next_action": "reauthorize_google_workspace_binding",
                    }
                ],
            },
        }
    ) == "reauthorize_google_workspace_binding"


def test_materialize_proactive_ooda_gold_acceptance_blocks_when_operator_safe_work_audit_is_not_deliverable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "blocked_local_runtime",
            "reason": "safe_work_audit_review",
            "next_action": "repair_proactive_safe_work_audit",
            "generated_at": "2026-06-29T08:00:00Z",
            "source_git_head": "source-head-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "delivery_guard": {"delivery_state": "eligible"},
            "source_coverage": {
                "checked": True,
                "status": "ready",
                "lane_count": 1,
                "observed_lane_count": 1,
                "missing_lane_keys": [],
                "lanes": [{"key": "postgres_observations", "observed": True, "missing_required_event_types": []}],
            },
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 1,
                "recipient_location_count": 1,
            },
            "safe_work_audit": {
                "present": True,
                "result_status": "blocked_needs_research_input",
                "audit_present": True,
                "audit_status": "review",
                "audit_passed": False,
                "issue_count": 1,
                "issue_codes": ["top_candidate_not_provider_like"],
                "issue_severity_counts": {"warn": 1},
                "browser_handoff_user_action_required": False,
                "delivery_allowed": False,
                "blocks_operator_followthrough": True,
                "blocking_reason": "safe_work_audit_review",
                "next_action": "repair_proactive_safe_work_audit",
            },
            "runtime_actionable_count": 1,
        },
    )
    _write_json(run_receipt_path, {"notification_status": "deferred", "item_count": 0})

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-06-29T08:01:00Z",
    )

    assert receipt["status"] == "blocked_operator_runtime_posture"
    assert receipt["next_action"] == "repair_proactive_safe_work_audit"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/app/queue"
    operator_runtime = receipt["proofs"]["operator_runtime_posture"]
    assert operator_runtime["present"] is False
    assert operator_runtime["safe_work_audit_recorded"] is True
    assert operator_runtime["safe_work_audit_ready"] is False
    assert operator_runtime["safe_work_audit_status"] == "review"
    assert operator_runtime["safe_work_audit_issue_codes"] == ["top_candidate_not_provider_like"]


def test_materialize_proactive_ooda_gold_acceptance_blocks_when_source_coverage_needs_postgres_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "reason": "ready",
            "generated_at": "2026-07-01T12:00:00Z",
            "source_git_head": "source-head-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "source_coverage": {
                "checked": True,
                "status": "ready_with_gaps",
                "lane_count": 2,
                "observed_lane_count": 1,
                "missing_lane_keys": ["postgres_observations"],
                "lanes": [
                    {
                        "key": "postgres_observations",
                        "observed": False,
                        "next_action": "verify_postgres_observation_source",
                        "missing_required_event_types": [],
                    },
                    {
                        "key": "google_workspace",
                        "observed": True,
                        "missing_required_event_types": [],
                    },
                ],
            },
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 1,
                "recipient_location_count": 1,
            },
            "safe_work_audit": {
                "present": False,
                "delivery_allowed": False,
                "blocks_operator_followthrough": False,
                "issue_codes": [],
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(run_receipt_path, {"notification_status": "deferred", "item_count": 0})

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-07-01T12:01:00Z",
    )

    assert receipt["status"] == "blocked_operator_runtime_posture"
    assert receipt["next_action"] == "verify_postgres_observation_source"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/admin/goals"
    assert receipt["next_action_label"] == "Open goals"
    assert receipt["next_action_method"] == "get"
    operator_runtime = receipt["proofs"]["operator_runtime_posture"]
    assert operator_runtime["present"] is False
    assert operator_runtime["source_coverage_ready"] is False
    assert operator_runtime["source_coverage_missing_lane_keys"] == ["postgres_observations"]
    assert operator_runtime["next_action_href"] == "https://myexternalbrain.com/admin/goals"


def test_materialize_proactive_ooda_gold_acceptance_allows_unchecked_source_coverage_during_approval_followthrough(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "reason": "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant",
            "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
            "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
            "next_action_label": "Record packet verdict",
            "next_action_method": "get",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "approval_capture_pending",
                "runtime_delivery_state": "no_actionable_items",
                "user_action_required": True,
                "manual_outcome_capture_ready": True,
                "current_packet_live_pending_count": 1,
            },
            "source_coverage": {
                "checked": False,
                "probe_ok": False,
                "status": "not_checked",
                "lane_count": 8,
                "observed_lane_count": 0,
                "missing_lane_keys": ["postgres_observations", "google_workspace"],
                "lanes": [
                    {
                        "key": "postgres_observations",
                        "observed": False,
                        "next_action": "verify_postgres_observation_source",
                        "missing_required_event_types": [],
                    },
                    {
                        "key": "google_workspace",
                        "observed": False,
                        "next_action": "reauthorize_or_sync_google_workspace_sources",
                        "missing_required_event_types": [],
                    },
                ],
            },
        },
    )
    digest_path = tmp_path / ".codex-studio/published/ea_operator_action_required_digest.generated.json"
    monkeypatch.setattr(module, "DEFAULT_OPERATOR_ACTION_REQUIRED_DIGEST", digest_path)
    _write_json(
        digest_path,
        {
            "status": "sent",
            "notification_status": "sent",
            "notification_item_count": 1,
            "notification_action_keys": ["proactive_ooda_packet_acceptance"],
            "send_attempted": True,
            "send_requested": True,
            "quiet_hours_respected": True,
            "telegram_push_allowed": True,
            "send_result": {"sent": True, "message_count": 1},
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "action_required_only_quiet_receipt_path": (
                "/data/provider-ledger/proactive_ooda_run_receipts/20260629T090000-deferred-quiet.json"
            ),
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "approval_outcome": {
                "schema": "ea.proactive_ooda_approval_outcome.v1",
                "approval_outcome_recorded": True,
                "accepted": True,
                "outcome": "approved",
                "status": "accepted_redacted",
                "source_kind": "operator_manual",
                "recorded_at": "2026-06-25T18:50:00Z",
                "evidence_sha256": _sha256("Approved for an older packet."),
                "actor_sha256": _sha256("operator-admin-1"),
                "packet_ref_sha256": _sha256("stage_packet:older-pkt"),
                "staged_artifact_sha256": _sha256("safe_work_result:older-res"),
            },
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-live")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-live")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 4,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_approval_surfaces": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "action_required_only_quiet_receipt": {
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "dry_run": False,
                "item_count": 2,
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-live",
                "stage": {"kind": "research_packet"},
                "approval": {"required": True},
                "safe_work_order": {
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    }
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Live Source", "url": "https://example.test/live"},
                },
                "shortlist": [{"label": "Live Source"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-06-26T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["status"] == "ready_for_approval_outcome_capture"
    assert receipt["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/admin/proactive-ooda/approval"
    operator_runtime = receipt["proofs"]["operator_runtime_posture"]
    assert operator_runtime["present"] is True
    assert operator_runtime["source_coverage_ready"] is True
    assert operator_runtime["source_coverage_checked"] is False
    assert operator_runtime["source_coverage_status"] == "not_checked"
    assert operator_runtime["source_coverage_followthrough_soft_override"] is True
    assert operator_runtime["source_coverage_missing_lane_keys"] == ["postgres_observations", "google_workspace"]


def test_materialize_proactive_ooda_gold_acceptance_blocks_when_suppressed_projection_needs_repair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_recovery_action",
            "reason": "suppressed_safe_work_projection",
            "next_action": "repair_proactive_safe_work_audit",
            "generated_at": "2026-06-30T08:11:00Z",
            "source_git_head": "source-head-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "source_coverage": {
                "checked": True,
                "status": "ready",
                "lane_count": 1,
                "observed_lane_count": 1,
                "missing_lane_keys": [],
                "lanes": [{"key": "postgres_observations", "observed": True, "missing_required_event_types": []}],
            },
            "context_grounding": {
                "grounded": True,
                "item_count": 0,
                "grounded_item_count": 0,
                "ungrounded_item_count": 0,
                "applied_context_count": 0,
                "recipient_location_count": 0,
            },
            "safe_work_audit": {
                "present": False,
                "delivery_allowed": False,
                "blocks_operator_followthrough": False,
                "issue_codes": [],
            },
            "suppressed_projection": {
                "present": True,
                "status": "suppressed",
                "requires_recovery": True,
                "blocking_reason": "suppressed_safe_work_projection",
                "next_action": "repair_proactive_safe_work_audit",
                "suppressed_item_count": 2,
                "suppressed_safe_work_review_count": 2,
                "suppressed_projection_reasons": ["safe_work_audit_review"],
                "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                "teable_status": "synced",
                "projection_record_count": 1,
                "packet_projection_record_count": 0,
                "inferred_from_packet_projection_gap": False,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(run_receipt_path, {"notification_status": "deferred", "item_count": 2})

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-06-30T08:12:00Z",
    )

    assert receipt["status"] == "blocked_operator_runtime_posture"
    assert receipt["next_action"] == "repair_proactive_safe_work_audit"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/app/queue"
    operator_runtime = receipt["proofs"]["operator_runtime_posture"]
    assert operator_runtime["present"] is False
    assert operator_runtime["suppressed_projection_ready"] is False
    assert operator_runtime["suppressed_projection_requires_recovery"] is True
    assert operator_runtime["suppressed_projection_item_count"] == 2
    assert operator_runtime["suppressed_projection_issue_codes"] == ["no_decision_ready_material"]
    assert "healthy operator runtime posture across approved proactive sources" in receipt["remaining_external_proofs"]


def test_materialize_proactive_ooda_gold_acceptance_falls_back_to_live_runtime_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
        },
    )
    digest_path = tmp_path / ".codex-studio/published/ea_operator_action_required_digest.generated.json"
    monkeypatch.setattr(module, "DEFAULT_OPERATOR_ACTION_REQUIRED_DIGEST", digest_path)
    _write_json(
        digest_path,
        {
            "status": "sent",
            "notification_status": "sent",
            "notification_item_count": 1,
            "notification_action_keys": ["proactive_ooda_packet_acceptance"],
            "send_attempted": True,
            "send_requested": True,
            "quiet_hours_respected": True,
            "telegram_push_allowed": True,
            "send_result": {"sent": True, "message_count": 1},
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "action_required_only_quiet_receipt_path": (
                "/data/provider-ledger/proactive_ooda_run_receipts/20260629T090000-deferred-quiet.json"
            ),
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "approval_outcome": {
                "schema": "ea.proactive_ooda_approval_outcome.v1",
                "approval_outcome_recorded": True,
                "accepted": True,
                "outcome": "approved",
                "status": "accepted_redacted",
                "source_kind": "operator_manual",
                "recorded_at": "2026-06-25T18:50:00Z",
                "evidence_sha256": _sha256("Approved for an older packet."),
                "actor_sha256": _sha256("operator-admin-1"),
                "packet_ref_sha256": _sha256("stage_packet:older-pkt"),
                "staged_artifact_sha256": _sha256("safe_work_result:older-res"),
            },
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-live")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-live")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 4,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_approval_surfaces": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "action_required_only_quiet_receipt": {
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "dry_run": False,
                "item_count": 2,
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-live",
                "stage": {"kind": "research_packet"},
                "approval": {"required": True},
                "safe_work_order": {
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    }
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Live Source", "url": "https://example.test/live"},
                },
                "shortlist": [{"label": "Live Source"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-06-26T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["status"] == "ready_for_approval_outcome_capture"
    assert receipt["proofs"]["live_browse_evidence"]["present"] is True
    assert receipt["proofs"]["chosen_candidate"]["present"] is True
    assert receipt["proofs"]["staged_reversible_artifact"]["present"] is True
    assert receipt["proofs"]["teable_projection"]["present"] is True
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is True
    assert receipt["proofs"]["action_required_only_delivery"]["quiet_receipt_proves_action_required_only"] is True
    assert receipt["proofs"]["action_required_only_delivery"]["quiet_receipt_path"].endswith("deferred-quiet.json")
    assert receipt["proofs"]["approval_followthrough_notification"]["present"] is True
    assert receipt["proofs"]["approval_followthrough_notification"]["approval_followthrough_prompt_sent"] is True
    assert receipt["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/admin/proactive-ooda/approval"
    assert receipt["next_action_label"] == "Record packet verdict"
    assert receipt["next_action_method"] == "get"
    assert receipt["summary"] == (
        "A proactive OODA packet has local gold-proof runtime evidence, the approval-needed Telegram prompt has been sent, "
        "and a live Telegram approval capture surface is ready; the latest stored approval artifact belongs to an older "
        "packet, so capture the current redacted approval outcome next."
    )
    assert receipt["proofs"]["approval_outcome"]["status"] == "stale_for_current_packet"
    assert receipt["proofs"]["approval_outcome"]["stale_for_current_packet"] is True
    assert receipt["evidence_receipts"]["approval_capture_surface"]["ready"] is True
    assert receipt["evidence_receipts"]["approval_capture_surface"]["callback_record_count"] == 1
    assert receipt["evidence_receipts"]["approval_capture_surface"]["current_packet_callback_record_count"] == 1
    assert receipt["evidence_receipts"]["approval_capture_surface"]["current_packet_live_pending_count"] == 1
    assert receipt["proofs"]["approval_capture_readiness"]["present"] is True
    assert receipt["evidence_receipts"]["approval_capture"]["principal_match_ready"] is True
    assert receipt["evidence_receipts"]["operator_action_required_digest"]["approval_followthrough_prompt_sent"] is True
    assert receipt["evidence_receipts"]["approval_outcome"]["status"] == "stale_for_current_packet"
    assert receipt["evidence_receipts"]["approval_outcome"]["artifact_status"] == "accepted_redacted"
    assert receipt["evidence_receipts"]["approval_outcome"]["stale_for_current_packet"] is True
    assert receipt["evidence_receipts"]["run_receipt"]["source"] == "docker_compose_exec"
    assert receipt["evidence_receipts"]["stage_packet"]["path"] == "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json"


def test_materialize_proactive_ooda_gold_acceptance_accepts_manual_approval_capture_without_live_callback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "approval_capture": {
                "checked": False,
                "probe_ok": False,
                "ready": False,
                "status": "not_checked",
                "privacy": {
                    "raw_callback_token_exposed": False,
                    "raw_principal_id_exposed": False,
                    "raw_chat_ref_exposed": False,
                    "raw_packet_ref_exposed": False,
                    "raw_staged_artifact_ref_exposed": False,
                },
            },
            "approval_capture_surface": {
                "present": True,
                "ready": True,
                "mode": "manual_outcome_capture_ready",
                "selected_channel": "telegram",
                "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "callback_dir_exists": True,
                "callback_dir_writable": True,
                "current_packet_present": True,
                "current_packet_status": "staged",
                "current_packet_approval_request_recordable": True,
                "approval_outcome_matches_current_packet": False,
                "telegram_approval_surface_ready": False,
                "manual_outcome_capture_ready": True,
                "current_packet_live_pending_count": 0,
                "source": "docker_compose_exec",
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/manual.json",
            "action_required_only_quiet_receipt_path": (
                "/data/provider-ledger/proactive_ooda_run_receipts/20260629T090000-deferred-quiet.json"
            ),
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 27,
            "approval_callback_pending_count": 0,
            "approval_callback_live_pending_count": 0,
            "approval_callback_recorded_count": 6,
            "current_packet_callback_record_count": 0,
            "current_packet_callback_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "",
            "current_packet_callback_latest_expired": False,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-manual.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-manual.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-manual")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-manual")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 3,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "action_required_only_quiet_receipt": {
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "dry_run": False,
                "item_count": 2,
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-manual",
                "stage": {"kind": "research_packet"},
                "approval": {"required": True},
                "safe_work_order": {
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    }
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-manual",
                "status": "staged_for_user_decision",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Manual Source", "url": "https://example.test/manual"},
                },
                "shortlist": [{"label": "Manual Source"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/manual", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-06-30T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["next_action"] == "repair_proactive_approval_capture"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/admin/goals"
    assert receipt["next_action_label"] == "Open goals"
    assert receipt["next_action_method"] == "get"
    assert receipt["summary"] == "Proactive OODA gold proof is still blocked because one or more packet-evidence links are missing."
    assert receipt["proofs"]["teable_projection"]["present"] is True
    assert receipt["proofs"]["teable_projection"]["approval_capture_surface_ready"] is False
    assert receipt["proofs"]["teable_projection"]["approval_capture_telegram_surface_ready"] is False
    assert receipt["proofs"]["teable_projection"]["approval_capture_manual_outcome_capture_ready"] is True
    surface = receipt["evidence_receipts"]["approval_capture_surface"]
    assert surface["ready"] is False
    assert surface["mode"] == "manual_outcome_capture_ready"
    assert surface["telegram_approval_surface_ready"] is False
    assert surface["manual_outcome_capture_ready"] is True
    assert surface["current_packet_approval_request_recordable"] is True
    assert surface["current_packet_matches_packet_artifacts"] is False
    assert surface["current_packet_live_pending_count"] == 0
    proof = receipt["proofs"]["approval_capture_readiness"]
    assert proof["present"] is True
    assert proof["ready"] is False
    assert proof["manual_capture_present"] is False
    assert proof["manual_outcome_capture_ready"] is False
    assert proof["telegram_approval_surface_ready"] is False
    assert receipt["remaining_external_proofs"] == [
        "redacted approval-capture readiness for the proactive OODA packet",
        "redacted explicit approval outcome for the proactive OODA packet",
    ]


def test_materialize_proactive_ooda_gold_acceptance_falls_back_to_recording_outcome_when_capture_surface_is_not_live_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    approval_outcome_path = tmp_path / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "approval_capture": {
                "checked": False,
                "probe_ok": False,
                "ready": False,
                "status": "not_checked",
                "privacy": {
                    "raw_callback_token_exposed": False,
                    "raw_principal_id_exposed": False,
                    "raw_chat_ref_exposed": False,
                    "raw_packet_ref_exposed": False,
                    "raw_staged_artifact_ref_exposed": False,
                },
            },
        },
    )
    _write_json(
        approval_outcome_path,
        {
            "schema": "ea.proactive_ooda_approval_outcome.v1",
            "contract_name": "ea.proactive_ooda_approval_outcome.v1",
            "approval_outcome_recorded": True,
            "accepted": True,
            "outcome": "approved",
            "status": "accepted_redacted",
            "source_kind": "operator_manual",
            "recorded_at": "2026-07-02T15:20:09Z",
            "evidence_sha256": _sha256("Approved after the previous packet review."),
            "actor_sha256": _sha256("operator-admin-1"),
            "packet_ref_sha256": _sha256("stage_packet:older-pkt"),
            "staged_artifact_sha256": _sha256("safe_work_result:older-res"),
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
            "action_required_only_quiet_receipt_path": (
                "/data/provider-ledger/proactive_ooda_run_receipts/20260706T091000-deferred-quiet.json"
            ),
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": str(approval_outcome_path),
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 0,
            "approval_callback_pending_count": 0,
            "approval_callback_live_pending_count": 0,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 0,
            "current_packet_callback_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "",
            "current_packet_callback_latest_expired": False,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-live")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-live")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 3,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "action_required_only_quiet_receipt": {
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "dry_run": False,
                "item_count": 2,
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-live",
                "stage": {"kind": "decision_packet"},
                "approval": {"required": True},
                "safe_work_order": {
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    }
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Live Source", "url": "https://example.test/live"},
                },
                "shortlist": [{"label": "Live Source"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        approval_outcome_path=approval_outcome_path,
        generated_at="2026-07-06T09:50:55Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["next_action"] == "repair_proactive_approval_capture"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/admin/goals"
    assert receipt["next_action_label"] == "Open goals"
    assert receipt["next_action_method"] == "get"
    assert receipt["summary"] == "Proactive OODA gold proof is still blocked because one or more packet-evidence links are missing."
    assert receipt["proofs"]["approval_outcome"]["status"] == "stale_for_current_packet"
    assert receipt["proofs"]["approval_outcome"]["stale_for_current_packet"] is True
    assert receipt["proofs"]["approval_capture_readiness"]["present"] is True
    assert receipt["proofs"]["approval_capture_readiness"]["ready"] is False
    assert receipt["proofs"]["approval_capture_readiness"]["checked"] is False
    assert receipt["remaining_external_proofs"] == [
        "redacted approval-capture readiness for the proactive OODA packet",
        "redacted explicit approval outcome for the proactive OODA packet",
    ]


def test_materialize_proactive_ooda_gold_acceptance_keeps_approval_followthrough_sent_under_digest_dedupe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "generated_at": "2026-06-26T18:49:00Z",
            "source_git_head": "source-head-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "approval_capture": {
                "checked": True,
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "source": "docker_compose_exec:proactive_approval_capture",
                "observed_at": "2026-06-26T18:49:30Z",
                "current_packet_refs_present": True,
                "current_packet_ref_sha256": _sha256("stage_packet:pkt-live"),
                "current_staged_artifact_ref_sha256": _sha256("safe_work_result:res-live"),
                "current_packet_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "principal_match_ready": True,
                "candidate_principal_hash_count": 1,
                "callback_principal_hash_present": True,
                "telegram_binding_ready": True,
                "telegram_bot_token_present": True,
                "telegram_chat_ref_present": True,
                "telegram_chat_ref_sha256": _sha256("telegram-chat-ref"),
            },
        },
    )
    digest_path = tmp_path / ".codex-studio/published/ea_operator_action_required_digest.generated.json"
    dedupe_path = tmp_path / ".codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json"
    monkeypatch.setattr(module, "DEFAULT_OPERATOR_ACTION_REQUIRED_DIGEST", digest_path)
    monkeypatch.setattr(module, "DEFAULT_OPERATOR_ACTION_REQUIRED_DEDUPE_PROOF", dedupe_path)
    _write_json(
        digest_path,
        {
            "status": "suppressed_duplicate",
            "notification_status": "suppressed_duplicate",
            "included_action_keys": ["proactive_ooda_packet_acceptance"],
            "notification_action_keys": [],
            "notification_item_count": 0,
            "send_attempted": False,
            "send_requested": True,
            "quiet_hours_respected": True,
            "telegram_push_allowed": True,
            "send_result": {"sent": False, "message_count": 0},
        },
    )
    _write_json(
        dedupe_path,
        {
            "contract_name": "ea.operator_action_required_dedupe_proof.v1",
            "status": "pass",
            "suppressed_duplicate_expected": True,
            "current_actions_covered_by_prior_state": True,
            "notification_mode_without_force": "covered_by_previous_send",
            "included_action_keys": ["proactive_ooda_packet_acceptance"],
            "state": {
                "message_id_count": 1,
            },
            "source_receipts": {
                "sent_digest": {
                    "status": "suppressed_duplicate",
                    "notification_status": "suppressed_duplicate",
                    "message_count": 0,
                }
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "action_required_only_quiet_receipt_path": (
                "/data/provider-ledger/proactive_ooda_run_receipts/20260629T090000-deferred-quiet.json"
            ),
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "approval_outcome": {
                "schema": "ea.proactive_ooda_approval_outcome.v1",
                "approval_outcome_recorded": True,
                "accepted": True,
                "outcome": "approved",
                "status": "accepted_redacted",
                "source_kind": "operator_manual",
                "recorded_at": "2026-06-25T18:50:00Z",
                "evidence_sha256": _sha256("Approved for an older packet."),
                "actor_sha256": _sha256("operator-admin-1"),
                "packet_ref_sha256": _sha256("stage_packet:older-pkt"),
                "staged_artifact_sha256": _sha256("safe_work_result:older-res"),
            },
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-live")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-live")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 4,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_approval_surfaces": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "action_required_only_quiet_receipt": {
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "dry_run": False,
                "item_count": 2,
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-live",
                "stage": {"kind": "research_packet"},
                "approval": {"required": True},
                "safe_work_order": {
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    }
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Live Source", "url": "https://example.test/live"},
                },
                "shortlist": [{"label": "Live Source"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-06-26T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["status"] == "ready_for_approval_outcome_capture"
    proof = receipt["proofs"]["approval_followthrough_notification"]
    assert proof["present"] is True
    assert proof["approval_followthrough_prompt_sent"] is True
    assert proof["approval_followthrough_prompt_covered_by_prior_send"] is True
    assert proof["notification_status"] == "suppressed_duplicate"
    assert proof["dedupe_proof_status"] == "pass"
    assert proof["current_actions_covered_by_prior_state"] is True
    assert proof["dedupe_state_message_id_count"] == 1
    assert receipt["summary"] == (
        "A proactive OODA packet has local gold-proof runtime evidence, the approval-needed Telegram prompt has been sent, "
        "and a live Telegram approval capture surface is ready; the latest stored approval artifact belongs to an older "
        "packet, so capture the current redacted approval outcome next."
    )
    assert receipt["evidence_receipts"]["operator_action_required_digest"]["approval_followthrough_prompt_sent"] is True
    assert receipt["evidence_receipts"]["operator_action_required_digest"]["approval_followthrough_prompt_covered_by_prior_send"] is True
    assert receipt["evidence_receipts"]["operator_action_required_dedupe_proof"]["status"] == "pass"


def test_materialize_proactive_ooda_gold_acceptance_blocks_internal_action_packet_even_with_delivery_and_capture_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})
    monkeypatch.setattr(module, "_live_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/internal-action.json",
            "action_required_only_quiet_receipt_path": (
                "/data/provider-ledger/proactive_ooda_run_receipts/20260704T090000-deferred-quiet.json"
            ),
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 17,
            "approval_callback_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 11,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_stale_pending_count": 0,
            "current_packet_callback_expired_count": 0,
            "current_packet_callback_expired_pending_count": 0,
            "current_packet_callback_superseded_count": 0,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-internal.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-internal.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-internal")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-internal")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 4,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_approval_surfaces": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "action_required_only_quiet_receipt": {
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "dry_run": False,
                "item_count": 2,
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-internal",
                "stage": {
                    "kind": "internal_action",
                    "summary": "Retry Google auth.",
                    "payload": {"work_type": "record_internal_action"},
                },
                "approval": {"required": True},
                "safe_work_order": {
                    "work_type": "record_internal_action",
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    },
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-internal",
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "recommended_option_or_draft": {
                    "kind": "internal_action",
                    "value": {"label": "Retry Google auth", "url": "https://myexternalbrain.com/integrations/google"},
                },
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 0,
                    "network_fetch_success_count": 0,
                    "page_checks": [],
                    "irreversible_actions_attempted": [],
                    "research_search_plan": {"mode": "internal_action", "policy": "internal_action_surface"},
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-07-04T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["status"] == "blocked_low_quality_packet_evidence"
    assert receipt["next_action"] == "stage_fresh_assistant_grade_proactive_packet"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["evidence_receipts"]["approval_capture_surface"]["current_packet_live_pending_count"] == 1
    assert receipt["evidence_receipts"]["approval_capture_surface"]["current_packet_callback_pending_count"] == 1
    assert receipt["proofs"]["assistant_grade_packet_quality"]["present"] is False
    assert "internal_action_not_assistant_grade" in receipt["proofs"]["assistant_grade_packet_quality"]["issues"]
    assert "assistant-grade source intent and candidate alignment for the proactive OODA packet" in receipt["remaining_external_proofs"]


def test_materialize_proactive_ooda_gold_acceptance_falls_back_to_historical_browse_backed_proof_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "approval_capture": {
                "checked": True,
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "source": "docker_compose_exec",
                "principal_match_ready": True,
                "telegram_binding_ready": True,
                "telegram_chat_ref_present": True,
                "telegram_bot_token_present": True,
                "privacy": {
                    "raw_callback_token_exposed": False,
                    "raw_principal_id_exposed": False,
                    "raw_chat_ref_exposed": False,
                    "raw_packet_ref_exposed": False,
                    "raw_staged_artifact_ref_exposed": False,
                },
            },
            "approval_capture_surface": {
                "present": True,
                "ready": True,
                "mode": "telegram_approval_surface_ready",
                "selected_channel": "telegram",
                "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "callback_dir_exists": True,
                "callback_dir_writable": True,
                "current_packet_present": True,
                "current_packet_status": "staged",
                "current_packet_approval_request_recordable": True,
                "approval_outcome_matches_current_packet": False,
                "telegram_approval_surface_ready": True,
                "manual_outcome_capture_ready": False,
                "current_packet_live_pending_count": 1,
                "source": "docker_compose_exec",
            },
        },
    )

    def _artifact_probe(**kwargs):
        if kwargs.get("prefer_browse_backed_delivery"):
            return {
                "probe_ok": True,
                "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
                "action_required_only_quiet_receipt_path": (
                    "/data/provider-ledger/proactive_ooda_run_receipts/20260629T090000-deferred-quiet.json"
                ),
                "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
                "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
                "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "approval_callback_dir_exists": True,
                "approval_callback_dir_writable": True,
                "approval_callback_record_count": 1,
                "approval_callback_pending_count": 1,
                "approval_callback_live_pending_count": 1,
                "approval_callback_recorded_count": 0,
                "current_packet_callback_record_count": 1,
                "current_packet_callback_pending_count": 1,
                "current_packet_callback_recorded_count": 0,
                "current_packet_live_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "current_packet_callback_latest_expired": False,
                "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
                "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
                "run_receipt": {
                    "notification_status": "sent",
                    "item_count": 1,
                    "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-live")],
                    "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-live")],
                    "teable_sync": {
                        "status": "synced",
                        "sync_attempted": True,
                        "projection_summary": {
                            "record_count": 4,
                            "tables": {
                                "proactive_ooda_runs": {"record_count": 1},
                                "proactive_ooda_safe_work": {"record_count": 1},
                                "proactive_ooda_items": {"record_count": 1},
                                "proactive_ooda_approval_surfaces": {"record_count": 1},
                            },
                        },
                        "missing_tables": [],
                    },
                },
                "action_required_only_quiet_receipt": {
                    "notification_status": "deferred",
                    "error_code": "no_user_action_required",
                    "dry_run": False,
                    "item_count": 2,
                    "telegram_message_ids": [],
                    "delivery_message_ids": [],
                },
                "stage_packet": {
                    "schema": "proactive_ooda.stage_packet.v1",
                    "packet_ref": "stage_packet:pkt-live",
                    "stage": {"kind": "research_packet", "payload": {"work_type": "compare_options"}},
                    "approval": {"required": True},
                    "safe_work_order": {
                        "handoff_policy": {
                            "safe_to_execute_before_approval": True,
                            "external_actions_remain_staged_only": True,
                        },
                        "work_type": "compare_options",
                    },
                },
                "safe_work_result": {
                    "schema": "proactive_ooda.safe_work_result.v1",
                    "result_ref": "safe_work_result:res-live",
                    "status": "staged_for_user_decision",
                    "recommended_option_or_draft": {
                        "kind": "shortlist_candidate",
                        "value": {"label": "Live Source", "url": "https://example.test/live"},
                    },
                    "shortlist": [{"label": "Live Source"}],
                    "approval": {"required": True},
                    "work_type": "compare_options",
                    "audit": {"status": "pass", "issues": []},
                    "execution_receipt": {
                        "network_fetch_count": 1,
                        "network_fetch_success_count": 1,
                        "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                        "irreversible_actions_attempted": [],
                    },
                },
            }
        return {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/internal-action.json",
            "action_required_only_quiet_receipt_path": (
                "/data/provider-ledger/proactive_ooda_run_receipts/20260704T090000-deferred-quiet.json"
            ),
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 17,
            "approval_callback_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 11,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_stale_pending_count": 0,
            "current_packet_callback_expired_count": 0,
            "current_packet_callback_expired_pending_count": 0,
            "current_packet_callback_superseded_count": 0,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-internal.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-internal.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-internal")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-internal")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 4,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_approval_surfaces": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "action_required_only_quiet_receipt": {
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "dry_run": False,
                "item_count": 2,
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-internal",
                "stage": {
                    "kind": "internal_action",
                    "summary": "Retry Google auth.",
                    "payload": {"work_type": "record_internal_action"},
                },
                "approval": {"required": True},
                "safe_work_order": {
                    "work_type": "record_internal_action",
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    },
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-internal",
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "recommended_option_or_draft": {
                    "kind": "internal_action",
                    "value": {"label": "Retry Google auth", "url": "https://myexternalbrain.com/integrations/google"},
                },
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 0,
                    "network_fetch_success_count": 0,
                    "page_checks": [],
                    "irreversible_actions_attempted": [],
                    "research_search_plan": {"mode": "internal_action", "policy": "internal_action_surface"},
                },
            },
        }

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_artifacts", _artifact_probe)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-07-04T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["selected_bundle_source"] == "historical_browse_backed_proof_bundle"
    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["next_action"] == "stage_fresh_assistant_grade_proactive_packet"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/app/queue"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["proofs"]["assistant_grade_packet_quality"]["present"] is True
    assert receipt["proofs"]["live_browse_evidence"]["present"] is True
    assert receipt["proofs"]["chosen_candidate"]["present"] is True
    assert receipt["proofs"]["staged_reversible_artifact"]["present"] is True
    assert receipt["proofs"]["teable_projection"]["present"] is True
    assert receipt["proofs"]["approval_capture_readiness"]["present"] is False
    assert "fresh assistant-grade proactive OODA packet acceptance evidence" in receipt["remaining_external_proofs"]
    assert "current recordable proactive OODA packet acceptance evidence" not in receipt["remaining_external_proofs"]
    assert "assistant-grade source intent and candidate alignment for the proactive OODA packet" not in receipt["remaining_external_proofs"]


def test_materialize_proactive_ooda_gold_acceptance_uses_current_callback_hygiene_when_selected_bundle_is_historical(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "source_git_head": "source-head-123",
            "source_state_fingerprint": "source-fingerprint-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "approval_capture_surface": {
                "present": True,
                "ready": False,
                "selected_channel": "telegram",
                "callback_hygiene_ready": True,
                "callback_hygiene_blocking_reason": "",
                "callback_hygiene_next_action": "",
                "callback_noncurrent_pending_count": 0,
                "callback_stale_pending_count": 0,
                "callback_expired_pending_count": 0,
                "current_packet_callback_stale_pending_count": 0,
                "current_packet_duplicate_live_pending_count": 0,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_pending_count": 1,
                "current_packet_callback_record_count": 1,
                "current_packet_callback_latest_status": "pending",
                "current_packet_callback_latest_expired": False,
            },
        },
    )

    current_internal_bundle = {
        "run_receipt_path": Path("/data/provider-ledger/proactive_ooda_run_receipts/internal-action.json"),
        "action_required_only_quiet_receipt_path": Path(
            "/data/provider-ledger/proactive_ooda_run_receipts/20260704T090000-deferred-quiet.json"
        ),
        "stage_packet_dir": Path("/data/provider-ledger/proactive_ooda_stage_packets"),
        "safe_work_result_dir": Path("/data/provider-ledger/proactive_ooda_safe_work_results"),
        "approval_outcome_path": Path("/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json"),
        "approval_callback_dir": Path("/data/provider-ledger/proactive_ooda_approval_callbacks"),
        "approval_callback_dir_exists": True,
        "approval_callback_dir_writable": True,
        "approval_callback_record_count": 17,
        "approval_callback_pending_count": 1,
        "approval_callback_live_pending_count": 1,
        "approval_callback_noncurrent_pending_count": 0,
        "approval_callback_stale_pending_count": 0,
        "approval_callback_expired_pending_count": 0,
        "approval_callback_recorded_count": 0,
        "approval_callback_expired_count": 0,
        "approval_callback_superseded_count": 11,
        "current_packet_callback_record_count": 1,
        "current_packet_callback_pending_count": 1,
        "current_packet_callback_recorded_count": 0,
        "current_packet_live_callback_record_count": 1,
        "current_packet_live_pending_count": 1,
        "current_packet_callback_stale_pending_count": 0,
        "current_packet_callback_expired_count": 0,
        "current_packet_callback_expired_pending_count": 0,
        "current_packet_callback_superseded_count": 0,
        "current_packet_callback_latest_status": "pending",
        "current_packet_callback_latest_expired": False,
        "run_receipt": {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-internal")],
            "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-internal")],
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "projection_summary": {
                    "record_count": 4,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                        "proactive_ooda_approval_surfaces": {"record_count": 1},
                    },
                },
                "missing_tables": [],
            },
        },
        "action_required_only_quiet_receipt": {
            "notification_status": "deferred",
            "error_code": "no_user_action_required",
            "dry_run": False,
            "item_count": 2,
            "telegram_message_ids": [],
            "delivery_message_ids": [],
        },
        "stage_packet_path": Path("/data/provider-ledger/proactive_ooda_stage_packets/pkt-internal.json"),
        "safe_work_result_path": Path("/data/provider-ledger/proactive_ooda_safe_work_results/res-internal.json"),
        "stage_packet": {
            "schema": "proactive_ooda.stage_packet.v1",
            "packet_ref": "stage_packet:pkt-internal",
            "stage": {"kind": "internal_action", "payload": {"work_type": "record_internal_action"}},
            "approval": {"required": True},
            "safe_work_order": {
                "work_type": "record_internal_action",
                "handoff_policy": {
                    "safe_to_execute_before_approval": True,
                    "external_actions_remain_staged_only": True,
                },
            },
        },
        "safe_work_result": {
            "schema": "proactive_ooda.safe_work_result.v1",
            "result_ref": "safe_work_result:res-internal",
            "status": "staged_for_user_decision",
            "work_type": "record_internal_action",
            "recommended_option_or_draft": {
                "kind": "internal_action",
                "value": {"label": "Retry Google auth", "url": "https://myexternalbrain.com/integrations/google"},
            },
            "approval": {"required": True},
            "audit": {"status": "pass", "issues": []},
            "execution_receipt": {
                "network_fetch_count": 0,
                "network_fetch_success_count": 0,
                "page_checks": [],
                "irreversible_actions_attempted": [],
                "research_search_plan": {"mode": "internal_action", "policy": "internal_action_surface"},
            },
        },
    }

    historical_browse_bundle = {
        "selection_source": "historical_browse_backed_proof_bundle",
        "run_receipt_path": Path("/data/provider-ledger/proactive_ooda_run_receipts/assistant-grade.json"),
        "stage_packet_path": Path("/data/provider-ledger/proactive_ooda_stage_packets/pkt-good.json"),
        "safe_work_result_path": Path("/data/provider-ledger/proactive_ooda_safe_work_results/res-good.json"),
        "run_receipt": {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-good")],
            "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-good")],
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "projection_summary": {
                    "record_count": 4,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                        "proactive_ooda_approval_surfaces": {"record_count": 1},
                    },
                },
                "missing_tables": [],
            },
        },
        "approval_callback_noncurrent_pending_count": 1,
        "approval_callback_stale_pending_count": 1,
        "approval_callback_pending_count": 1,
        "approval_callback_raw_pending_count": 1,
        "approval_callback_live_pending_count": 0,
        "approval_callback_unexpired_pending_count": 1,
        "approval_callback_record_count": 17,
        "approval_callback_recorded_count": 0,
        "approval_callback_superseded_count": 11,
        "current_packet_callback_record_count": 0,
        "current_packet_callback_pending_count": 0,
        "current_packet_callback_raw_pending_count": 0,
        "current_packet_live_callback_record_count": 0,
        "current_packet_live_pending_count": 0,
        "current_packet_callback_latest_status": "",
        "current_packet_callback_latest_expired": False,
        "stage_packet": {
            "schema": "proactive_ooda.stage_packet.v1",
            "packet_ref": "stage_packet:pkt-good",
            "stage": {"kind": "research_packet", "payload": {"work_type": "compare_options"}},
            "approval": {"required": True},
            "safe_work_order": {
                "work_type": "compare_options",
                "handoff_policy": {
                    "safe_to_execute_before_approval": True,
                    "external_actions_remain_staged_only": True,
                },
            },
        },
        "safe_work_result": {
            "schema": "proactive_ooda.safe_work_result.v1",
            "result_ref": "safe_work_result:res-good",
            "status": "staged_for_user_decision",
            "work_type": "compare_options",
            "recommended_option_or_draft": {
                "kind": "shortlist_candidate",
                "value": {"label": "Live Source", "url": "https://example.test/live"},
            },
            "shortlist": [{"label": "Live Source"}],
            "approval": {"required": True},
            "audit": {"status": "pass", "issues": []},
            "execution_receipt": {
                "network_fetch_count": 1,
                "network_fetch_success_count": 1,
                "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                "irreversible_actions_attempted": [],
            },
        },
    }

    def _runtime_artifact_bundle(**kwargs):
        return dict(current_internal_bundle), True

    monkeypatch.setattr(module, "_runtime_artifact_bundle", _runtime_artifact_bundle)
    monkeypatch.setattr(
        module,
        "_historical_assistant_grade_browse_bundle_from_runtime_paths",
        lambda **_kwargs: dict(historical_browse_bundle),
    )
    monkeypatch.setattr(module, "_live_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-07-04T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["selected_bundle_source"] == "historical_browse_backed_proof_bundle"
    assert receipt["next_action"] != "cleanup_proactive_approval_callbacks"
    assert receipt["proofs"]["operator_runtime_posture"]["approval_callback_hygiene_ready"] is True
    assert receipt["evidence_receipts"]["approval_capture_surface"]["callback_hygiene_ready"] is True
    assert receipt["evidence_receipts"]["approval_capture_surface"]["callback_hygiene_blocking_reason"] == ""


def test_live_historical_assistant_grade_browse_bundle_loader_accepts_runtime_payload(monkeypatch) -> None:
    module = _load_script()

    monkeypatch.setattr(
        module.ea_live_ops,
        "_docker_compose_exec_json",
        lambda **_kwargs: (
            0,
            {
                "ok": True,
                "selection_source": "historical_browse_backed_proof_bundle",
                "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/assistant-grade.json",
                "run_receipt": {
                    "notification_status": "sent",
                    "item_count": 1,
                    "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-good")],
                    "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-good")],
                },
                "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-good.json",
                "stage_packet": {
                    "schema": "proactive_ooda.stage_packet.v1",
                    "packet_ref": "stage_packet:pkt-good",
                    "stage": {"kind": "research_packet", "payload": {"work_type": "compare_options"}},
                },
                "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-good.json",
                "safe_work_result": {
                    "schema": "proactive_ooda.safe_work_result.v1",
                    "result_ref": "safe_work_result:res-good",
                    "work_type": "compare_options",
                    "audit": {"status": "pass", "issues": []},
                },
            },
            "",
            "",
        ),
    )

    bundle = module._live_historical_assistant_grade_browse_bundle_from_runtime_paths(  # noqa: SLF001
        run_receipt_path=Path("/data/provider-ledger/proactive_ooda_run_receipts/current.json"),
        stage_packet_dir=Path("/data/provider-ledger/proactive_ooda_stage_packets"),
        safe_work_result_dir=Path("/data/provider-ledger/proactive_ooda_safe_work_results"),
    )

    assert bundle["selection_source"] == "historical_browse_backed_proof_bundle"
    assert bundle["run_receipt_path"] == Path("/data/provider-ledger/proactive_ooda_run_receipts/assistant-grade.json")
    assert bundle["stage_packet_path"] == Path("/data/provider-ledger/proactive_ooda_stage_packets/pkt-good.json")
    assert bundle["safe_work_result_path"] == Path("/data/provider-ledger/proactive_ooda_safe_work_results/res-good.json")
    assert bundle["stage_packet"]["packet_ref"] == "stage_packet:pkt-good"
    assert bundle["safe_work_result"]["result_ref"] == "safe_work_result:res-good"


def test_materialize_proactive_ooda_gold_acceptance_uses_live_historical_assistant_grade_bundle_when_browse_probe_is_low_quality(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "approval_capture": {
                "checked": True,
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "source": "docker_compose_exec",
                "principal_match_ready": True,
                "telegram_binding_ready": True,
                "telegram_chat_ref_present": True,
                "telegram_bot_token_present": True,
                "privacy": {
                    "raw_callback_token_exposed": False,
                    "raw_principal_id_exposed": False,
                    "raw_chat_ref_exposed": False,
                    "raw_packet_ref_exposed": False,
                    "raw_staged_artifact_ref_exposed": False,
                },
            },
            "approval_capture_surface": {
                "present": True,
                "ready": True,
                "mode": "telegram_approval_surface_ready",
                "selected_channel": "telegram",
                "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "callback_dir_exists": True,
                "callback_dir_writable": True,
                "current_packet_present": True,
                "current_packet_status": "staged",
                "current_packet_approval_request_recordable": True,
                "approval_outcome_matches_current_packet": False,
                "telegram_approval_surface_ready": True,
                "manual_outcome_capture_ready": False,
                "current_packet_live_pending_count": 1,
                "source": "docker_compose_exec",
            },
        },
    )

    def _artifact_probe(**kwargs):
        if kwargs.get("prefer_browse_backed_delivery"):
            return {
                "probe_ok": True,
                "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/browse-low-quality.json",
                "action_required_only_quiet_receipt_path": (
                    "/data/provider-ledger/proactive_ooda_run_receipts/20260629T090000-deferred-quiet.json"
                ),
                "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
                "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
                "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "approval_callback_dir_exists": True,
                "approval_callback_dir_writable": True,
                "approval_callback_record_count": 1,
                "approval_callback_pending_count": 1,
                "approval_callback_live_pending_count": 1,
                "approval_callback_recorded_count": 0,
                "current_packet_callback_record_count": 1,
                "current_packet_callback_pending_count": 1,
                "current_packet_callback_recorded_count": 0,
                "current_packet_live_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "current_packet_callback_latest_expired": False,
                "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-browse-low-quality.json",
                "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-browse-low-quality.json",
                "run_receipt": {
                    "notification_status": "sent",
                    "item_count": 1,
                    "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-browse-low-quality")],
                    "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-browse-low-quality")],
                    "teable_sync": {
                        "status": "synced",
                        "sync_attempted": True,
                        "projection_summary": {
                            "record_count": 4,
                            "tables": {
                                "proactive_ooda_runs": {"record_count": 1},
                                "proactive_ooda_safe_work": {"record_count": 1},
                                "proactive_ooda_items": {"record_count": 1},
                                "proactive_ooda_approval_surfaces": {"record_count": 1},
                            },
                        },
                        "missing_tables": [],
                    },
                },
                "action_required_only_quiet_receipt": {
                    "notification_status": "deferred",
                    "error_code": "no_user_action_required",
                    "dry_run": False,
                    "item_count": 2,
                    "telegram_message_ids": [],
                    "delivery_message_ids": [],
                },
                "stage_packet": {
                    "schema": "proactive_ooda.stage_packet.v1",
                    "packet_ref": "stage_packet:pkt-browse-low-quality",
                    "stage": {
                        "kind": "research_packet",
                        "payload": {
                            "work_type": "compare_options",
                            "request": "translate ein einen einem",
                        },
                    },
                    "approval": {"required": True},
                    "safe_work_order": {
                        "work_type": "compare_options",
                        "handoff_policy": {
                            "safe_to_execute_before_approval": True,
                            "external_actions_remain_staged_only": True,
                        },
                    },
                    "adapter_hints": ["transcript_signal"],
                },
                "safe_work_result": {
                    "schema": "proactive_ooda.safe_work_result.v1",
                    "result_ref": "safe_work_result:res-browse-low-quality",
                    "status": "staged_for_user_decision",
                    "work_type": "compare_options",
                    "recommended_option_or_draft": {
                        "kind": "shortlist_candidate",
                        "value": {"label": "German grammar article", "url": "https://example.test/german-articles"},
                    },
                    "shortlist": [{"label": "German grammar article"}],
                    "approval": {"required": True},
                    "audit": {"status": "pass", "issues": []},
                    "execution_receipt": {
                        "network_fetch_count": 1,
                        "network_fetch_success_count": 1,
                        "page_checks": [{"url": "https://example.test/german-articles", "reachable": True}],
                        "irreversible_actions_attempted": [],
                    },
                },
            }
        return {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/internal-action.json",
            "action_required_only_quiet_receipt_path": (
                "/data/provider-ledger/proactive_ooda_run_receipts/20260704T090000-deferred-quiet.json"
            ),
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-internal.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-internal.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-internal")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-internal")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 4,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_approval_surfaces": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "action_required_only_quiet_receipt": {
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "dry_run": False,
                "item_count": 2,
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-internal",
                "stage": {"kind": "internal_action", "payload": {"work_type": "record_internal_action"}},
                "approval": {"required": True},
                "safe_work_order": {
                    "work_type": "record_internal_action",
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    },
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-internal",
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "recommended_option_or_draft": {
                    "kind": "internal_action",
                    "value": {"label": "Retry Google auth", "url": "https://myexternalbrain.com/integrations/google"},
                },
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 0,
                    "network_fetch_success_count": 0,
                    "page_checks": [],
                    "irreversible_actions_attempted": [],
                    "research_search_plan": {"mode": "internal_action", "policy": "internal_action_surface"},
                },
            },
        }

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_artifacts", _artifact_probe)
    monkeypatch.setattr(module, "_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})
    monkeypatch.setattr(
        module,
        "_live_historical_assistant_grade_browse_bundle_from_runtime_paths",
        lambda **_kwargs: {
            "run_receipt_path": Path("/data/provider-ledger/proactive_ooda_run_receipts/assistant-grade.json"),
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-good")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-good")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 4,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_approval_surfaces": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "stage_packet_path": Path("/data/provider-ledger/proactive_ooda_stage_packets/pkt-good.json"),
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-good",
                "stage": {
                    "kind": "research_packet",
                    "payload": {"work_type": "compare_options", "request": "search me under wall options"},
                },
                "approval": {"required": True},
                "safe_work_order": {
                    "work_type": "compare_options",
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    },
                },
                "adapter_hints": ["transcript_signal"],
            },
            "safe_work_result_path": Path("/data/provider-ledger/proactive_ooda_safe_work_results/res-good.json"),
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-good",
                "status": "staged_for_user_decision",
                "work_type": "compare_options",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Atom VoiceS3R", "url": "https://docs.m5stack.com/en/core/Atom_EchoS3R"},
                },
                "shortlist": [{"label": "Atom VoiceS3R"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 6,
                    "network_fetch_success_count": 6,
                    "page_checks": [{"url": "https://docs.m5stack.com/en/core/Atom_EchoS3R", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
            "selection_source": "historical_browse_backed_proof_bundle",
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-07-04T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["selected_bundle_source"] == "historical_browse_backed_proof_bundle"
    assert receipt["proofs"]["assistant_grade_packet_quality"]["present"] is True
    assert receipt["proofs"]["live_browse_evidence"]["present"] is True
    assert "assistant-grade source intent and candidate alignment for the proactive OODA packet" not in receipt["remaining_external_proofs"]


def test_materialize_proactive_ooda_gold_acceptance_downgrades_unverified_telegram_approval_surface_to_manual_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_local_runtime",
            "delivery_route_ready": True,
            "live_receipt_checked": False,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": False, "receipt_path": ""},
            "approval_capture": {
                "checked": False,
                "probe_ok": False,
                "ready": False,
                "status": "not_checked",
                "blocking_reason": "",
                "next_action": "",
                "privacy": {
                    "raw_callback_token_exposed": False,
                    "raw_principal_id_exposed": False,
                    "raw_chat_ref_exposed": False,
                    "raw_packet_ref_exposed": False,
                    "raw_staged_artifact_ref_exposed": False,
                },
            },
            "approval_capture_surface": {
                "present": True,
                "ready": True,
                "mode": "telegram_callback_pending",
                "selected_channel": "telegram",
                "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "callback_dir_exists": True,
                "callback_dir_writable": True,
                "current_packet_present": True,
                "current_packet_status": "pending_approval",
                "current_packet_approval_request_recordable": True,
                "approval_outcome_matches_current_packet": False,
                "telegram_approval_surface_ready": True,
                "manual_outcome_capture_ready": True,
                "current_packet_live_pending_count": 1,
                "source": "docker_compose_exec",
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/manual.json",
            "action_required_only_quiet_receipt_path": (
                "/data/provider-ledger/proactive_ooda_run_receipts/20260629T090000-deferred-quiet.json"
            ),
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 27,
            "approval_callback_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_recorded_count": 6,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-manual.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-manual.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-manual")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-manual")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 3,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_approval_surfaces": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "action_required_only_quiet_receipt": {
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "dry_run": False,
                "item_count": 2,
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-manual",
                "stage": {"kind": "research_packet"},
                "approval": {"required": True},
                "safe_work_order": {
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    }
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-manual",
                "status": "staged_for_user_decision",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Manual Source", "url": "https://example.test/manual"},
                },
                "shortlist": [{"label": "Manual Source"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/manual", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-07-02T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    surface = receipt["evidence_receipts"]["approval_capture_surface"]
    assert surface["ready"] is True
    assert surface["mode"] == "manual_outcome_capture_ready"
    assert surface["telegram_approval_surface_ready"] is False
    assert surface["manual_outcome_capture_ready"] is True
    assert surface["current_packet_live_pending_count"] == 1
    proof = receipt["proofs"]["approval_capture_readiness"]
    assert proof["present"] is True
    assert proof["manual_capture_present"] is True
    assert proof["manual_outcome_capture_ready"] is True
    assert proof["telegram_approval_surface_ready"] is False


def test_materialize_proactive_ooda_gold_acceptance_blocks_noisy_transcript_language_reference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})
    monkeypatch.setattr(module, "_live_historical_assistant_grade_browse_bundle_from_runtime_paths", lambda **_kwargs: {})
    noisy_query = "[Mikrofonger\u00e4usche] Wir gehen jetzt, glaube ich auf die Kinderspielh\u00fcgge."
    noisy_query_with_tail = f"{noisy_query} Stimmt schauen anschauen mitgeht"

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "runtime_actionable_count": 0,
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 0,
            "approval_callback_pending_count": 0,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 0,
            "current_packet_callback_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "",
            "current_packet_callback_latest_expired": False,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-noise.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-noise.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-noise")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-noise")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 3,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-noise",
                "stage": {
                    "kind": "research_packet",
                    "payload": {
                        "adapter_hint": "transcript_signal",
                        "work_type": "compare_options",
                        "research_query": noisy_query,
                        "search_queries": [
                            noisy_query_with_tail,
                            noisy_query,
                        ],
                    },
                },
                "approval": {"required": True},
                "safe_work_order": {
                    "work_type": "compare_options",
                    "input_contract": {
                        "research_query": noisy_query,
                    },
                    "tool_hints": {"adapter_hint": "transcript_signal"},
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    },
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-noise",
                "status": "staged_for_user_decision",
                "work_type": "compare_options",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {
                        "label": "Google Translate",
                        "url": "https://translate.google.at/?hl=en",
                        "final_url": "https://translate.google.at/?hl=en&ucbcb=1",
                        "snippet": "Translate words and phrases.",
                    },
                },
                "shortlist": [{"label": "Google Translate"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 6,
                    "network_fetch_success_count": 6,
                    "page_checks": [{"url": "https://translate.google.at/?hl=en", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-06-29T10:50:00Z",
        allow_live_runtime_probe=True,
    )

    quality = receipt["proofs"]["assistant_grade_packet_quality"]
    assert receipt["status"] == "blocked_low_quality_packet_evidence"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["next_action"] == "stage_fresh_assistant_grade_proactive_packet"
    assert quality["present"] is False
    assert quality["raw_request_exposed"] is False
    assert quality["raw_candidate_exposed"] is False
    assert quality["issues"] == [
        "transcript_signal_lacks_action_intent",
        "transcript_signal_noise_like_query",
        "candidate_reference_page_not_aligned_with_request",
    ]


def test_assistant_grade_quality_blocks_single_official_info_link_without_user_request() -> None:
    module = _load_script()
    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:official-info",
        "stage": {
            "kind": "approval_packet",
            "payload": {
                "work_type": "compare_options",
                "summary": "One official public information candidate is staged for review.",
                "selection_criteria": ["official source", "reversible link only"],
            },
        },
        "safe_work_order": {
            "work_type": "compare_options",
            "input_contract": {
                "candidate_items": [
                    {
                        "label": "Official City of Vienna information portal",
                        "url": "https://www.wien.gv.at/english/",
                        "source": "official_site",
                    }
                ],
                "selection_criteria": ["official source", "reversible link only"],
                "private_payload_available": True,
            },
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:official-info",
        "status": "staged_for_user_decision",
        "work_type": "compare_options",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {
                "label": "Official City of Vienna information portal",
                "url": "https://www.wien.gv.at/english/",
                "source": "official_site",
            },
        },
        "shortlist": [
            {
                "label": "Official City of Vienna information portal",
                "url": "https://www.wien.gv.at/english/",
                "source": "official_site",
            }
        ],
        "audit": {"status": "pass", "issues": []},
    }

    proof, present = module._assistant_grade_packet_quality_proof(  # noqa: SLF001
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
        packet_artifacts_match_run_receipt=True,
    )

    assert present is False
    assert proof["present"] is False
    assert proof["decision_materiality_issue_code"] == "single_official_info_link_not_decision_ready"
    assert proof["raw_request_exposed"] is False
    assert proof["raw_candidate_exposed"] is False
    assert proof["recommended_candidate_hash"]
    assert "single_official_info_link_not_decision_ready" in proof["issues"]


def test_assistant_grade_quality_blocks_internal_operator_action_packets() -> None:
    module = _load_script()
    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:internal-action",
        "stage": {
            "kind": "internal_action",
            "payload": {
                "work_type": "record_internal_action",
                "summary": "Retry Google auth.",
            },
        },
        "safe_work_order": {
            "work_type": "record_internal_action",
            "input_contract": {
                "action_label": "Retry Google auth",
                "action_method": "get",
                "action_url": "https://myexternalbrain.com/integrations/google",
            },
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:internal-action",
        "status": "staged_for_user_decision",
        "work_type": "record_internal_action",
        "recommended_option_or_draft": {
            "kind": "internal_action",
            "value": {
                "label": "Retry Google auth",
                "method": "get",
                "url": "https://myexternalbrain.com/integrations/google",
            },
        },
        "approval": {"required": True},
        "audit": {"status": "pass", "issues": []},
    }

    proof, present = module._assistant_grade_packet_quality_proof(  # noqa: SLF001
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
        packet_artifacts_match_run_receipt=True,
    )

    assert present is False
    assert proof["present"] is False
    assert proof["stage_kind"] == "internal_action"
    assert proof["work_type"] == "record_internal_action"
    assert "internal_action_not_assistant_grade" in proof["issues"]


def test_materialize_proactive_ooda_gold_acceptance_requires_teable_approval_surface_projection_when_surface_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-live")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-live")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 3,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-live",
                "stage": {"kind": "research_packet"},
                "approval": {"required": True},
                "safe_work_order": {
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    }
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Live Source", "url": "https://example.test/live"},
                },
                "shortlist": [{"label": "Live Source"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-06-26T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["proofs"]["teable_projection"]["present"] is False
    assert receipt["proofs"]["teable_projection"]["approval_capture_surface_ready"] is True
    assert receipt["proofs"]["teable_projection"]["approval_surface_projection_present"] is False


def test_materialize_proactive_ooda_gold_acceptance_accepts_executed_gmail_draft_as_staged_reversible_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-draft",
        "stage": {"kind": "research_packet"},
        "approval": {"required": False},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-draft",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "draft_text",
            "value": "Draft to review: Guten Tag, ...",
        },
        "shortlist": [{"label": "Vendor A"}],
        "approval": {"required": False},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-draft.json", stage_packet)
    _write_json(safe_dir / "res-draft.json", safe_work_result)
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "auto_execute_results": [
                {
                    "action": "save_gmail_draft",
                    "status": "executed",
                    "packet_ref_hash": _sha256(stage_packet["packet_ref"]),
                    "safe_work_result_ref_hash": _sha256(safe_work_result["result_ref"]),
                }
            ],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-06-29T05:30:00Z",
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["next_action"] == "repair_proactive_approval_capture"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/admin/goals"
    assert receipt["proofs"]["staged_reversible_artifact"]["present"] is True
    assert receipt["proofs"]["staged_reversible_artifact"]["approval_required"] is False
    assert receipt["proofs"]["staged_reversible_artifact"]["auto_execute_action"] == "save_gmail_draft"
    assert receipt["proofs"]["staged_reversible_artifact"]["auto_execute_status"] == "executed"
    assert receipt["proofs"]["staged_reversible_artifact"]["auto_execute_match_count"] == 1
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is True
    assert receipt["remaining_external_proofs"] == [
        "redacted approval-capture readiness for the proactive OODA packet",
        "redacted explicit approval outcome for the proactive OODA packet",
    ]


def test_materialize_proactive_ooda_gold_acceptance_accepts_staged_research_packet_as_reversible_artifact_without_approval_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-research",
        "stage": {"kind": "research_packet"},
        "approval": {"required": False},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-research",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A"}],
        "approval": {"required": False},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-research.json", stage_packet)
    _write_json(safe_dir / "res-research.json", safe_work_result)
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-06-29T06:00:00Z",
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["proofs"]["staged_reversible_artifact"]["present"] is True
    assert receipt["proofs"]["staged_reversible_artifact"]["approval_required"] is False
    assert receipt["proofs"]["staged_reversible_artifact"]["auto_execute_match_count"] == 0
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is False


def test_materialize_proactive_ooda_gold_acceptance_accepts_operator_safe_mirrored_delivery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-mirror",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": True},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-mirror",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A"}],
        "approval": {"required": True},
        "approval_prompt": "Approve whether EA should proceed with Vendor A.",
        "audit": {"status": "pass", "issues": []},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-mirror.json", stage_packet)
    _write_json(safe_dir / "res-mirror.json", safe_work_result)
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_local_runtime",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {
                "ok": False,
                "notification_status": "deferred",
                "errors": ["receipt_not_sent"],
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            },
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "deferred",
            "error_code": "mirrored_delivery_proof",
            "item_count": 1,
            "telegram_message_ids": [],
            "delivery_message_ids": [],
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "delivery_mirror": {
                "schema": "ea.proactive_ooda.delivery_mirror.v1",
                "enabled": True,
                "mode": "operator_safe_mirror",
                "reason": "mirror_delivery_proof",
                "user_notification_suppressed": True,
                "approval_request_requires_user_action": True,
                "raw_notification_text_exposed": False,
                "raw_approval_prompt_exposed": False,
            },
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-06-29T06:30:00Z",
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["proofs"]["routed_delivery"]["present"] is True
    assert receipt["proofs"]["routed_delivery"]["delivery_mode"] == "operator_safe_mirror"
    assert receipt["proofs"]["routed_delivery"]["mirrored_delivery_present"] is True
    assert receipt["proofs"]["routed_delivery"]["mirror_user_notification_suppressed"] is True
    assert receipt["proofs"]["routed_delivery"]["mirror_raw_notification_text_exposed"] is False
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is True
    assert receipt["proofs"]["teable_projection"]["present"] is True
    assert receipt["proofs"]["approval_capture_readiness"]["present"] is False
    assert receipt["remaining_external_proofs"] == [
        "current recordable proactive OODA packet acceptance evidence",
    ]


def test_materialize_proactive_ooda_gold_acceptance_discards_stale_invalid_saved_approval_outcome(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
        },
    )
    _write_json(
        stage_dir / "pkt-1.json",
        {
            "schema": "proactive_ooda.stage_packet.v1",
            "packet_ref": "stage_packet:pkt-1",
            "stage": {"kind": "research_packet"},
            "approval": {"required": True},
            "safe_work_order": {
                "handoff_policy": {
                    "safe_to_execute_before_approval": True,
                    "external_actions_remain_staged_only": True,
                }
            },
        },
    )
    _write_json(
        safe_dir / "res-1.json",
        {
            "schema": "proactive_ooda.safe_work_result.v1",
            "result_ref": "safe_work_result:res-1",
            "source_packet_ref_hash": _sha256("stage_packet:pkt-1"),
            "status": "staged_for_user_decision",
            "recommended_option_or_draft": {
                "kind": "shortlist_candidate",
                "value": {"label": "Live Source", "url": "https://example.test/live"},
            },
            "shortlist": [{"label": "Live Source"}],
            "approval": {"required": True},
            "execution_receipt": {
                "network_fetch_count": 1,
                "network_fetch_success_count": 1,
                "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                "irreversible_actions_attempted": [],
            },
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-1")],
            "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-1")],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    _write_json(
        output,
        {
            "proofs": {
                "approval_outcome": {
                    "present": True,
                    "accepted": False,
                    "approval_outcome_recorded": True,
                    "status": "missing_or_invalid",
                    "outcome": "missing",
                    "source_kind": "unknown",
                    "recorded_at": "",
                    "evidence_sha256": "",
                    "actor_sha256": "",
                    "packet_ref_sha256": "",
                    "staged_artifact_sha256": "",
                }
            }
        },
    )

    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-06-26T19:20:00Z",
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["proofs"]["approval_outcome"]["present"] is False
    assert receipt["proofs"]["approval_outcome"]["approval_outcome_recorded"] is False
    assert receipt["proofs"]["approval_outcome"]["status"] == "missing_or_invalid"
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is False
    assert receipt["next_action"] == "repair_proactive_approval_capture"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/admin/goals"


def test_materialize_proactive_ooda_gold_acceptance_does_not_treat_stale_callback_as_current_packet_surface(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    callback_dir = tmp_path / "state" / "proactive_ooda_approval_callbacks"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)
    callback_dir.mkdir(parents=True, exist_ok=True)

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-current",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": True},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-current",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A"}],
        "approval": {"required": True},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-current.json", stage_packet)
    _write_json(safe_dir / "res-current.json", safe_work_result)
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )
    _write_json(
        callback_dir / "stale.json",
        {
            "schema": "ea.proactive_ooda_telegram_approval_callback.v1",
            "callback_token": "stale-token",
            "status": "pending",
            "packet_ref": "stage_packet:pkt-stale",
            "staged_artifact_ref": "safe_work_result:res-stale",
            "created_at": "2026-06-26T18:00:00Z",
        },
    )
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "generated_at": "2026-06-26T18:29:00Z",
            "source_git_head": "source-head-123",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        generated_at="2026-06-26T18:31:00Z",
    )

    assert receipt["status"] == "blocked_operator_runtime_posture"
    assert receipt["next_action"] == "cleanup_proactive_approval_callbacks"
    surface = receipt["evidence_receipts"]["approval_capture_surface"]
    assert surface["callback_record_count"] == 1
    assert surface["current_packet_callback_record_count"] == 0
    assert surface["ready"] is False
    assert surface["callback_hygiene_ready"] is False
    assert surface["callback_hygiene_blocking_reason"] == "approval_callback_noncurrent_pending"


def test_materialize_proactive_ooda_gold_acceptance_treats_expired_current_packet_callback_as_not_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json"},
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 2,
                "recipient_location_count": 1,
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": True,
            "current_packet_callback_latest_created_at": "2026-06-26T18:00:00Z",
            "current_packet_callback_latest_expires_at": "2000-01-01T00:00:00Z",
            "current_packet_callback_latest_age_seconds": 3600,
            "current_packet_callback_latest_seconds_until_expiry": 0,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-live")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-live")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 3,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-live",
                "stage": {"kind": "research_packet"},
                "approval": {"required": True},
                "safe_work_order": {
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    }
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Live Source", "url": "https://example.test/live"},
                },
                "shortlist": [{"label": "Live Source"}],
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-06-26T18:50:00Z",
        allow_live_runtime_probe=True,
    )

    surface = receipt["evidence_receipts"]["approval_capture_surface"]
    assert surface["current_packet_callback_record_count"] == 1
    assert surface["current_packet_live_pending_count"] == 0
    assert surface["current_packet_callback_latest_expired"] is True
    assert surface["current_packet_callback_latest_created_at"] == "2026-06-26T18:00:00Z"
    assert surface["current_packet_callback_latest_expires_at"] == "2000-01-01T00:00:00Z"
    assert surface["current_packet_callback_latest_age_seconds"] == 3600
    assert surface["current_packet_callback_latest_seconds_until_expiry"] == 0
    assert surface["ready"] is False
    assert surface["callback_hygiene_ready"] is False
    assert surface["callback_hygiene_blocking_reason"] == "approval_callback_current_packet_stale_pending"
    assert receipt["next_action"] == "cleanup_proactive_approval_callbacks"


def test_materialize_proactive_ooda_gold_acceptance_blocks_on_approval_callback_hygiene(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json"},
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 40,
            "approval_callback_pending_count": 3,
            "approval_callback_raw_pending_count": 3,
            "approval_callback_live_pending_count": 1,
            "approval_callback_unexpired_pending_count": 3,
            "approval_callback_noncurrent_pending_count": 2,
            "approval_callback_stale_pending_count": 2,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_recorded_count": 2,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 28,
            "approval_callback_terminal_count": 30,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_raw_pending_count": 1,
            "current_packet_callback_stale_pending_count": 0,
            "current_packet_callback_expired_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_callback_expired_count": 0,
            "current_packet_callback_superseded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "current_packet_callback_latest_created_at": "2026-07-02T16:21:48Z",
            "current_packet_callback_latest_expires_at": "2026-07-09T16:21:48Z",
            "current_packet_callback_latest_age_seconds": 300,
            "current_packet_callback_latest_seconds_until_expiry": 604500,
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-live")],
                "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-live")],
                "teable_sync": {
                    "status": "synced",
                    "sync_attempted": True,
                    "projection_summary": {
                        "record_count": 3,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                        },
                    },
                    "missing_tables": [],
                },
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-live",
                "stage": {"kind": "research_packet"},
                "approval": {"required": True},
                "safe_work_order": {
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    }
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Live Source", "url": "https://example.test/live"},
                },
                "shortlist": [{"label": "Live Source"}],
                "approval": {"required": True},
                "approval_prompt": "Approve this staged candidate.",
                "staged_action_url": "https://example.test/live",
                "audit": {"status": "pass", "issues": []},
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        generated_at="2026-07-02T17:10:00Z",
        allow_live_runtime_probe=True,
    )

    assert receipt["status"] == "blocked_operator_runtime_posture"
    assert receipt["next_action"] == "cleanup_proactive_approval_callbacks"
    assert receipt["proofs"]["operator_runtime_posture"]["present"] is False
    assert receipt["proofs"]["operator_runtime_posture"]["approval_callback_hygiene_ready"] is False
    assert receipt["proofs"]["operator_runtime_posture"]["approval_callback_hygiene_blocking_reason"] == "approval_callback_noncurrent_pending"
    surface = receipt["evidence_receipts"]["approval_capture_surface"]
    assert surface["ready"] is False
    assert surface["callback_hygiene_ready"] is False
    assert surface["callback_hygiene_blocking_reason"] == "approval_callback_noncurrent_pending"
    assert surface["callback_noncurrent_pending_count"] == 2
    assert surface["callback_stale_pending_count"] == 2


def test_materialize_proactive_ooda_gold_acceptance_reads_explicit_runtime_approval_outcome_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    approval_outcome_path = tmp_path / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        stage_dir / "pkt-1.json",
        {
            "schema": "proactive_ooda.stage_packet.v1",
            "packet_ref": "stage_packet:pkt-1",
            "stage": {"kind": "approval_packet"},
            "approval": {"required": True},
            "safe_work_order": {
                "handoff_policy": {
                    "safe_to_execute_before_approval": True,
                    "external_actions_remain_staged_only": True,
                }
            },
        },
    )
    _write_json(
        safe_dir / "res-1.json",
        {
            "schema": "proactive_ooda.safe_work_result.v1",
            "result_ref": "safe_work_result:res-1",
            "source_packet_ref_hash": _sha256("stage_packet:pkt-1"),
            "status": "staged_for_user_decision",
            "recommended_option_or_draft": {
                "kind": "shortlist_candidate",
                "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
            },
            "shortlist": [{"label": "Vendor A"}],
            "approval": {"required": True},
            "execution_receipt": {
                "network_fetch_count": 1,
                "network_fetch_success_count": 1,
                "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
                "irreversible_actions_attempted": [],
            },
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-1")],
            "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-1")],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )
    _write_json(
        approval_outcome_path,
        {
            "schema": "ea.proactive_ooda_approval_outcome.v1",
            "contract_name": "ea.proactive_ooda_approval_outcome.v1",
            "approval_outcome_recorded": True,
            "accepted": True,
            "outcome": "approved",
            "status": "accepted_redacted",
            "source_kind": "operator",
            "recorded_at": "2026-06-26T19:30:00Z",
            "evidence_sha256": _sha256("Approved after the live shortlist review."),
            "actor_sha256": _sha256("operator-admin-1"),
            "packet_ref_sha256": _sha256("stage_packet:pkt-1"),
            "staged_artifact_sha256": _sha256("safe_work_result:res-1"),
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        approval_outcome_path=approval_outcome_path,
        generated_at="2026-06-26T19:31:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["proofs"]["approval_outcome"]["present"] is True
    assert receipt["proofs"]["approval_outcome"]["accepted"] is True
    assert receipt["evidence_receipts"]["approval_outcome"]["path"].endswith(
        "proactive_ooda_latest_approval_outcome.generated.json"
    )
    assert receipt["evidence_receipts"]["approval_outcome"]["present"] is True
    assert receipt["evidence_receipts"]["approval_outcome"]["artifact_present"] is True
    assert receipt["evidence_receipts"]["approval_outcome"]["schema"] == "ea.proactive_ooda_approval_outcome.v1"
    assert receipt["evidence_receipts"]["approval_outcome"]["status"] == "accepted_redacted"
    assert receipt["evidence_receipts"]["approval_outcome"]["artifact_status"] == "accepted_redacted"
    assert receipt["evidence_receipts"]["approval_outcome"]["current_packet_status"] == "accepted_redacted"
    assert receipt["evidence_receipts"]["approval_outcome"]["current_packet_match"] is True
    assert receipt["evidence_receipts"]["approval_outcome"]["stale_for_current_packet"] is False
    assert receipt["evidence_receipts"]["approval_outcome"]["packet_artifacts_match_current_packet"] is True


def test_historical_accepted_bundle_from_approval_outcome_recovers_archived_artifacts(
    tmp_path: Path,
) -> None:
    module = _load_script()

    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    archive_dir = tmp_path / "state" / "assistant_property_boundary_archive" / "20260703T044750Z"
    archive_run_dir = archive_dir / "run_receipts"
    archive_stage_dir = archive_dir / "stage_packets"
    archive_safe_dir = archive_dir / "safe_work_results"
    run_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)
    archive_run_dir.mkdir(parents=True, exist_ok=True)
    archive_stage_dir.mkdir(parents=True, exist_ok=True)
    archive_safe_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        run_receipt_path,
        {
            "notification_status": "skipped_no_items",
            "item_count": 0,
            "delivery_message_ids": [],
            "telegram_message_ids": [],
        },
    )

    archived_stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-accepted-archived",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": True},
        "safe_work_order": {
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            }
        },
    }
    archived_safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-accepted-archived",
        "source_packet_ref_hash": _sha256(archived_stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "shortlist": [{"label": "Vendor A"}],
        "approval": {"required": True},
        "audit": {"status": "pass", "issues": []},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(archive_stage_dir / "pkt-accepted-archived.json", archived_stage_packet)
    _write_json(archive_safe_dir / "res-accepted-archived.json", archived_safe_work_result)
    _write_json(
        archive_run_dir / "20260702T113932_507121_0000-sent-accepted.json",
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(archived_stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(archived_safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(archive_stage_dir),
            "safe_work_result_output_dir": str(archive_safe_dir),
        },
    )

    bundle = module._historical_accepted_bundle_from_approval_outcome(  # noqa: SLF001
        approval_row={
            "approval_outcome_recorded": True,
            "accepted": True,
            "packet_ref_sha256": _sha256(archived_stage_packet["packet_ref"]),
            "staged_artifact_sha256": _sha256(archived_safe_work_result["result_ref"]),
        },
        run_receipt_path=run_receipt_path,
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
    )

    assert bundle["selection_source"] == "historical_accepted_approval_outcome"
    assert bundle["stage_packet_path"] == archive_stage_dir / "pkt-accepted-archived.json"
    assert bundle["safe_work_result_path"] == archive_safe_dir / "res-accepted-archived.json"
    assert bundle["run_receipt_path"] == archive_run_dir / "20260702T113932_507121_0000-sent-accepted.json"
    assert bundle["stage_packet"]["packet_ref"] == archived_stage_packet["packet_ref"]
    assert bundle["safe_work_result"]["result_ref"] == archived_safe_work_result["result_ref"]


def test_materialize_proactive_ooda_gold_acceptance_accepts_terminal_approval_capture_after_recorded_current_packet_outcome(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    approval_outcome_path = tmp_path / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "runtime_actionable_count": 0,
            "approval_capture": {
                "checked": True,
                "probe_ok": True,
                "ready": False,
                "status": "blocked",
                "source": "docker_compose_exec:proactive_approval_capture",
                "observed_at": "2026-06-30T02:08:29Z",
                "blocking_reason": "current_packet_approval_callback_missing",
                "next_action": "reissue_proactive_approval",
                "current_packet_refs_present": True,
                "current_packet_callback_record_count": 1,
                "current_packet_live_pending_count": 0,
                "current_packet_callback_latest_status": "approved",
                "callback_principal_hash_present": True,
                "candidate_principal_hash_count": 3,
                "principal_match_ready": True,
                "telegram_binding_ready": True,
                "telegram_chat_ref_present": True,
                "telegram_bot_token_present": True,
                "privacy": {
                    "raw_callback_token_exposed": False,
                    "raw_principal_id_exposed": False,
                    "raw_chat_ref_exposed": False,
                    "raw_packet_ref_exposed": False,
                    "raw_staged_artifact_ref_exposed": False,
                },
            },
        },
    )
    _write_json(
        stage_dir / "pkt-1.json",
        {
            "schema": "proactive_ooda.stage_packet.v1",
            "packet_ref": "stage_packet:pkt-1",
            "stage": {"kind": "approval_packet"},
            "approval": {"required": True},
            "safe_work_order": {
                "handoff_policy": {
                    "safe_to_execute_before_approval": True,
                    "external_actions_remain_staged_only": True,
                }
            },
        },
    )
    _write_json(
        safe_dir / "res-1.json",
        {
            "schema": "proactive_ooda.safe_work_result.v1",
            "result_ref": "safe_work_result:res-1",
            "source_packet_ref_hash": _sha256("stage_packet:pkt-1"),
            "status": "staged_for_user_decision",
            "recommended_option_or_draft": {
                "kind": "shortlist_candidate",
                "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
            },
            "shortlist": [{"label": "Vendor A"}],
            "approval": {"required": True},
            "audit": {"status": "pass", "issues": []},
            "execution_receipt": {
                "network_fetch_count": 1,
                "network_fetch_success_count": 1,
                "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
                "irreversible_actions_attempted": [],
            },
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-1")],
            "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-1")],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 4,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                        "proactive_ooda_approval_surfaces": {"record_count": 1},
                    },
                },
            },
        },
    )
    _write_json(
        approval_outcome_path,
        {
            "schema": "ea.proactive_ooda_approval_outcome.v1",
            "contract_name": "ea.proactive_ooda_approval_outcome.v1",
            "approval_outcome_recorded": True,
            "accepted": True,
            "outcome": "approved",
            "status": "accepted_redacted",
            "source_kind": "telegram_button",
            "recorded_at": "2026-06-30T00:05:42Z",
            "evidence_sha256": _sha256("Approved after the live shortlist review."),
            "actor_sha256": _sha256("operator-admin-1"),
            "packet_ref_sha256": _sha256("stage_packet:pkt-1"),
            "staged_artifact_sha256": _sha256("safe_work_result:res-1"),
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        approval_outcome_path=approval_outcome_path,
        generated_at="2026-06-30T02:24:44Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["gold_claim_allowed"] is True
    assert receipt["proofs"]["approval_capture_readiness"]["present"] is True
    assert receipt["proofs"]["approval_capture_readiness"]["satisfied_by_recorded_outcome"] is True
    assert receipt["proofs"]["approval_capture_readiness"]["current_packet_live_pending_count"] == 0
    assert receipt["proofs"]["approval_capture_readiness"]["current_packet_callback_latest_status"] == "approved"
    assert receipt["proofs"]["approval_outcome"]["accepted"] is True
    assert receipt["remaining_external_proofs"] == []


def test_materialize_proactive_ooda_gold_acceptance_merges_current_approval_outcome_teable_sync_when_run_summary_only_has_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    approval_outcome_path = tmp_path / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "runtime_actionable_count": 0,
            "approval_capture": {
                "checked": True,
                "probe_ok": True,
                "ready": False,
                "status": "blocked",
                "source": "docker_compose_exec:proactive_approval_capture",
                "observed_at": "2026-06-30T02:08:29Z",
                "blocking_reason": "current_packet_approval_callback_missing",
                "next_action": "reissue_proactive_approval",
                "current_packet_refs_present": True,
                "current_packet_callback_record_count": 1,
                "current_packet_live_pending_count": 0,
                "current_packet_callback_latest_status": "rejected",
                "callback_principal_hash_present": True,
                "candidate_principal_hash_count": 3,
                "principal_match_ready": True,
                "telegram_binding_ready": True,
                "telegram_chat_ref_present": True,
                "telegram_bot_token_present": True,
                "privacy": {
                    "raw_callback_token_exposed": False,
                    "raw_principal_id_exposed": False,
                    "raw_chat_ref_exposed": False,
                    "raw_packet_ref_exposed": False,
                    "raw_staged_artifact_ref_exposed": False,
                },
            },
        },
    )
    _write_json(
        stage_dir / "pkt-1.json",
        {
            "schema": "proactive_ooda.stage_packet.v1",
            "packet_ref": "stage_packet:pkt-1",
            "stage": {"kind": "approval_packet"},
            "approval": {"required": True},
            "safe_work_order": {
                "handoff_policy": {
                    "safe_to_execute_before_approval": True,
                    "external_actions_remain_staged_only": True,
                }
            },
        },
    )
    _write_json(
        safe_dir / "res-1.json",
        {
            "schema": "proactive_ooda.safe_work_result.v1",
            "result_ref": "safe_work_result:res-1",
            "source_packet_ref_hash": _sha256("stage_packet:pkt-1"),
            "status": "staged_for_user_decision",
            "recommended_option_or_draft": {
                "kind": "shortlist_candidate",
                "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
            },
            "shortlist": [{"label": "Vendor A"}],
            "approval": {"required": True},
            "audit": {"status": "pass", "issues": []},
            "execution_receipt": {
                "network_fetch_count": 1,
                "network_fetch_success_count": 1,
                "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
                "irreversible_actions_attempted": [],
            },
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-1")],
            "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-1")],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 1,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                    },
                },
            },
        },
    )
    _write_json(
        approval_outcome_path,
        {
            "schema": "ea.proactive_ooda_approval_outcome.v1",
            "contract_name": "ea.proactive_ooda_approval_outcome.v1",
            "approval_outcome_recorded": True,
            "accepted": False,
            "outcome": "rejected",
            "status": "recorded_not_accepted",
            "source_kind": "telegram_button",
            "recorded_at": "2026-06-30T00:05:42Z",
            "evidence_sha256": _sha256("Rejected after the live shortlist review."),
            "actor_sha256": _sha256("operator-admin-1"),
            "packet_ref_sha256": _sha256("stage_packet:pkt-1"),
            "staged_artifact_sha256": _sha256("safe_work_result:res-1"),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_approval_surfaces": {"record_count": 1},
                    },
                },
            },
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        approval_outcome_path=approval_outcome_path,
        generated_at="2026-06-30T02:24:44Z",
    )

    assert receipt["status"] == "blocked_not_accepted_under_ordinary_use"
    assert receipt["proofs"]["teable_projection"]["present"] is True
    assert receipt["proofs"]["teable_projection"]["packet_projection_present"] is True
    assert receipt["proofs"]["teable_projection"]["approval_surface_projection_present"] is True
    assert receipt["proofs"]["teable_projection"]["approval_outcome_sync_attempted"] is True
    assert receipt["proofs"]["teable_projection"]["approval_outcome_teable_status"] == "synced"
    assert receipt["proofs"]["approval_outcome"]["present"] is True
    assert receipt["proofs"]["approval_outcome"]["accepted"] is False
    assert "mirrored Teable projection for the proactive OODA packet" not in receipt["remaining_external_proofs"]
    assert receipt["remaining_external_proofs"] == ["real proactive OODA packet accepted under ordinary use"]


def test_materialize_proactive_ooda_gold_acceptance_marks_mismatched_runtime_approval_outcome_as_artifact_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    approval_outcome_path = tmp_path / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
        },
    )
    _write_json(
        stage_dir / "pkt-1.json",
        {
            "schema": "proactive_ooda.stage_packet.v1",
            "packet_ref": "stage_packet:pkt-1",
            "stage": {"kind": "approval_packet"},
            "approval": {"required": True},
            "safe_work_order": {
                "handoff_policy": {
                    "safe_to_execute_before_approval": True,
                    "external_actions_remain_staged_only": True,
                }
            },
        },
    )
    _write_json(
        safe_dir / "res-1.json",
        {
            "schema": "proactive_ooda.safe_work_result.v1",
            "result_ref": "safe_work_result:res-1",
            "source_packet_ref_hash": _sha256("stage_packet:pkt-1"),
            "status": "staged_for_user_decision",
            "recommended_option_or_draft": {
                "kind": "shortlist_candidate",
                "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
            },
            "shortlist": [{"label": "Vendor A"}],
            "approval": {"required": True},
            "execution_receipt": {
                "network_fetch_count": 1,
                "network_fetch_success_count": 1,
                "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
                "irreversible_actions_attempted": [],
            },
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-1")],
            "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-1")],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )
    _write_json(
        approval_outcome_path,
        {
            "schema": "ea.proactive_ooda_approval_outcome.v1",
            "contract_name": "ea.proactive_ooda_approval_outcome.v1",
            "approval_outcome_recorded": True,
            "accepted": True,
            "outcome": "approved",
            "status": "accepted_redacted",
            "source_kind": "operator",
            "recorded_at": "2026-06-26T19:30:00Z",
            "evidence_sha256": _sha256("Approved after the live shortlist review."),
            "actor_sha256": _sha256("operator-admin-1"),
            "packet_ref_sha256": _sha256("stage_packet:stale-pkt"),
            "staged_artifact_sha256": _sha256("safe_work_result:stale-res"),
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        approval_outcome_path=approval_outcome_path,
        generated_at="2026-06-26T19:31:00Z",
    )

    assert receipt["status"] == "blocked_missing_proactive_packet_evidence"
    assert receipt["proofs"]["approval_outcome"]["present"] is False
    assert receipt["proofs"]["approval_outcome"]["approval_outcome_recorded"] is False
    assert receipt["proofs"]["approval_outcome"]["status"] == "stale_for_current_packet"
    assert receipt["proofs"]["approval_outcome"]["current_packet_match"] is False
    assert receipt["proofs"]["approval_outcome"]["stale_for_current_packet"] is True
    assert receipt["evidence_receipts"]["approval_outcome"]["present"] is False
    assert receipt["evidence_receipts"]["approval_outcome"]["artifact_present"] is True
    assert receipt["evidence_receipts"]["approval_outcome"]["status"] == "stale_for_current_packet"
    assert receipt["evidence_receipts"]["approval_outcome"]["artifact_status"] == "accepted_redacted"
    assert receipt["evidence_receipts"]["approval_outcome"]["current_packet_status"] == "stale_for_current_packet"
    assert receipt["evidence_receipts"]["approval_outcome"]["current_packet_match"] is False
    assert receipt["evidence_receipts"]["approval_outcome"]["stale_for_current_packet"] is True
    assert receipt["evidence_receipts"]["approval_outcome"]["packet_artifacts_match_current_packet"] is False
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is False


def test_materialize_proactive_ooda_gold_acceptance_uses_current_approved_callback_when_latest_outcome_is_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    run_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    approval_outcome_path = tmp_path / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
    callback_dir = tmp_path / "state" / "proactive_ooda_approval_callbacks"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)
    callback_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        operator_status_path,
        {
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "delivery_route_ready": True,
            "live_receipt_checked": True,
            "delivery_route": {"selected_channel": "telegram"},
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"},
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "has_high_priority": False,
                "interruption_budget_exhausted": False,
                "quiet_hours_active": False,
            },
            "runtime_actionable_count": 0,
        },
    )
    _write_json(
        stage_dir / "pkt-1.json",
        {
            "schema": "proactive_ooda.stage_packet.v1",
            "packet_ref": "stage_packet:pkt-1",
            "stage": {"kind": "approval_packet"},
            "approval": {"required": True},
            "safe_work_order": {
                "handoff_policy": {
                    "safe_to_execute_before_approval": True,
                    "external_actions_remain_staged_only": True,
                }
            },
        },
    )
    _write_json(
        safe_dir / "res-1.json",
        {
            "schema": "proactive_ooda.safe_work_result.v1",
            "result_ref": "safe_work_result:res-1",
            "source_packet_ref_hash": _sha256("stage_packet:pkt-1"),
            "status": "staged_for_user_decision",
            "recommended_option_or_draft": {
                "kind": "shortlist_candidate",
                "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
            },
            "shortlist": [{"label": "Vendor A"}],
            "approval": {"required": True},
            "execution_receipt": {
                "network_fetch_count": 1,
                "network_fetch_success_count": 1,
                "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
                "irreversible_actions_attempted": [],
            },
        },
    )
    _write_json(
        run_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256("stage_packet:pkt-1")],
            "safe_work_result_ref_hashes": [_sha256("safe_work_result:res-1")],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "blocked_reason": "",
                "missing_tables": [],
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                    },
                },
            },
        },
    )
    _write_json(
        approval_outcome_path,
        {
            "schema": "ea.proactive_ooda_approval_outcome.v1",
            "contract_name": "ea.proactive_ooda_approval_outcome.v1",
            "approval_outcome_recorded": True,
            "accepted": True,
            "outcome": "approved",
            "status": "accepted_redacted",
            "source_kind": "operator",
            "recorded_at": "2026-06-26T19:30:00Z",
            "evidence_sha256": _sha256("Approved after a stale shortlist review."),
            "actor_sha256": _sha256("operator-admin-1"),
            "packet_ref_sha256": _sha256("stage_packet:stale-pkt"),
            "staged_artifact_sha256": _sha256("safe_work_result:stale-res"),
        },
    )
    _write_json(
        callback_dir / "current-approved.json",
        {
            "schema": "ea.proactive_ooda_telegram_approval_callback.v1",
            "status": "approved",
            "packet_ref": "stage_packet:pkt-1",
            "staged_artifact_ref": "safe_work_result:res-1",
            "packet_ref_sha256": _sha256("stage_packet:pkt-1"),
            "staged_artifact_ref_sha256": _sha256("safe_work_result:res-1"),
            "actor_sha256": _sha256("telegram-user-1"),
            "approval_prompt_sha256": _sha256("Approve whether EA should proceed."),
            "approval_outcome_id": "proactive-ooda-approval-current",
            "created_at": "2026-06-26T19:29:00Z",
            "decided_at": "2026-06-26T19:32:00Z",
            "expires_at": "2026-07-05T19:29:00Z",
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    receipt = module.materialize_proactive_ooda_gold_acceptance(
        output_path=output,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        approval_outcome_path=approval_outcome_path,
        generated_at="2026-06-26T19:33:00Z",
    )

    assert receipt["status"] == "pass"
    approval = receipt["proofs"]["approval_outcome"]
    assert approval["present"] is True
    assert approval["accepted"] is True
    assert approval["source_kind"] == "telegram_button"
    assert approval["packet_ref_sha256"] == _sha256("stage_packet:pkt-1")
    assert approval["staged_artifact_sha256"] == _sha256("safe_work_result:res-1")
    approval_evidence = receipt["evidence_receipts"]["approval_outcome"]
    assert approval_evidence["callback_outcome_present"] is True
    assert approval_evidence["callback_outcome_used"] is True
    assert approval_evidence["approval_outcome_source"] == "current_packet_callback"
    assert approval_evidence["artifact_status"] == "accepted_redacted"
    assert approval_evidence["current_packet_status"] == "accepted_redacted"
    assert approval_evidence["current_packet_match"] is True
    assert approval_evidence["stale_for_current_packet"] is False
    assert approval_evidence["packet_artifacts_match_current_packet"] is True
