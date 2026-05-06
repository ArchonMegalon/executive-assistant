#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from app.yaml_inputs import load_yaml_dict

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer_participation_followthrough_packets" / "CHUMMER_PARTICIPATION_FOLLOWTHROUGH_PACKET_PACK.yaml"
SPECIMENS_PATH = ROOT / "docs" / "chummer_participation_followthrough_packets" / "PARTICIPATION_FOLLOWTHROUGH_PACKET_SPECIMENS.yaml"
PROOF_PATH = ROOT / ".codex-studio" / "published" / "NEXT90_M129_EA_PARTICIPATION_FOLLOWTHROUGH_PACKETS.generated.json"
HANDOFF_CLOSEOUT_PATH = ROOT / "docs" / "chummer_participation_followthrough_packets" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
HUB_PROOF_PATH = Path("/docker/chummercomplete/chummer6-hub-m112/.codex-studio/published/NEXT90_M129_HUB_REUSABLE_ACCOUNT_FLOWS.generated.json")
FLEET_PROOF_PATH = Path("/docker/fleet/.codex-studio/published/NEXT90_M129_FLEET_PARTICIPATION_LANE_RECEIPTS.generated.json")

def _yaml(path: Path) -> dict[str, Any]:
    return load_yaml_dict(path)

def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8")) or {}
    return dict(payload) if isinstance(payload, dict) else {}

def without_generated_at(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(payload).items() if key != "generated_at"}

def _hub_source_status() -> dict[str, Any]:
    if not HUB_PROOF_PATH.is_file():
        return {
            "path": str(HUB_PROOF_PATH),
            "required": True,
            "present": False,
            "status": "missing",
            "reward_journal_projection_available": False,
            "entitlement_journal_projection_available": False,
            "account_membership_projection_available": False,
            "required_markers": [],
        }
    payload = _json(HUB_PROOF_PATH)
    markers = [str(item) for item in payload.get("required_markers") or []]
    return {
        "path": str(HUB_PROOF_PATH),
        "required": True,
        "present": True,
        "status": str(payload.get("status") or "unknown"),
        "package_id": str(dict(payload.get("package_proof") or {}).get("package_id") or ""),
        "reward_journal_projection_available": any("reward-journal" in marker for marker in markers),
        "entitlement_journal_projection_available": any("entitlement-journal" in marker for marker in markers),
        "account_membership_projection_available": any("membership status" in marker for marker in markers),
        "required_markers": markers,
    }

def _fleet_source_status() -> dict[str, Any]:
    if not FLEET_PROOF_PATH.is_file():
        return {
            "path": str(FLEET_PROOF_PATH),
            "required": True,
            "present": False,
            "status": "missing",
            "participation_status": "missing",
            "runtime_blockers": ["fleet participation receipt proof is missing"],
            "contribution_receipt_projection_available": False,
            "lane_local_boundary_proven": False,
            "sponsor_session_projection_available": False,
        }
    payload = _json(FLEET_PROOF_PATH)
    summary = dict(payload.get("monitor_summary") or {})
    controller = dict(dict(payload.get("runtime_monitors") or {}).get("controller_receipts") or {})
    controller_runtime_blockers = [str(item) for item in controller.get("runtime_blockers") or []]
    return {
        "path": str(FLEET_PROOF_PATH),
        "required": True,
        "present": True,
        "status": str(payload.get("status") or "unknown"),
        "package_id": str(payload.get("package_id") or ""),
        "participation_status": str(summary.get("participation_status") or "unknown"),
        "runtime_blockers": [str(item) for item in summary.get("runtime_blockers") or []],
        "contribution_receipt_projection_available": int(summary.get("controller_receipt_match_count") or 0) > 0,
        "lane_local_boundary_proven": int(summary.get("controller_forbidden_leak_count") or 1) == 0,
        "sponsor_session_projection_available": not any("sponsor_session_id" in item for item in controller_runtime_blockers),
    }

def _projection_gaps(hub_status: dict[str, Any], fleet_status: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if fleet_status.get("participation_status") != "pass":
        gaps.append(
            {
                "gap_id": "fleet_participation_receipt_window_blocked",
                "source_anchor_id": "fleet_participation_lane_receipts",
                "hold_reason": "Fleet participation proof still reports runtime blockers, so contribution and participation followthrough must stay on hold.",
                "runtime_blockers": list(fleet_status.get("runtime_blockers") or []),
            }
        )
    if not fleet_status.get("sponsor_session_projection_available"):
        gaps.append(
            {
                "gap_id": "missing_sponsor_session_receipt_projection",
                "source_anchor_id": "fleet_participation_lane_receipts",
                "hold_reason": "Fleet does not yet prove sponsor_session_id as a clean receipt projection in the current contract window.",
            }
        )
    if not hub_status.get("entitlement_journal_projection_available"):
        gaps.append(
            {
                "gap_id": "missing_entitlement_journal_projection",
                "source_anchor_id": "hub_reusable_account_flows_receipt",
                "hold_reason": "Hub reusable-account proof no longer exposes the entitlement-journal rail needed for participant followthrough.",
            }
        )
    if not hub_status.get("reward_journal_projection_available"):
        gaps.append(
            {
                "gap_id": "missing_reward_journal_projection",
                "source_anchor_id": "hub_reusable_account_flows_receipt",
                "hold_reason": "Hub reusable-account proof no longer exposes the reward-journal rail needed for reward followthrough.",
            }
        )
    gaps.append(
        {
            "gap_id": "missing_hub_or_fleet_channel_ref_projection",
            "source_anchor_id": "hub_reusable_account_flows_receipt+fleet_participation_lane_receipts",
            "hold_reason": "The current Hub/Fleet receipt window does not project a channel ref such as desktopChannelRef or an equivalent governed channel token.",
        }
    )
    gaps.append(
        {
            "gap_id": "missing_hub_or_fleet_reward_publication_projection",
            "source_anchor_id": "hub_reusable_account_flows_receipt+fleet_participation_lane_receipts",
            "hold_reason": "The current Hub/Fleet receipt window does not project a reward publication ref that EA can cite without falling back to Registry-only mirrors.",
        }
    )
    return gaps

def build_payload() -> dict[str, Any]:
    pack = _yaml(PACK_PATH)
    specimens = _yaml(SPECIMENS_PATH)
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    bundle = dict(pack.get("governed_truth_bundle") or {})
    packet_families = dict(pack.get("packet_families") or {})
    packet_specimens = dict(specimens.get("packet_specimens") or {})
    hub_status = _hub_source_status()
    fleet_status = _fleet_source_status()
    projection_gaps = _projection_gaps(hub_status, fleet_status)
    contribution_state = "ready" if fleet_status.get("participation_status") == "pass" and fleet_status.get("sponsor_session_projection_available") else "hold"
    participation_entitlement_state = "ready" if contribution_state == "ready" and hub_status.get("entitlement_journal_projection_available") else "hold"
    channel_reward_state = "ready" if contribution_state == "ready" and hub_status.get("reward_journal_projection_available") and not any(gap["gap_id"].startswith("missing_hub_or_fleet_") for gap in projection_gaps) else "hold"
    hold_reasons = {gap["gap_id"]: gap["hold_reason"] for gap in projection_gaps}
    source_truth_status = {
        "hub_reusable_account_flows_receipt": hub_status,
        "fleet_participation_lane_receipts": fleet_status,
    }
    packet_states = {
        "contribution_followthrough:participant": contribution_state,
        "participation_entitlement_followthrough": participation_entitlement_state,
        "channel_reward_followthrough": channel_reward_state,
    }
    packet_hold_keys = {
        "contribution_followthrough:participant": ["fleet_participation_receipt_window_blocked", "missing_sponsor_session_receipt_projection"],
        "participation_entitlement_followthrough": ["fleet_participation_receipt_window_blocked", "missing_entitlement_journal_projection"],
        "channel_reward_followthrough": ["missing_hub_or_fleet_channel_ref_projection", "missing_hub_or_fleet_reward_publication_projection"],
    }
    return {
        "contract_name": "ea.next90_m129_participation_followthrough_packets",
        "status": "passed",
        "proof_kind": "repo_local_packet_contract",
        "package_proof": {
            "package_id": str(pack.get("package_id") or "").strip(),
            "title": str(pack.get("title") or "").strip(),
            "task": str(pack.get("title") or "").strip(),
            "milestone_id": int(pack.get("milestone_id") or 0),
            "frontier_id": 8620875598,
            "allowed_paths": ["scripts", "feedback", "docs"],
            "owned_surfaces": list(pack.get("owned_surfaces") or []),
        },
        "truth_bundle": {
            "bundle_id": str(bundle.get("bundle_id") or "").strip(),
            "source_anchor_ids": list(bundle.get("source_anchor_ids") or []),
        },
        "source_truth_status": source_truth_status,
        "projection_gaps": projection_gaps,
        "packets": {
            packet_name: {
                "state": packet_states[packet_name],
                "packet_kind": str(dict(packet_specimens.get(packet_name) or {}).get("packet_kind") or packet_name),
                "truth_bundle_id": str(bundle.get("bundle_id") or "").strip(),
                "required_source_anchors": list(dict(packet_families.get(packet_name) or {}).get("required_source_anchors") or []),
                "required_sections": list(dict(packet_families.get(packet_name) or {}).get("required_sections") or []),
                "required_fields": list(dict(packet_specimens.get(packet_name) or {}).get("required_fields") or []),
                "source_packet_fields": list(dict(packet_specimens.get(packet_name) or {}).get("source_packet_fields") or []),
                "example": dict(dict(packet_specimens.get(packet_name) or {}).get("example") or {}),
                "hold_reasons": [hold_reasons[key] for key in packet_hold_keys[packet_name] if key in hold_reasons],
                "proof_artifacts": [str(item) for item in handoff.get("proof_artifacts") or []],
            }
            for packet_name in (
                "contribution_followthrough:participant",
                "participation_entitlement_followthrough",
                "channel_reward_followthrough",
            )
        },
        "guardrails": {
            "claim_guard_rules": list(dict(pack.get("proof_guardrails") or {}).get("claim_guard_rules") or []),
            "runtime_safety_markers": list(dict(pack.get("proof_guardrails") or {}).get("runtime_safety_markers") or []),
            "active_package_status": str(handoff.get("status") or ""),
        },
    }

def materialize(*, generated_at: str | None = None) -> dict[str, Any]:
    payload = build_payload()
    payload["generated_at"] = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return payload

def main() -> int:
    PROOF_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = materialize()
    PROOF_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(PROOF_PATH)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
