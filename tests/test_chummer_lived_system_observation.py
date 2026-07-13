from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

from scripts import materialize_chummer_lived_system_observation as materialize
from scripts import verify_chummer_lived_system_observation as verifier


NOW = "2026-07-14T00:00:00Z"
OLDER = "2026-07-12T06:35:08Z"
NEWER = "2026-07-13T20:59:42Z"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _base_receipts() -> dict[str, dict[str, Any]]:
    return {
        "scorecard": {
            "contract_name": "chummer.campaign_operability_scorecard",
            "generated_at_utc": NOW,
            "status": "pass",
            "verdict": "CAMPAIGN_OPERABILITY_READY",
            "summary": {"score_3_count": 36, "below_3_count": 0},
        },
        "final_gold_graph": {
            "contract_name": "chummer.final_gold_graph",
            "generated_at_utc": NOW,
            "status": "pass",
            "verdict": "GOLD_READY",
        },
        "weekly_pulse": {
            "contract_name": "chummer.weekly_product_pulse",
            "generated_at": NOW,
            "flagship_readiness": {"proof_status": "pass"},
            "release_health": {"state": "ready"},
            "governor_decisions": [{"action": "launch_expand"}],
        },
        "fleet_flagship": {
            "contract_name": "fleet.flagship_product_readiness",
            "generated_at": NOW,
            "status": "pass",
            "scoped_status": "pass",
        },
        "fleet_journeys": {
            "contract_name": "fleet.journey_gates",
            "generated_at": NOW,
            "summary": {
                "overall_state": "ready",
                "total_journey_count": 6,
                "ready_count": 6,
                "warning_count": 0,
                "blocked_count": 0,
            },
        },
        "desktop": {
            "contract_name": "chummer6-ui.desktop_executable_exit_gate",
            "generated_at": NOW,
            "status": "pass",
        },
        "windows_desktop": {
            "contract_name": "chummer6-ui.windows_desktop_exit_gate",
            "generated_at": NOW,
            "status": "pass",
        },
        "windows_visual": {
            "contract_name": "chummer.windows_installer_visual_audit",
            "generated_at_utc": NOW,
            "status": "pass",
        },
        "release_ready": {
            "contract_name": "chummer.release_ready",
            "generated_at_utc": NOW,
            "status": "pass",
            "verdict": "RELEASE_READY",
            "failures": [],
        },
        "channel": {
            "contract_name": "Chummer.Hub.Registry.Contracts",
            "generated_at": NOW,
            "status": "published",
            "channel": "preview",
            "version": "run-1",
            "supportability": "preview_supported",
            "rollout": "promoted_preview",
            "artifacts": [
                {
                    "artifactId": "avalonia-win-x64-installer",
                    "fileName": "chummer.exe",
                    "platform": "windows",
                    "kind": "installer",
                    "sha256": "a" * 64,
                }
            ],
        },
    }


def _fixture_paths(tmp_path: Path) -> tuple[materialize.ObservationPaths, dict[str, Path]]:
    mirror = tmp_path / "mirror"
    canonical = tmp_path / "canonical"
    receipts = _base_receipts()
    clear_text = "# Chummer\nBLK-010 is cleared.\n"

    filenames = {
        "readme": "README.md",
        "group_blockers": "GROUP_BLOCKERS.md",
        "closeout": "CAMPAIGN_OS_FLAGSHIP_CLOSEOUT.md",
        "scorecard": "CAMPAIGN_OPERABILITY_SCORECARD.generated.json",
        "final_gold_graph": "FINAL_GOLD_GRAPH.generated.json",
        "weekly_pulse": "WEEKLY_PRODUCT_PULSE.generated.json",
    }
    for key in ("readme", "group_blockers", "closeout"):
        _write_text(mirror / filenames[key], clear_text)
        _write_text(canonical / filenames[key], clear_text)
    for key in ("scorecard", "final_gold_graph", "weekly_pulse"):
        _write_json(mirror / filenames[key], receipts[key])
        _write_json(canonical / filenames[key], receipts[key])

    paths_by_key = {
        "fleet_flagship": tmp_path / "fleet-flagship.json",
        "fleet_journeys": tmp_path / "fleet-journeys.json",
        "desktop": tmp_path / "desktop.json",
        "windows_desktop": tmp_path / "windows-desktop.json",
        "windows_visual": tmp_path / "windows-visual.json",
        "release_ready": tmp_path / "release-ready.json",
        "registry_channel": tmp_path / "registry-channel.json",
        "portal_channel": tmp_path / "portal-channel.json",
    }
    for key in (
        "fleet_flagship",
        "fleet_journeys",
        "desktop",
        "windows_desktop",
        "windows_visual",
        "release_ready",
    ):
        _write_json(paths_by_key[key], receipts[key])
    _write_json(paths_by_key["registry_channel"], receipts["channel"])
    _write_json(paths_by_key["portal_channel"], receipts["channel"])

    paths = materialize.ObservationPaths(
        ea_mirror_product_root=mirror,
        canonical_product_root=canonical,
        fleet_flagship_readiness=paths_by_key["fleet_flagship"],
        fleet_journey_gates=paths_by_key["fleet_journeys"],
        desktop_executable_exit_gate=paths_by_key["desktop"],
        windows_desktop_exit_gate=paths_by_key["windows_desktop"],
        windows_installer_visual_audit=paths_by_key["windows_visual"],
        release_ready=paths_by_key["release_ready"],
        registry_release_channel=paths_by_key["registry_channel"],
        portal_release_channel=paths_by_key["portal_channel"],
    )
    paths_by_key["mirror"] = mirror
    paths_by_key["canonical"] = canonical
    return paths, paths_by_key


def _check_map(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["key"]): item for item in receipt["checks"]}


def _all_status_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "status":
                values.append(str(item))
            values.extend(_all_status_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_all_status_values(item))
    return values


def test_consistent_observation_is_non_authoritative_and_hash_bound(tmp_path: Path) -> None:
    paths, _ = _fixture_paths(tmp_path)

    receipt = materialize.build_observation(paths, generated_at=NOW)

    assert receipt["status"] == "consistent"
    assert receipt["authoritative"] is False
    assert receipt["release_decision"] is None
    assert receipt["execution_policy"] == {
        "filesystem_input_mode": "read_only",
        "output_write_mode": "atomic_receipt_only",
        "network_actions": 0,
        "provider_actions": 0,
        "docker_actions": 0,
        "source_mutations": 0,
    }
    assert tuple(item["key"] for item in receipt["input_bindings"]) == materialize.required_input_keys()
    assert all(len(str(item["sha256"])) == 64 for item in receipt["input_bindings"])
    assert set(_all_status_values(receipt)) <= materialize.ALLOWED_STATUSES
    assert receipt["findings"] == []


def test_observation_detects_current_regression_shapes_without_making_decision(tmp_path: Path) -> None:
    paths, files = _fixture_paths(tmp_path)
    scorecard = _base_receipts()["scorecard"]
    scorecard["generated_at_utc"] = OLDER
    gold = _base_receipts()["final_gold_graph"]
    gold["generated_at_utc"] = OLDER
    _write_json(files["canonical"] / "CAMPAIGN_OPERABILITY_SCORECARD.generated.json", scorecard)
    _write_json(files["mirror"] / "CAMPAIGN_OPERABILITY_SCORECARD.generated.json", scorecard)
    _write_json(files["canonical"] / "FINAL_GOLD_GRAPH.generated.json", gold)
    _write_json(files["mirror"] / "FINAL_GOLD_GRAPH.generated.json", gold)

    _write_text(files["canonical"] / "README.md", "BLK-010 remains active.\n")
    _write_text(files["mirror"] / "README.md", "BLK-010 remains active.\n")
    _write_text(files["canonical"] / "GROUP_BLOCKERS.md", "BLK-010 is cleared.\n")
    _write_text(files["mirror"] / "GROUP_BLOCKERS.md", "BLK-010 is cleared.\n")
    _write_text(files["canonical"] / "CAMPAIGN_OS_FLAGSHIP_CLOSEOUT.md", "BLK-010 is cleared.\n")
    _write_text(files["mirror"] / "CAMPAIGN_OS_FLAGSHIP_CLOSEOUT.md", "BLK-010 is cleared.\n")

    canonical_pulse = _base_receipts()["weekly_pulse"]
    canonical_pulse.update(
        {
            "generated_at": NEWER,
            "flagship_readiness": {"proof_status": "fail"},
            "release_health": {"state": "needs_attention"},
            "governor_decisions": [{"action": "freeze_launch"}],
        }
    )
    mirror_pulse = dict(canonical_pulse)
    mirror_pulse["generated_at"] = OLDER
    mirror_pulse["flagship_readiness"] = {"proof_status": "pass"}
    _write_json(files["canonical"] / "WEEKLY_PRODUCT_PULSE.generated.json", canonical_pulse)
    _write_json(files["mirror"] / "WEEKLY_PRODUCT_PULSE.generated.json", mirror_pulse)

    for key, observed_value in (
        ("fleet_flagship", "fail"),
        ("desktop", "fail"),
        ("windows_desktop", "failed"),
        ("windows_visual", "fail"),
    ):
        payload = _base_receipts()[key]
        payload["generated_at"] = NEWER
        payload["generated_at_utc"] = NEWER
        payload["status"] = observed_value
        if key == "fleet_flagship":
            payload["scoped_status"] = "fail"
        _write_json(files[key], payload)
    release_ready = _base_receipts()["release_ready"]
    release_ready.update(
        {
            "generated_at_utc": NEWER,
            "status": "fail",
            "verdict": "NOT_RELEASE_READY",
            "failures": ["desktop proof missing"],
        }
    )
    _write_json(files["release_ready"], release_ready)

    portal_channel = _base_receipts()["channel"]
    portal_channel["version"] = "run-2"
    portal_channel["artifacts"] = []
    _write_json(files["portal_channel"], portal_channel)

    receipt = materialize.build_observation(paths, generated_at=NOW)
    checks = _check_map(receipt)
    finding_codes = {item["code"] for item in receipt["findings"]}

    assert receipt["status"] == "attention_required"
    assert receipt["authoritative"] is False
    assert receipt["release_decision"] is None
    for key in (
        "mirror_canonical_alignment",
        "canonical_blk010_narrative_alignment",
        "campaign_operability_scorecard_freshness",
        "final_gold_graph_freshness",
        "desktop_proof_posture",
        "release_ready_posture",
        "release_channel_projection_alignment",
    ):
        assert checks[key]["status"] == "attention_required"
    assert {
        "mirror_canonical_drift",
        "canonical_blk010_narrative_contradiction",
        "campaign_operability_scorecard_freshness_superseded",
        "final_gold_graph_freshness_superseded",
        "desktop_proof_not_green",
        "release_ready_not_green",
        "release_channel_split_brain",
    } <= finding_codes
    assert set(_all_status_values(receipt)) <= materialize.ALLOWED_STATUSES

    output = tmp_path / "EA_CHUMMER_LIVED_SYSTEM_OBSERVATION.generated.json"
    materialize._atomic_write_json(output, receipt)
    assert verifier.verify(output) == []


def test_invalid_or_missing_owner_input_fails_closed(tmp_path: Path) -> None:
    paths, files = _fixture_paths(tmp_path)
    files["release_ready"].unlink()

    receipt = materialize.build_observation(paths, generated_at=NOW)

    assert receipt["status"] == "invalid_inputs"
    assert _check_map(receipt)["input_integrity"]["status"] == "invalid_inputs"
    binding = next(item for item in receipt["input_bindings"] if item["key"] == "release_ready")
    assert "error" in binding
    assert receipt["release_decision"] is None

    output = tmp_path / "invalid-observation.json"
    materialize._atomic_write_json(output, receipt)
    assert verifier.verify(output) == []


def test_atomic_writer_replaces_with_mode_0600(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    output.write_text("old", encoding="utf-8")
    output.chmod(0o644)

    materialize._atomic_write_json(output, {"value": "new"})

    assert json.loads(output.read_text(encoding="utf-8")) == {"value": "new"}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(f".{output.name}.*.tmp"))


def test_verifier_rejects_authority_and_action_overclaim(tmp_path: Path) -> None:
    paths, _ = _fixture_paths(tmp_path)
    receipt = materialize.build_observation(paths, generated_at=NOW)
    receipt["authoritative"] = True
    receipt["release_decision"] = "promote"
    receipt["execution_policy"]["provider_actions"] = 1
    output = tmp_path / "overclaim.json"
    materialize._atomic_write_json(output, receipt)

    issues = verifier.verify(output)

    assert "authoritative must be false" in issues
    assert "release_decision must be present and null" in issues
    assert "execution_policy.provider_actions must be zero" in issues


def test_verifier_detects_hash_bound_input_change(tmp_path: Path) -> None:
    paths, files = _fixture_paths(tmp_path)
    receipt = materialize.build_observation(paths, generated_at=NOW)
    output = tmp_path / "observation.json"
    materialize._atomic_write_json(output, receipt)
    _write_text(files["canonical"] / "README.md", "BLK-010 changed after observation.\n")

    issues = verifier.verify(output)

    assert "hash-bound input canonical_readme content changed" in issues
    assert "hash-bound input canonical_readme size changed" in issues
