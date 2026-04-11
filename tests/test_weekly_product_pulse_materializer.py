from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_weekly_product_pulse.py"
PULSE_PATH = Path(".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json")
SCORECARD_PATH = Path(".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml")
FLAGSHIP_RECEIPT_PATH = Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json")
JOURNEY_GATES_PATH = Path("/tmp/ea-weekly-pulse-journey-gates.generated.json")


def _seed_truth_sources(root: Path) -> None:
    (root / SCORECARD_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / FLAGSHIP_RECEIPT_PATH).parent.mkdir(parents=True, exist_ok=True)

    scorecard = {
        "product": "executive-assistant",
        "version": 1,
        "cadence": {"review": "weekly", "snapshot_owner": "product_governor", "publication": "internal_canon_first"},
        "scorecards": [
            {
                "id": "release_health",
                "metrics": [
                    {"name": "promoted_regressions_open", "target": 0, "source": "weekly pulse"},
                ],
            },
            {
                "id": "flagship_readiness",
                "metrics": [
                    {"name": "flagship_acceptance_surfaces_failing", "target": 0, "source": "receipt"},
                ],
            },
        ],
    }
    (root / SCORECARD_PATH).write_text(yaml.safe_dump(scorecard, sort_keys=False), encoding="utf-8")

    receipt = {
        "product": "executive-assistant",
        "surface": "flagship_release_control",
        "version": 1,
        "truth_plane": {
            "source": ".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md",
            "legacy_history": "MILESTONE.json",
        },
        "release_claim": {
            "summary": "EA can only claim flagship-grade release truth when the browser workflow proof and release asset verification agree with this gate seed.",
            "required_conditions": [],
        },
        "browser_workflow_proof": {
            "evidence_sources": [],
            "published_receipt": ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
            "published_receipt_present": False,
        },
        "status": "preview_only",
        "current_limitations": ["no published browser execution receipt is attached yet"],
    }
    (root / FLAGSHIP_RECEIPT_PATH).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    journey_gates = {
        "contract_name": "fleet.journey_gates",
        "contract_version": 1,
        "generated_at": "2026-04-10T15:00:38Z",
        "summary": {
            "overall_state": "blocked",
            "total_journey_count": 6,
            "ready_count": 3,
            "warning_count": 0,
            "blocked_count": 3,
            "recommended_action": "Resolve the blocking golden-journey gaps before widening publish claims.",
        },
        "journeys": [],
    }
    Path(JOURNEY_GATES_PATH).write_text(json.dumps(journey_gates, indent=2) + "\n", encoding="utf-8")


def test_weekly_product_pulse_materializer_writes_ea_native_pulse(tmp_path: Path) -> None:
    _seed_truth_sources(tmp_path)

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--scorecard",
            SCORECARD_PATH.as_posix(),
            "--journey-gates",
            str(JOURNEY_GATES_PATH),
            "--flagship-receipt",
            FLAGSHIP_RECEIPT_PATH.as_posix(),
            "--output",
            PULSE_PATH.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    pulse = json.loads((tmp_path / PULSE_PATH).read_text(encoding="utf-8"))

    assert pulse["contract_name"] == "ea.weekly_product_pulse"
    assert pulse["summary"].startswith("Executive Assistant remains in preview-only flagship posture:")
    assert pulse["active_wave"] == "EA flagship receipt closeout"
    assert pulse["active_wave_status"] == "active"
    assert pulse["release_truth_source"] == FLAGSHIP_RECEIPT_PATH.as_posix()
    assert pulse["journey_gate_source"] == str(JOURNEY_GATES_PATH)
    assert pulse["release_health"]["state"] == "blocked"
    assert pulse["flagship_readiness"]["state"] == "watch"
    assert pulse["journey_gate_health"]["state"] == "blocked"
    assert pulse["journey_gate_health"]["blocked_count"] == 3
    assert pulse["supporting_signals"]["journey_gate_source"] == str(JOURNEY_GATES_PATH)
    assert pulse["supporting_signals"]["flagship_release_receipt_source"] == FLAGSHIP_RECEIPT_PATH.as_posix()
    assert pulse["supporting_signals"]["launch_readiness"].startswith("Hold launch expansion")
    assert pulse["supporting_signals"]["overall_progress_percent"] == 50
    assert pulse["governor_decisions"]
    assert len(pulse["governor_decisions"]) == 2
