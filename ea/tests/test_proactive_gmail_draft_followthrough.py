from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EA_LIVE_OPS_PATH = ROOT / "scripts" / "ea_live_ops.py"
VERIFY_OPERATOR_STATUS_PATH = ROOT / "scripts" / "verify_proactive_ooda_operator_status.py"


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_gmail_draft_no_pending_status_points_to_draft_queue() -> None:
    module = _load_script(EA_LIVE_OPS_PATH, "ea_live_ops_for_gmail_draft_test")

    assert module._proactive_gmail_draft_next_action(status="no_pending_draft") == "review_proactive_draft_queue"  # noqa: SLF001
    surface = module._next_action_surface_fields("review_proactive_draft_queue")  # noqa: SLF001
    assert surface["next_action_href"]
    assert surface["next_action_label"]
    assert surface["next_action_method"] == "get"


def test_operator_status_verifier_requires_gmail_followthrough_next_action(tmp_path: Path) -> None:
    verifier = _load_script(VERIFY_OPERATOR_STATUS_PATH, "verify_operator_status_for_gmail_draft_test")
    receipt_path = tmp_path / "operator_status.json"
    source_lanes = [
        {"key": key, "status": "observed"}
        for key in sorted(verifier.EXPECTED_SOURCE_COVERAGE_LANES)
    ]
    receipt = {
        "contract_name": "ea.proactive_ooda.operator_status.v1",
        "generated_at": "2026-06-30T00:00:00Z",
        "generated_by": "scripts/materialize_proactive_ooda_operator_status.py",
        "source_git_head": verifier._git_head(verifier.ROOT),  # noqa: SLF001
        "head_semantics": "source_state",
        "source_state_fingerprint": verifier._source_fingerprint(verifier.ROOT),  # noqa: SLF001
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "status": "ready_with_live_receipt",
        "reason": "",
        "summary": "fixture",
        "next_action": "maintain_proactive_ooda_runtime",
        "goal_completion_claim_allowed": False,
        "live_delivery_claim_allowed": False,
        "route_probe_source": "host_verifier",
        "rules": list(verifier.EXPECTED_RULES),
        "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
        "delivery_guard": {"delivery_state": "sent"},
        "stage_packets": {"ready": True},
        "safe_work_results": {"ready": True},
        "gmail_draft_followthrough": {
            "checked": True,
            "status": "no_pending_draft",
            "raw_execution_payload_exposed": False,
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
        },
        "source_coverage": {
            "checked": True,
            "status": "ready",
            "ready": True,
            "lane_count": len(verifier.EXPECTED_SOURCE_COVERAGE_LANES),
            "observed_lane_count": len(verifier.EXPECTED_SOURCE_COVERAGE_LANES),
            "lanes": source_lanes,
            "privacy": {
                "raw_rows_exposed": False,
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
            },
            "missing_lane_keys": [],
        },
        "live_receipt_checked": True,
        "live_receipt": {"ok": True, "receipt_path": "receipt.json"},
        "approval_capture_surface": {},
        "approval_capture": {},
        "verifier_commands": [
            "make verify-proactive-ooda",
            "make verify-proactive-ooda-live-receipt",
            "make verify-proactive-ooda-operator-status",
        ],
        "remaining_external_proofs": [verifier.EXPECTED_REMAINING_PROOF],
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    issues = verifier.verify(receipt_path)

    assert "no_pending_draft gmail_draft_followthrough requires next_action" in issues
