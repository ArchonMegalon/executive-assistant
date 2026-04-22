from __future__ import annotations

import json
from pathlib import Path

from scripts.materialize_ea_browser_workflow_proof import build_receipt


SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")


def _write_seed(root: Path) -> None:
    (root / SEED).parent.mkdir(parents=True, exist_ok=True)
    (root / SEED).write_text(
        json.dumps(
            {
                "product": "executive-assistant",
                "release_claim": {"summary": "browser proof must match the flagship claim"},
                "browser_workflow_proof": {
                    "expected_browser_signals": ["/register", "/app/today"],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_browser_workflow_proof_passes_when_both_lanes_pass(tmp_path: Path) -> None:
    _write_seed(tmp_path)

    def fake_runner(root: Path, *, python_bin: str, test_file: str, cases: list[str], real_browser: bool) -> dict[str, object]:
        assert root == tmp_path
        return {
            "status": "pass",
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 0,
            "duration_seconds": 1.0,
            "output_excerpt": ["2 passed"],
            "limitations": [],
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "pass"
    assert receipt["contract_name"] == "ea.browser_workflow_proof"
    assert receipt["blocking_reasons"] == []
    assert receipt["current_limitations"] == []
    assert receipt["expected_browser_signals"] == ["/register", "/app/today"]


def test_browser_workflow_proof_stays_preview_only_when_real_browser_lane_is_skipped(tmp_path: Path) -> None:
    _write_seed(tmp_path)

    def fake_runner(root: Path, *, python_bin: str, test_file: str, cases: list[str], real_browser: bool) -> dict[str, object]:
        status = "preview_only" if real_browser else "pass"
        limitations = ["uvicorn is not installed in the selected Python environment"] if real_browser else []
        return {
            "status": status,
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 5 if real_browser else 0,
            "duration_seconds": 1.0,
            "output_excerpt": ["skipped"] if real_browser else ["4 passed"],
            "limitations": limitations,
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "preview_only"
    assert receipt["blocking_reasons"] == []
    assert receipt["current_limitations"] == ["uvicorn is not installed in the selected Python environment"]


def test_browser_workflow_proof_blocks_when_source_backed_lane_fails(tmp_path: Path) -> None:
    _write_seed(tmp_path)

    def fake_runner(root: Path, *, python_bin: str, test_file: str, cases: list[str], real_browser: bool) -> dict[str, object]:
        if real_browser:
            return {
                "status": "pass",
                "command": "pytest",
                "cwd": root.as_posix(),
                "python_bin": python_bin,
                "test_file": test_file,
                "cases": cases,
                "exit_code": 0,
                "duration_seconds": 1.0,
                "output_excerpt": ["2 passed"],
                "limitations": [],
            }
        return {
            "status": "blocked",
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 1,
            "duration_seconds": 1.0,
            "output_excerpt": ["4 failed"],
            "limitations": ["application import path is broken"],
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "blocked"
    assert "source-backed browser journey proof is not passing" in receipt["blocking_reasons"]
    assert receipt["current_limitations"] == ["application import path is broken"]
