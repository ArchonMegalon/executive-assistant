from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_flagship_release_readiness.py"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_flagship_release_readiness_gate_fails_closed_on_blocked_journey(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    _write_json(
        pulse,
        {
            "release_health": {"state": "blocked"},
            "flagship_readiness": {"state": "clear"},
            "journey_gate_health": {"state": "blocked", "blocked_count": 1},
            "supporting_signals": {"launch_readiness": "Hold launch expansion pending cross-host journey coverage."},
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, {"status": "pass"})
    _write_json(journey, {"summary": {"overall_state": "blocked", "blocked_count": 1}})

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--pulse",
            str(pulse),
            "--flagship-receipt",
            str(receipt),
            "--browser-proof",
            str(browser),
            "--journey-gates",
            str(journey),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "weekly release_health is blocked" in result.stdout
    assert "fleet journey gates are blocked" in result.stdout


def test_flagship_release_readiness_gate_passes_when_receipts_and_journeys_are_clear(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    _write_json(
        pulse,
        {
            "release_health": {"state": "clear"},
            "flagship_readiness": {"state": "clear"},
            "journey_gate_health": {"state": "ready", "blocked_count": 0},
            "supporting_signals": {"launch_readiness": "Release truth is clear enough to widen claims."},
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, {"status": "pass"})
    _write_json(journey, {"summary": {"overall_state": "ready", "blocked_count": 0}})

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--pulse",
            str(pulse),
            "--flagship-receipt",
            str(receipt),
            "--browser-proof",
            str(browser),
            "--journey-gates",
            str(journey),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert '"status": "pass"' in result.stdout
