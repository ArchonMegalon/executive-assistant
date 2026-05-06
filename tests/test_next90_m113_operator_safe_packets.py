from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml
from app.yaml_inputs import load_yaml_dict


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer_operator_safe_packets" / "CHUMMER_OPERATOR_SAFE_PACKET_PACK.yaml"
SPECIMENS_PATH = ROOT / "docs" / "chummer_operator_safe_packets" / "OPERATOR_SAFE_PACKET_SPECIMENS.yaml"
PROOF_PATH = ROOT / ".codex-studio" / "published" / "NEXT90_M113_OPERATOR_SAFE_PACKETS.generated.json"
MATERIALIZER_PATH = ROOT / "scripts" / "materialize_next90_m113_operator_safe_packets.py"
HANDOFF_CLOSEOUT_PATH = ROOT / "docs" / "chummer_operator_safe_packets" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
QUEUE_STAGING_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
DESIGN_QUEUE_STAGING_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")


def _yaml(path: Path) -> dict:
    return load_yaml_dict(path)


def _json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _materializer_module():
    spec = importlib.util.spec_from_file_location("ea_next90_m113_materializer", MATERIALIZER_PATH)
    assert spec is not None and spec.loader is not None, MATERIALIZER_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pack_identity_and_scope() -> None:
    pack = _yaml(PACK_PATH)
    assert pack.get("contract_name") == "ea.chummer_operator_safe_packet_pack"
    assert pack.get("package_id") == "next90-m113-executive-assistant-operator-safe-packets"
    assert int(pack.get("milestone_id") or 0) == 113
    assert list(pack.get("owned_surfaces") or []) == ["gm_prep_packets", "roster_movement_followthrough"]


def test_specimens_share_the_same_truth_bundle() -> None:
    pack = _yaml(PACK_PATH)
    specimens = _yaml(SPECIMENS_PATH)
    assert specimens.get("shared_truth_bundle_id") == dict(pack.get("governed_truth_bundle") or {}).get("bundle_id")
    assert specimens.get("status") == pack.get("status")


def test_materializer_rebuilds_current_generated_receipt() -> None:
    module = _materializer_module()
    proof = _json(PROOF_PATH)
    assert module.without_generated_at(proof) == module.build_payload()


def test_generated_receipt_marks_both_packets_ready() -> None:
    proof = _json(PROOF_PATH)
    packets = dict(proof.get("packets") or {})
    assert dict(packets.get("gm_prep_packets") or {}).get("state") == "ready"
    assert dict(packets.get("roster_movement_followthrough") or {}).get("state") == "ready"
    assert proof.get("status") == "passed"


def test_generated_receipt_stays_worker_safe() -> None:
    proof_text = PROOF_PATH.read_text(encoding="utf-8").lower()
    for marker in (
        "task_local_telemetry",
        "active_run_handoff",
        "/var/lib/codex-fleet",
        "supervisor status",
        "supervisor eta",
        "operator telemetry",
    ):
        assert marker not in proof_text


def test_closed_package_authority_matches_queue_registry_and_handoff() -> None:
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    queue = _yaml(QUEUE_STAGING_PATH)
    design_queue = _yaml(DESIGN_QUEUE_STAGING_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)

    queue_row = next(item for item in queue.get("items") or [] if dict(item).get("package_id") == "next90-m113-executive-assistant-operator-safe-packets")
    design_queue_row = next(item for item in design_queue.get("items") or [] if dict(item).get("package_id") == "next90-m113-executive-assistant-operator-safe-packets")
    milestone = next(item for item in registry.get("milestones") or [] if int(dict(item).get("id") or 0) == 113)
    work_task = next(item for item in milestone.get("work_tasks") or [] if str(dict(item).get("id")) == "113.5")

    assert handoff.get("status") == "ea_scope_complete"
    assert handoff.get("package_id") == "next90-m113-executive-assistant-operator-safe-packets"
    assert queue_row["status"] == design_queue_row["status"] == work_task["status"] == "complete"
    assert queue_row["landed_commit"] == design_queue_row["landed_commit"] == "38fdba5"
    assert queue_row["completion_action"] == design_queue_row["completion_action"] == "verify_closed_package_only"
    assert queue_row["do_not_reopen_reason"] == design_queue_row["do_not_reopen_reason"] == (
        "M113 executive-assistant operator-safe packets is complete; future shards must verify the EA packet pack, generated proof, focused verifier and test, canonical registry row, and queue rows instead of reopening the GM prep and roster followthrough slice."
    )


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
