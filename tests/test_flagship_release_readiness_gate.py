from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_flagship_release_readiness.py"
REAL_SCOPE = ROOT / ".codex-design" / "repo" / "IMPLEMENTATION_SCOPE.md"

VALID_SCOPE_TEXT = (
    "mirrored `.codex-design/product/*`\n"
    "Guide/help/public projections must compile from mirrored design sources rather than assistant-local prompt lore.\n"
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_release_authority_inputs(
    manifest_path: Path,
    project_modes_path: Path,
    *,
    public_origin: str = "https://ea.example.test",
    public_origin_source: str = "EA_PUBLIC_APP_BASE_URL",
    deployment_id: str = "deploy-123",
    deployment_id_source: str = "explicit",
    dirty_worktree: bool = False,
) -> None:
    _write_json(
        manifest_path,
        {
            "contract_name": "ea.release_manifest.v1",
            "repository": "EA",
            "branch": "main",
            "tracking_branch": "origin/main",
            "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "deploy_context_generated_at": "2026-06-23T08:00:00Z",
            "deploy_context_branch": "main",
            "deploy_context_tracking_branch": "origin/main",
            "deploy_context_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "deployment_id": deployment_id,
            "deployment_id_source": deployment_id_source,
            "public_origin": public_origin,
            "public_origin_source": public_origin_source,
            "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
            "release_label": "deploy-123",
            "project_mode": "EA_CORE",
            "enabled_project_modes": ["EA_CORE"],
            "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
            "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
            "dirty_worktree": dirty_worktree,
        },
    )
    _write_json(project_modes_path, {"modes": [{"key": "EA_CORE"}]})


@pytest.fixture(autouse=True)
def _preserve_real_implementation_scope() -> None:
    original = REAL_SCOPE.read_text(encoding="utf-8")
    try:
        yield
    finally:
        REAL_SCOPE.write_text(original, encoding="utf-8")


def test_flagship_release_readiness_gate_fails_closed_on_blocked_journey(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    scope = tmp_path / "scope.md"
    manifest = tmp_path / "release_manifest.generated.json"
    project_modes = tmp_path / "PROJECT_MODES.generated.json"
    _write_release_authority_inputs(manifest, project_modes)
    _write_json(
        pulse,
        {
            "contract_name": "ea.weekly_product_pulse",
            "scorecard_source": ".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml",
            "release_truth_source": ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
            "release_health": {"state": "blocked"},
            "flagship_readiness": {"state": "clear"},
            "journey_gate_health": {"state": "blocked", "blocked_count": 1},
            "supporting_signals": {"launch_readiness": "Hold launch expansion pending cross-host journey coverage."},
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, {"status": "pass"})
    _write_json(journey, {"summary": {"overall_state": "blocked", "blocked_count": 1}})
    scope.write_text(VALID_SCOPE_TEXT, encoding="utf-8")

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
            "--implementation-scope",
            str(scope),
            "--release-manifest",
            str(manifest),
            "--project-modes",
            str(project_modes),
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
    scope = tmp_path / "scope.md"
    manifest = tmp_path / "release_manifest.generated.json"
    project_modes = tmp_path / "PROJECT_MODES.generated.json"
    _write_release_authority_inputs(manifest, project_modes)
    _write_json(
        pulse,
        {
            "contract_name": "ea.weekly_product_pulse",
            "scorecard_source": ".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml",
            "release_truth_source": ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
            "release_health": {"state": "clear"},
            "flagship_readiness": {"state": "clear"},
            "journey_gate_health": {"state": "ready", "blocked_count": 0},
            "supporting_signals": {"launch_readiness": "Release truth is clear enough to widen claims."},
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, {"status": "pass"})
    _write_json(journey, {"summary": {"overall_state": "ready", "blocked_count": 0}})
    scope.write_text(VALID_SCOPE_TEXT, encoding="utf-8")

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
            "--implementation-scope",
            str(scope),
            "--release-manifest",
            str(manifest),
            "--project-modes",
            str(project_modes),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert '"status": "pass"' in result.stdout


def test_flagship_release_readiness_gate_accepts_committed_journey_snapshot_when_external_receipt_is_absent(
    tmp_path: Path,
) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "missing" / "journey.json"
    scope = tmp_path / "scope.md"
    manifest = tmp_path / "release_manifest.generated.json"
    project_modes = tmp_path / "PROJECT_MODES.generated.json"
    _write_release_authority_inputs(manifest, project_modes)
    _write_json(
        pulse,
        {
            "contract_name": "ea.weekly_product_pulse",
            "scorecard_source": ".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml",
            "release_truth_source": ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
            "journey_gate_source": journey.as_posix(),
            "release_health": {"state": "clear"},
            "flagship_readiness": {"state": "clear"},
            "journey_gate_health": {
                "state": "ready",
                "blocked_count": 0,
                "warning_count": 0,
                "recommended_action": "Journey proof is steady on current published evidence.",
            },
            "supporting_signals": {
                "launch_readiness": "Release truth is clear enough to widen claims.",
                "journey_gate_source": journey.as_posix(),
            },
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, {"status": "pass"})
    scope.write_text(VALID_SCOPE_TEXT, encoding="utf-8")

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
            "--implementation-scope",
            str(scope),
            "--release-manifest",
            str(manifest),
            "--project-modes",
            str(project_modes),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert '"status": "pass"' in result.stdout


def test_flagship_release_readiness_gate_fails_when_external_receipt_and_snapshot_are_absent(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "missing" / "journey.json"
    scope = tmp_path / "scope.md"
    manifest = tmp_path / "release_manifest.generated.json"
    project_modes = tmp_path / "PROJECT_MODES.generated.json"
    _write_release_authority_inputs(manifest, project_modes)
    _write_json(
        pulse,
        {
            "contract_name": "ea.weekly_product_pulse",
            "scorecard_source": ".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml",
            "release_truth_source": ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
            "release_health": {"state": "clear"},
            "flagship_readiness": {"state": "clear"},
            "supporting_signals": {"launch_readiness": "Release truth is clear enough to widen claims."},
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, {"status": "pass"})
    scope.write_text(VALID_SCOPE_TEXT, encoding="utf-8")

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
            "--implementation-scope",
            str(scope),
            "--release-manifest",
            str(manifest),
            "--project-modes",
            str(project_modes),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "journey gates summary missing or invalid" in result.stdout


def test_flagship_release_readiness_gate_rejects_unsourced_journey_snapshot_when_external_receipt_is_absent(
    tmp_path: Path,
) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "missing" / "journey.json"
    scope = tmp_path / "scope.md"
    _write_json(
        pulse,
        {
            "contract_name": "ea.weekly_product_pulse",
            "scorecard_source": ".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml",
            "release_truth_source": ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
            "release_health": {"state": "clear"},
            "flagship_readiness": {"state": "clear"},
            "journey_gate_health": {"state": "ready", "blocked_count": 0},
            "supporting_signals": {"launch_readiness": "Release truth is clear enough to widen claims."},
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, {"status": "pass"})
    scope.write_text(VALID_SCOPE_TEXT, encoding="utf-8")

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
            "--implementation-scope",
            str(scope),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "journey gates summary missing or invalid" in result.stdout


def test_flagship_release_readiness_gate_rejects_chummer_pulse_and_missing_ea_scope(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    scope = tmp_path / "scope.md"
    manifest = tmp_path / "release_manifest.generated.json"
    project_modes = tmp_path / "PROJECT_MODES.generated.json"
    _write_release_authority_inputs(manifest, project_modes)
    _write_json(
        pulse,
        {
            "contract_name": "chummer.weekly_product_pulse",
            "scorecard_source": "products/chummer/PRODUCT_HEALTH_SCORECARD.yaml",
            "release_truth_source": "",
            "release_health": {"state": "clear"},
            "flagship_readiness": {"state": "clear"},
            "journey_gate_health": {"state": "ready", "blocked_count": 0},
            "supporting_signals": {"launch_readiness": "Release truth is clear enough to widen claims."},
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, {"status": "pass"})
    _write_json(journey, {"summary": {"overall_state": "ready", "blocked_count": 0}})
    scope.write_text("mirrored `.codex-design/product/*`\n", encoding="utf-8")

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
            "--implementation-scope",
            str(scope),
            "--release-manifest",
            str(manifest),
            "--project-modes",
            str(project_modes),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "expected ea.weekly_product_pulse" in result.stdout
    assert "products/chummer/PRODUCT_HEALTH_SCORECARD.yaml" in result.stdout
    assert "implementation scope no longer requires mirrored design-source compilation" in result.stdout


def test_flagship_release_readiness_gate_rejects_failed_release_authority(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    scope = tmp_path / "scope.md"
    manifest = tmp_path / "release_manifest.generated.json"
    project_modes = tmp_path / "PROJECT_MODES.generated.json"
    _write_release_authority_inputs(
        manifest,
        project_modes,
        public_origin="",
        public_origin_source="missing",
        deployment_id="local-20260622T000000Z-aaaaaaaaaaaa",
        deployment_id_source="local_fallback",
        dirty_worktree=True,
    )
    _write_json(
        pulse,
        {
            "contract_name": "ea.weekly_product_pulse",
            "scorecard_source": ".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml",
            "release_truth_source": ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
            "release_health": {"state": "clear"},
            "flagship_readiness": {"state": "clear"},
            "journey_gate_health": {"state": "ready", "blocked_count": 0},
            "supporting_signals": {"launch_readiness": "Release truth is clear enough to widen claims."},
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, {"status": "pass"})
    _write_json(journey, {"summary": {"overall_state": "ready", "blocked_count": 0}})
    scope.write_text(VALID_SCOPE_TEXT, encoding="utf-8")

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
            "--implementation-scope",
            str(scope),
            "--release-manifest",
            str(manifest),
            "--project-modes",
            str(project_modes),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "release authority gate is fail:" in result.stdout
    assert "public_origin_missing" in result.stdout
    assert "deployment_id_local_fallback" in result.stdout
