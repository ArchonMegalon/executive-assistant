from __future__ import annotations

import json
from pathlib import Path

import yaml
from app.yaml_inputs import load_yaml_dict


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer_launch_followthrough" / "CHUMMER_LAUNCH_FOLLOWTHROUGH_PACK.yaml"
SPECIMENS_PATH = ROOT / "docs" / "chummer_launch_followthrough" / "PUBLIC_AND_REPORTER_FOLLOWTHROUGH_SPECIMENS.yaml"
HANDOFF_CLOSEOUT_PATH = ROOT / "docs" / "chummer_launch_followthrough" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
FEEDBACK_PATH = ROOT / "feedback" / "2026-05-05-next90-m120-ea-launch-pulse-followthrough-progress.md"
QUEUE_STAGING_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
DESIGN_QUEUE_STAGING_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
FLEET_LAUNCH_PULSE_PATH = Path("/docker/fleet/.codex-studio/published/NEXT90_M120_FLEET_LAUNCH_PULSE.generated.json")
FLEET_WEEKLY_GOVERNOR_PATH = Path("/docker/fleet/.codex-studio/published/WEEKLY_GOVERNOR_PACKET.generated.json")
FLEET_SUPPORT_PACKETS_PATH = Path("/docker/fleet/.codex-studio/published/SUPPORT_CASE_PACKETS.generated.json")
RELEASE_CHANNEL_PATH = Path("/docker/chummercomplete/chummer-hub-registry/.codex-studio/published/RELEASE_CHANNEL.generated.json")
SOURCE_ANCHOR_IDS = [
    "fleet_launch_pulse_packet",
    "fleet_weekly_governor_packet",
    "registry_release_channel",
    "fleet_support_case_packets",
    "design_launch_health_language",
    "design_public_release_experience",
    "ea_governor_packet_baseline",
]
QUEUE_TITLE = "Draft reporter, operator, and public followthrough from launch-pulse truth"
QUEUE_TASK = "Draft reporter, operator, and public followthrough from launch-pulse truth."
REGISTRY_TITLE = "Draft reporter, operator, and public followthrough from launch-pulse truth without inventing release claims."
PROOF_ARTIFACTS = [
    "docs/chummer_launch_followthrough/CHUMMER_LAUNCH_FOLLOWTHROUGH_PACK.yaml",
    "docs/chummer_launch_followthrough/PUBLIC_AND_REPORTER_FOLLOWTHROUGH_SPECIMENS.yaml",
    "docs/chummer_launch_followthrough/README.md",
    "docs/chummer_launch_followthrough/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
    "tests/test_next90_m120_ea_launch_pulse_followthrough.py",
    "feedback/2026-05-05-next90-m120-ea-launch-pulse-followthrough-progress.md",
]


def _yaml(path: Path) -> dict:
    return load_yaml_dict(path)


def _json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def test_pack_identity_scope_and_anchor_contract() -> None:
    pack = _yaml(PACK_PATH)
    assert pack.get("contract_name") == "ea.chummer_launch_followthrough_pack"
    assert pack.get("package_id") == "next90-m120-ea-launch-pulse-followthrough"
    assert int(pack.get("milestone_id") or 0) == 120
    assert pack.get("wave") == "W14"
    assert pack.get("status") == "task_proven"
    assert pack.get("title") == REGISTRY_TITLE
    assert list(pack.get("owned_surfaces") or []) == ["launch_followthrough_drafts", "reporter_followthrough:public"]
    assert list(dict(pack.get("governed_truth_bundle") or {}).get("source_anchor_ids") or []) == SOURCE_ANCHOR_IDS


def test_specimens_share_truth_bundle_and_current_hold_posture() -> None:
    pack = _yaml(PACK_PATH)
    specimens = _yaml(SPECIMENS_PATH)
    launch_pulse = _json(FLEET_LAUNCH_PULSE_PATH)
    weekly_governor = _json(FLEET_WEEKLY_GOVERNOR_PATH)
    support_packets = _json(FLEET_SUPPORT_PACKETS_PATH)
    release_channel = _json(RELEASE_CHANNEL_PATH)

    assert specimens.get("shared_truth_bundle_id") == dict(pack.get("governed_truth_bundle") or {}).get("bundle_id")
    assert list(specimens.get("source_anchor_ids") or []) == SOURCE_ANCHOR_IDS

    launch_specimen = dict(specimens.get("launch_followthrough_draft_specimen") or {})
    reporter_specimen = dict(specimens.get("reporter_followthrough_specimen") or {})
    projection_bindings = dict(specimens.get("projection_bindings") or {})
    launch_bindings = dict(projection_bindings.get("launch_followthrough_drafts") or {})
    reporter_bindings = dict(projection_bindings.get("reporter_followthrough:public") or {})

    assert launch_specimen.get("state") == "hold"
    assert list(launch_bindings.get("launch_action_fields") or []) == [
        "NEXT90_M120_FLEET_LAUNCH_PULSE.generated.json.launch_pulse.governor_action",
        "WEEKLY_GOVERNOR_PACKET.generated.json.decision_alignment.actual_action",
        "WEEKLY_GOVERNOR_PACKET.generated.json.public_status_copy.headline",
        "WEEKLY_GOVERNOR_PACKET.generated.json.public_status_copy.body",
    ]
    assert str(dict(launch_specimen.get("launch_decision_window") or {}).get("operator_posture") or "").strip()
    assert str(dict(launch_specimen.get("launch_decision_window") or {}).get("public_status_headline") or "").strip()
    assert str(dict(launch_specimen.get("launch_decision_window") or {}).get("public_status_body") or "").strip()
    assert str(dict(launch_specimen.get("adoption_health_snapshot") or {}).get("state") or "").strip()
    assert str(dict(launch_specimen.get("adoption_health_snapshot") or {}).get("summary") or "").strip()
    assert str(dict(launch_specimen.get("proof_freshness_holds") or {}).get("state") or "").strip()
    assert isinstance(dict(launch_specimen.get("proof_freshness_holds") or {}).get("missing_input_count"), int)
    assert isinstance(dict(launch_specimen.get("proof_freshness_holds") or {}).get("stale_input_count"), int)

    assert reporter_specimen.get("state") == "hold"
    assert list(reporter_bindings.get("release_claim_fields") or []) == [
        "RELEASE_CHANNEL.generated.json.rolloutState",
        "RELEASE_CHANNEL.generated.json.fixAvailabilitySummary",
        "RELEASE_CHANNEL.generated.json.knownIssueSummary",
    ]
    assert str(dict(reporter_specimen.get("release_claim_guard") or {}).get("rollout_state") or "").strip()
    assert str(dict(reporter_specimen.get("public_status_alignment") or {}).get("launch_followthrough_state") or "").strip()
    assert str(dict(reporter_specimen.get("public_status_alignment") or {}).get("support_risk_state") or "").strip()
    assert str(dict(reporter_specimen.get("public_status_alignment") or {}).get("public_status_headline") or "").strip()
    assert isinstance(dict(reporter_specimen.get("support_followthrough_gate") or {}).get("reporter_ready_count"), int)
    assert isinstance(dict(reporter_specimen.get("support_followthrough_gate") or {}).get("needs_human_response_count"), int)
    assert str(dict(reporter_specimen.get("release_channel_posture") or {}).get("fix_availability_summary") or "").strip()
    assert str(dict(reporter_specimen.get("release_channel_posture") or {}).get("known_issue_summary") or "").strip()
    assert launch_pulse
    assert weekly_governor
    assert support_packets
    assert release_channel


def test_packet_family_contracts_stay_fail_closed() -> None:
    pack = _yaml(PACK_PATH)
    packets = dict(pack.get("packet_families") or {})
    launch_family = dict(packets.get("launch_followthrough_drafts") or {})
    reporter_family = dict(packets.get("reporter_followthrough:public") or {})
    fail_closed = dict(pack.get("fail_closed_posture") or {})

    assert launch_family.get("state") == "hold"
    assert reporter_family.get("state") == "hold"
    assert list(launch_family.get("required_sections") or []) == [
        "packet_identity",
        "launch_decision_window",
        "adoption_health_snapshot",
        "proof_freshness_holds",
        "public_copy_guardrails",
        "next_safe_actions",
    ]
    assert list(reporter_family.get("required_sections") or []) == [
        "packet_identity",
        "release_claim_guard",
        "public_status_alignment",
        "support_followthrough_gate",
        "release_channel_posture",
        "publish_hold_reason",
    ]
    assert "proof_freshness_blocked" in fail_closed
    assert "release_channel_drift" in fail_closed
    assert "support_gate_drift" in fail_closed


def test_package_authority_matches_queue_registry_and_handoff() -> None:
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    queue = _yaml(QUEUE_STAGING_PATH)
    design_queue = _yaml(DESIGN_QUEUE_STAGING_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)

    queue_row = next(item for item in queue.get("items") or [] if dict(item).get("package_id") == "next90-m120-ea-launch-pulse-followthrough")
    design_queue_row = next(item for item in design_queue.get("items") or [] if dict(item).get("package_id") == "next90-m120-ea-launch-pulse-followthrough")
    milestone = next(item for item in registry.get("milestones") or [] if int(dict(item).get("id") or 0) == 120)
    work_task = next(item for item in milestone.get("work_tasks") or [] if str(dict(item).get("id")) == "120.4")

    assert handoff.get("status") == "active_package_proven"
    assert [str(item) for item in handoff.get("proof_artifacts") or []] == PROOF_ARTIFACTS
    assert [str(item) for item in handoff.get("completed_outputs") or []] == PROOF_ARTIFACTS
    assert [str(dict(item).get("source_anchor_id") or "") for item in handoff.get("shared_truth_runtime_sources") or []] == SOURCE_ANCHOR_IDS
    assert dict(handoff.get("canonical_authority") or {}).get("queue_package") == "next90-m120-ea-launch-pulse-followthrough status=in_progress"
    assert dict(handoff.get("canonical_authority") or {}).get("registry_work_task") == "120.4 status=in_progress owner=executive-assistant"
    assert queue_row["status"] == design_queue_row["status"] == "in_progress"
    assert queue_row["repo"] == design_queue_row["repo"] == "executive-assistant"
    assert queue_row["wave"] == design_queue_row["wave"] == "W14"
    assert queue_row["title"] == design_queue_row["title"] == QUEUE_TITLE
    assert queue_row["task"] == design_queue_row["task"] == QUEUE_TASK
    assert list(queue_row["allowed_paths"]) == list(design_queue_row["allowed_paths"]) == ["skills", "feedback", "docs", "tests"]
    assert list(queue_row["owned_surfaces"]) == list(design_queue_row["owned_surfaces"]) == [
        "launch_followthrough_drafts",
        "reporter_followthrough:public",
    ]
    assert work_task["owner"] == "executive-assistant"
    assert work_task["title"] == REGISTRY_TITLE


def test_feedback_and_docs_stay_worker_safe() -> None:
    public_facing_text = "\n".join(
        [
            SPECIMENS_PATH.read_text(encoding="utf-8").lower(),
            FEEDBACK_PATH.read_text(encoding="utf-8").lower(),
        ]
    )
    for marker in (
        "task_local_telemetry",
        "active_run_handoff",
        "/var/lib/codex-fleet",
        "supervisor status",
        "supervisor eta",
        "operator telemetry",
        "codexea status",
        "codexea eta",
    ):
        assert marker not in public_facing_text


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
