from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml
from app.yaml_inputs import load_yaml_dict


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer_organizer_packets" / "CHUMMER_ORGANIZER_PACKET_PACK.yaml"
SPECIMENS_PATH = ROOT / "docs" / "chummer_organizer_packets" / "ORGANIZER_PACKET_SPECIMENS.yaml"
PROOF_PATH = ROOT / ".codex-studio" / "published" / "NEXT90_M118_EA_ORGANIZER_PACKETS.generated.json"
MATERIALIZER_PATH = ROOT / "scripts" / "materialize_next90_m118_ea_organizer_packets.py"
HANDOFF_CLOSEOUT_PATH = ROOT / "docs" / "chummer_organizer_packets" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
QUEUE_STAGING_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
DESIGN_QUEUE_STAGING_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
SOURCE_ANCHOR_IDS = [
    "community_scale_audit_schema",
    "organizer_boundary_policy",
    "hub_organizer_ops_verifier",
    "hub_creator_publication_verifier",
    "fleet_weekly_governor_packet",
    "fleet_support_case_packets",
    "ea_operator_safe_baseline",
]
PACKET_FAMILY_DETAILS = {
    "organizer_followthrough:ea": {
        "required_sections": [
            "packet_identity",
            "source_packet_links",
            "event_or_roster_summary",
            "publication_posture",
            "support_followthrough_gate",
            "next_safe_action",
        ],
        "required_fields": [
            "packet_id",
            "truth_bundle_id",
            "source_packet_ids",
            "operation_family",
            "event_or_roster_summary",
            "publication_posture",
            "support_followthrough_gate",
            "next_safe_action",
        ],
        "source_packet_fields": [
            "CommunityScaleAuditPacket.packet_id",
            "CommunityScaleAuditPacket.operation_family",
            "CommunityScaleAuditPacket.support_case_ref",
            "SUPPORT_CASE_PACKETS.generated.json.followthrough_receipt_gates.required_gates",
            "SUPPORT_CASE_PACKETS.generated.json.packets[].packet_id",
        ],
    },
    "event_prep_packets": {
        "required_sections": [
            "packet_identity",
            "prep_scope",
            "dependency_window",
            "publication_readiness",
            "blocker_holds",
            "handoff_receipts",
        ],
        "required_fields": [
            "packet_id",
            "truth_bundle_id",
            "source_packet_ids",
            "prep_scope",
            "dependency_window",
            "publication_readiness",
            "blocker_holds",
            "handoff_receipts",
        ],
        "source_packet_fields": [
            "CommunityScaleAuditPacket.packet_id",
            "WEEKLY_GOVERNOR_PACKET.generated.json.decision_alignment.actual_action",
            "WEEKLY_GOVERNOR_PACKET.generated.json.public_status_copy.state",
            "SUPPORT_CASE_PACKETS.generated.json.summary.needs_human_response",
            "CHUMMER_OPERATOR_SAFE_PACKET_PACK.yaml.packet_families.gm_prep_packets.state",
        ],
    },
}
PROOF_ARTIFACTS = [
    "docs/chummer_organizer_packets/CHUMMER_ORGANIZER_PACKET_PACK.yaml",
    "docs/chummer_organizer_packets/ORGANIZER_PACKET_SPECIMENS.yaml",
    "docs/chummer_organizer_packets/README.md",
    "docs/chummer_organizer_packets/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
    "scripts/materialize_next90_m118_ea_organizer_packets.py",
    "scripts/verify_next90_m118_ea_organizer_packets.py",
    "tests/test_next90_m118_ea_organizer_packets.py",
    ".codex-studio/published/NEXT90_M118_EA_ORGANIZER_PACKETS.generated.json",
    "feedback/2026-05-05-next90-m118-ea-organizer-followthrough-progress.md",
]


def _yaml(path: Path) -> dict:
    return load_yaml_dict(path)


def _json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _materializer_module():
    spec = importlib.util.spec_from_file_location("ea_next90_m118_materializer", MATERIALIZER_PATH)
    assert spec is not None and spec.loader is not None, MATERIALIZER_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pack_identity_and_scope() -> None:
    pack = _yaml(PACK_PATH)
    assert pack.get("contract_name") == "ea.chummer_organizer_packet_pack"
    assert pack.get("package_id") == "next90-m118-ea-organizer-followthrough"
    assert int(pack.get("milestone_id") or 0) == 118
    assert list(pack.get("owned_surfaces") or []) == ["organizer_followthrough:ea", "event_prep_packets"]


def test_specimens_share_the_same_truth_bundle() -> None:
    pack = _yaml(PACK_PATH)
    specimens = _yaml(SPECIMENS_PATH)
    assert specimens.get("shared_truth_bundle_id") == dict(pack.get("governed_truth_bundle") or {}).get("bundle_id")
    assert specimens.get("status") == pack.get("status")
    assert list(dict(pack.get("governed_truth_bundle") or {}).get("source_anchor_ids") or []) == SOURCE_ANCHOR_IDS


def test_materializer_rebuilds_current_generated_receipt() -> None:
    module = _materializer_module()
    proof = _json(PROOF_PATH)
    assert module.without_generated_at(proof) == module.build_payload()


def test_generated_receipt_marks_both_packets_ready() -> None:
    pack = _yaml(PACK_PATH)
    proof = _json(PROOF_PATH)
    guardrails = dict(proof.get("guardrails") or {})
    packets = dict(proof.get("packets") or {})
    assert list(dict(proof.get("truth_bundle") or {}).get("source_anchor_ids") or []) == SOURCE_ANCHOR_IDS
    assert list(guardrails.get("claim_guard_rules") or []) == list(dict(pack.get("proof_guardrails") or {}).get("claim_guard_rules") or [])
    assert dict(guardrails.get("fail_closed_posture") or {}) == dict(pack.get("fail_closed_posture") or {})
    assert list(guardrails.get("prohibited_behaviors") or []) == list(pack.get("prohibited_behaviors") or [])
    assert guardrails.get("active_package_status") == "active_package_proven"
    for packet_name, expected in PACKET_FAMILY_DETAILS.items():
        packet = dict(packets.get(packet_name) or {})
        assert packet.get("state") == "ready"
        assert packet.get("packet_kind") == packet_name
        assert list(packet.get("required_source_anchors") or []) == list(
            dict(pack.get("packet_families") or {}).get(packet_name, {}).get("required_source_anchors") or []
        )
        assert list(packet.get("required_sections") or []) == expected["required_sections"]
        assert list(packet.get("required_fields") or []) == expected["required_fields"]
        assert list(packet.get("source_packet_fields") or []) == expected["source_packet_fields"]
        assert [str(item) for item in packet.get("proof_artifacts") or []] == PROOF_ARTIFACTS
    assert proof.get("status") == "passed"


def test_generated_receipt_stays_worker_safe() -> None:
    proof_text = PROOF_PATH.read_text(encoding="utf-8").lower()
    feedback_text = (ROOT / "feedback" / "2026-05-05-next90-m118-ea-organizer-followthrough-progress.md").read_text(encoding="utf-8").lower()
    for marker in (
        "task_local_telemetry",
        "active_run_handoff",
        "/var/lib/codex-fleet",
        "supervisor status",
        "supervisor eta",
        "operator telemetry",
    ):
        assert marker not in proof_text
        assert marker not in feedback_text


def test_package_authority_matches_queue_registry_and_handoff() -> None:
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    queue = _yaml(QUEUE_STAGING_PATH)
    design_queue = _yaml(DESIGN_QUEUE_STAGING_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)

    queue_row = next(item for item in queue.get("items") or [] if dict(item).get("package_id") == "next90-m118-ea-organizer-followthrough")
    design_queue_row = next(item for item in design_queue.get("items") or [] if dict(item).get("package_id") == "next90-m118-ea-organizer-followthrough")
    milestone = next(item for item in registry.get("milestones") or [] if int(dict(item).get("id") or 0) == 118)
    work_task = next(item for item in milestone.get("work_tasks") or [] if str(dict(item).get("id")) == "118.3")

    assert handoff.get("status") == "active_package_proven"
    assert handoff.get("package_id") == "next90-m118-ea-organizer-followthrough"
    assert [str(item) for item in handoff.get("proof_artifacts") or []] == PROOF_ARTIFACTS
    assert [str(item) for item in handoff.get("completed_outputs") or []] == PROOF_ARTIFACTS
    assert [str(dict(item).get("source_anchor_id") or "") for item in handoff.get("shared_truth_runtime_sources") or []] == SOURCE_ANCHOR_IDS
    assert dict(handoff.get("canonical_authority") or {}).get("queue_package") == "next90-m118-ea-organizer-followthrough status=complete"
    assert dict(handoff.get("canonical_authority") or {}).get("registry_work_task") == "118.3 status=complete owner=executive-assistant"
    assert queue_row["status"] == design_queue_row["status"] == "complete"
    assert queue_row["title"] == design_queue_row["title"] == "Compile organizer packets, event prep, and followthrough from governed operations truth."
    assert queue_row["task"] == design_queue_row["task"] == "Compile organizer packets, event prep, and followthrough from governed operations truth."
    assert queue_row["repo"] == design_queue_row["repo"] == "executive-assistant"
    assert queue_row["wave"] == design_queue_row["wave"] == "W13"
    assert str(queue_row["work_task_id"]) == str(design_queue_row["work_task_id"]) == "118.3"
    assert work_task["owner"] == "executive-assistant"
    assert work_task["title"] == "Compile organizer packets, event prep, and followthrough from governed operations truth."


def _run_direct() -> int:
    failed = 0
    ran = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        ran += 1
        try:
            func()
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"ran={ran} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_direct())
