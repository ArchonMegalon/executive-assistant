from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "materialize_proactive_ooda_gold_acceptance.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("materialize_proactive_ooda_gold_acceptance", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
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
        payload = {**payload, "approval_capture": _approval_capture_ready()}
    if payload.get("schema") == "proactive_ooda.safe_work_result.v1" and "audit" not in payload:
        payload = {**payload, "audit": {"status": "pass", "issues": []}}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_materialize_proactive_ooda_gold_acceptance_passes_with_full_proof_chain(
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
    assert receipt["proofs"]["operator_runtime_posture"]["next_action_href"] == (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    assert receipt["proofs"]["approval_outcome"]["accepted"] is True
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
    assert receipt["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/admin/proactive-ooda/approval"
    assert receipt["next_action_label"] == "Open approval capture"
    assert receipt["next_action_method"] == "get"
    assert receipt["evidence_receipts"]["approval_capture_surface"]["ready"] is True
    assert receipt["evidence_receipts"]["approval_capture_surface"]["callback_record_count"] == 1
    assert receipt["evidence_receipts"]["approval_capture_surface"]["current_packet_callback_record_count"] == 1
    assert receipt["evidence_receipts"]["approval_capture_surface"]["current_packet_live_pending_count"] == 1
    assert receipt["proofs"]["approval_capture_readiness"]["present"] is True
    assert receipt["evidence_receipts"]["approval_capture"]["principal_match_ready"] is True
    assert receipt["evidence_receipts"]["run_receipt"]["source"] == "docker_compose_exec"
    assert receipt["evidence_receipts"]["stage_packet"]["path"] == "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json"


def test_materialize_proactive_ooda_gold_acceptance_blocks_noisy_transcript_language_reference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
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

    assert receipt["status"] == "ready_for_approval_outcome_capture"
    assert receipt["next_action"] == "record_proactive_ooda_approval_outcome"
    assert receipt["proofs"]["staged_reversible_artifact"]["present"] is True
    assert receipt["proofs"]["staged_reversible_artifact"]["approval_required"] is False
    assert receipt["proofs"]["staged_reversible_artifact"]["auto_execute_action"] == "save_gmail_draft"
    assert receipt["proofs"]["staged_reversible_artifact"]["auto_execute_status"] == "executed"
    assert receipt["proofs"]["staged_reversible_artifact"]["auto_execute_match_count"] == 1
    assert receipt["remaining_external_proofs"] == ["redacted explicit approval outcome for the proactive OODA packet"]


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

    assert receipt["status"] == "ready_for_approval_outcome_capture"
    assert receipt["proofs"]["staged_reversible_artifact"]["present"] is True
    assert receipt["proofs"]["staged_reversible_artifact"]["approval_required"] is False
    assert receipt["proofs"]["staged_reversible_artifact"]["auto_execute_match_count"] == 0


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

    assert receipt["status"] == "ready_for_approval_outcome_capture"
    assert receipt["proofs"]["approval_outcome"]["present"] is False
    assert receipt["proofs"]["approval_outcome"]["approval_outcome_recorded"] is False
    assert receipt["proofs"]["approval_outcome"]["status"] == "missing_or_invalid"
    assert receipt["next_action"] == "record_proactive_ooda_approval_outcome"


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

    assert receipt["status"] == "ready_for_approval_outcome_capture"
    assert receipt["next_action"] == "record_proactive_ooda_approval_outcome"
    surface = receipt["evidence_receipts"]["approval_capture_surface"]
    assert surface["callback_record_count"] == 1
    assert surface["current_packet_callback_record_count"] == 0
    assert surface["ready"] is False


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
    assert receipt["next_action"] == "record_proactive_ooda_approval_outcome"


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
    assert receipt["evidence_receipts"]["approval_outcome"]["packet_artifacts_match_current_packet"] is True


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

    assert receipt["status"] == "ready_for_approval_outcome_capture"
    assert receipt["proofs"]["approval_outcome"]["present"] is False
    assert receipt["proofs"]["approval_outcome"]["approval_outcome_recorded"] is False
    assert receipt["proofs"]["approval_outcome"]["status"] == "missing_or_invalid"
    assert receipt["evidence_receipts"]["approval_outcome"]["present"] is False
    assert receipt["evidence_receipts"]["approval_outcome"]["artifact_present"] is True
    assert receipt["evidence_receipts"]["approval_outcome"]["status"] == "missing_or_invalid"
    assert receipt["evidence_receipts"]["approval_outcome"]["artifact_status"] == "accepted_redacted"
    assert receipt["evidence_receipts"]["approval_outcome"]["packet_artifacts_match_current_packet"] is False


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
    assert approval_evidence["packet_artifacts_match_current_packet"] is True
