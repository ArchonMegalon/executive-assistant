from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_flagship_release_readiness.py"
REAL_SCOPE = ROOT / ".codex-design" / "repo" / "IMPLEMENTATION_SCOPE.md"

VALID_SCOPE_TEXT = (
    "mirrored `.codex-design/product/*`\n"
    "Guide/help/public projections must compile from mirrored design sources rather than assistant-local prompt lore.\n"
)
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


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
            "artifact_set": [
                ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"
            ],
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


def test_flagship_release_readiness_gate_fails_closed_on_blocked_journey(
    tmp_path: Path,
) -> None:
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
            "supporting_signals": {
                "launch_readiness": "Hold launch expansion pending cross-host journey coverage."
            },
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


def test_flagship_release_readiness_gate_accepts_canonical_identity_sources_and_ready_vocabulary(
    tmp_path: Path,
) -> None:
    assert _verify_canonical_pulse(tmp_path, _canonical_pulse()) == []


def test_flagship_release_readiness_gate_accepts_committed_journey_snapshot_when_external_receipt_is_absent(
    tmp_path: Path,
) -> None:
    journey = tmp_path / "journey.json"
    pulse = _canonical_pulse(journey_source=journey.as_posix())

    assert _verify_canonical_pulse(tmp_path, pulse, journey_missing=True) == []


def test_flagship_release_readiness_gate_fails_when_external_receipt_and_snapshot_are_absent(
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
            "release_health": {"state": "clear"},
            "flagship_readiness": {"state": "clear"},
            "supporting_signals": {
                "launch_readiness": "Release truth is clear enough to widen claims."
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
            "supporting_signals": {
                "launch_readiness": "Release truth is clear enough to widen claims."
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
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "journey gates summary missing or invalid" in result.stdout


def test_flagship_release_readiness_gate_rejects_ea_local_pulse_and_missing_ea_scope(
    tmp_path: Path,
) -> None:
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
            "release_truth_source": "",
            "release_health": {"state": "clear"},
            "flagship_readiness": {"state": "clear"},
            "journey_gate_health": {"state": "ready", "blocked_count": 0},
            "supporting_signals": {
                "launch_readiness": "Release truth is clear enough to widen claims."
            },
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
    assert "expected chummer.weekly_product_pulse" in result.stdout
    assert "expected products/chummer/PRODUCT_HEALTH_SCORECARD.yaml" in result.stdout
    assert (
        "implementation scope no longer requires mirrored design-source compilation"
        in result.stdout
    )


def test_flagship_release_readiness_gate_rejects_fresh_green_mirror_on_exact_hash_drift(
    tmp_path: Path,
) -> None:
    local_green = _canonical_pulse()
    canonical_freeze = _canonical_pulse(
        launch_action="freeze_launch",
        launch_readiness="Hold launch expansion until flagship readiness returns to ready.",
    )
    canonical_freeze["release_health"] = {"state": "needs_attention"}
    canonical_freeze["flagship_readiness"] = {"state": "watch"}

    issues = _verify_canonical_pulse(
        tmp_path,
        local_green,
        canonical_source=canonical_freeze,
    )

    assert "weekly product pulse mirror parity is drift, expected ok" in issues
    assert (
        "weekly product pulse mirror does not prove exact source hash parity" in issues
    )


def test_flagship_release_readiness_gate_rejects_stale_and_malformed_canonical_pulses(
    tmp_path: Path,
) -> None:
    stale = _canonical_pulse(generated_at=NOW - timedelta(days=9))
    stale_issues = _verify_canonical_pulse(tmp_path, stale)
    malformed = _canonical_pulse()
    malformed.update(
        {
            "contract_version": 3.0,
            "generated_at": "not-a-timestamp",
            "release_health": [],
            "supporting_signals": [],
        }
    )
    malformed_issues = _verify_canonical_pulse(tmp_path, malformed)

    assert (
        "weekly product pulse generated_at is stale (older than 8 days)" in stale_issues
    )
    assert "weekly product pulse as_of is stale (older than 8 days)" in stale_issues
    assert (
        "weekly product pulse contract version is 3.0, expected 3" in malformed_issues
    )
    assert "weekly product pulse generated_at is missing or invalid" in malformed_issues
    assert (
        "weekly release_health is missing, expected green_or_explained"
        in malformed_issues
    )
    assert "weekly launch_readiness must be a non-empty string" in malformed_issues


def test_flagship_release_readiness_gate_uses_structured_launch_action_not_exact_human_copy(
    tmp_path: Path,
) -> None:
    assert (
        _verify_canonical_pulse(
            tmp_path,
            _canonical_pulse(
                launch_readiness="Current governed launch evidence supports a bounded expansion."
            ),
        )
        == []
    )

    frozen = _canonical_pulse(
        launch_action="freeze_launch",
        launch_readiness="Current governed launch evidence is green.",
    )
    issues = _verify_canonical_pulse(tmp_path, frozen)
    assert (
        "weekly launch-governance action is freeze_launch, expected launch_expand"
        in issues
    )


def test_flagship_release_readiness_gate_detects_swap_during_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replacement = tmp_path / "replacement-pulse.json"
    _write_json(replacement, {**_canonical_pulse(), "summary": "swapped"})
    original_inspector = VERIFIER.inspect_manifest

    def swapping_inspector(
        root: Path,
        manifest: Path,
        *,
        hash_file: Callable[[Path], str],
        binding_key: str,
        expected_absolute_local_path: Path,
    ) -> list[dict[str, object]]:
        rows = original_inspector(
            root,
            manifest,
            hash_file=hash_file,
            binding_key=binding_key,
            expected_absolute_local_path=expected_absolute_local_path,
        )
        os.replace(
            replacement, tmp_path / "mirror" / "WEEKLY_PRODUCT_PULSE.generated.json"
        )
        return rows

    monkeypatch.setattr(VERIFIER, "inspect_manifest", swapping_inspector)
    issues = _verify_canonical_pulse(tmp_path, _canonical_pulse())

    assert (
        "weekly product pulse mirror changed during mirror parity inspection" in issues
    )
    assert (
        "weekly product pulse mirror does not prove exact source hash parity" in issues
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("blocked_count", 0.0),
        ("blocked_count", "0"),
        ("warning_count", 0.0),
        ("warning_count", "0"),
    ],
)
def test_flagship_release_readiness_gate_rejects_noninteger_canonical_journey_counts(
    tmp_path: Path, field: str, value: object
) -> None:
    pulse = _canonical_pulse()
    health = dict(pulse["journey_gate_health"])
    health[field] = value
    pulse["journey_gate_health"] = health

    issues = _verify_canonical_pulse(tmp_path, pulse)

    assert (
        f"weekly journey_gate_health {field} is missing or not a nonnegative integer"
        in issues
    )


def test_flagship_release_readiness_gate_rejects_canonical_blocker_masked_by_external_zero(
    tmp_path: Path,
) -> None:
    pulse = _canonical_pulse()
    health = dict(pulse["journey_gate_health"])
    health["blocked_count"] = 1
    pulse["journey_gate_health"] = health

    issues = _verify_canonical_pulse(tmp_path, pulse)

    assert "weekly journey_gate_health still reports 1 blocked journey(s)" in issues


@pytest.mark.parametrize(
    ("warning_count", "expected_issue"),
    [
        (1, "fleet journey gates still report 1 warning journey(s)"),
        ("1", "fleet journey gates warning_count is missing or invalid"),
        (-1, "fleet journey gates warning_count is missing or invalid"),
        (1.0, "fleet journey gates warning_count is missing or invalid"),
    ],
)
def test_flagship_release_readiness_gate_rejects_external_journey_warnings(
    tmp_path: Path,
    warning_count: object,
    expected_issue: str,
) -> None:
    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        external_warning_count=warning_count,
    )

    assert expected_issue in issues


def test_flagship_release_readiness_gate_rejects_nonfile_pulse_binding(
    tmp_path: Path,
) -> None:
    def change_binding_kind(paths: dict[str, Path]) -> None:
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        manifest["bindings"][0]["kind"] = "directory"
        _write_json(paths["manifest"], manifest)

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=change_binding_kind,
    )

    assert any("mirror manifest missing or invalid" in issue for issue in issues)


@pytest.mark.parametrize("bound_path", ["pulse", "source"])
def test_flagship_release_readiness_gate_rejects_oversized_pulse_before_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bound_path: str,
) -> None:
    def make_oversized(paths: dict[str, Path]) -> None:
        paths[bound_path].write_bytes(b"x" * (VERIFIER.PULSE_MAX_BYTES + 1))

    def forbidden_inspector(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("oversized pulse reached parity inspector")

    monkeypatch.setattr(VERIFIER, "inspect_manifest", forbidden_inspector)
    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=make_oversized,
    )

    label = "mirror" if bound_path == "pulse" else "canonical source"
    assert f"weekly product pulse {label} exceeds the 1 MiB read bound" in issues


def test_flagship_release_readiness_gate_detects_source_swap_after_inspector_postcheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_reader = VERIFIER._read_bound_file
    read_count = 0
    source = tmp_path / "source" / "WEEKLY_PRODUCT_PULSE.generated.json"

    def swapping_reader(
        *args: object, **kwargs: object
    ) -> tuple[bytes, str, list[str]]:
        nonlocal read_count
        read_count += 1
        if read_count == 3:
            replacement = source.with_name("replacement-pulse.json")
            _write_json(
                replacement, {**_canonical_pulse(), "summary": "swapped source"}
            )
            os.replace(replacement, source)
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(VERIFIER, "_read_bound_file", swapping_reader)
    issues = _verify_canonical_pulse(tmp_path, _canonical_pulse())

    assert read_count >= 4
    assert (
        "weekly product pulse canonical source descriptor identity changed before read"
        in issues
    )
    assert (
        "weekly product pulse mirror does not prove exact source hash parity" in issues
    )


@pytest.mark.parametrize(
    ("artifact", "duplicate_json", "expected_issue"),
    [
        (
            "receipt",
            '{"status":"pass","status":"pass"}\n',
            "flagship release receipt missing or invalid",
        ),
        (
            "browser",
            '{"status":"pass","status":"pass"}\n',
            "browser workflow proof missing or invalid",
        ),
        (
            "journey",
            '{"summary":{"overall_state":"ready","blocked_count":0,'
            '"blocked_count":0,"warning_count":0}}\n',
            "journey gates summary missing or invalid",
        ),
        (
            "release_manifest",
            '{"contract_name":"ea.release_manifest.v1",'
            '"contract_name":"ea.release_manifest.v1"}\n',
            "release manifest missing or invalid",
        ),
        (
            "project_modes",
            '{"modes":[],"modes":[]}\n',
            "project modes manifest missing or invalid",
        ),
    ],
)
def test_flagship_release_readiness_gate_rejects_duplicate_keys_in_all_json_inputs(
    tmp_path: Path,
    artifact: str,
    duplicate_json: str,
    expected_issue: str,
) -> None:
    def write_duplicate(paths: dict[str, Path]) -> None:
        paths[artifact].write_text(duplicate_json, encoding="utf-8")

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=write_duplicate,
    )

    assert any(issue.startswith(expected_issue) for issue in issues)


def test_flagship_release_readiness_gate_rejects_duplicate_keys_in_bound_pulse(
    tmp_path: Path,
) -> None:
    def write_duplicate_pulse(paths: dict[str, Path]) -> None:
        pulse_text = json.dumps(_canonical_pulse())
        field = '"contract_name": "chummer.weekly_product_pulse"'
        duplicate_text = pulse_text.replace(field, f"{field}, {field}", 1) + "\n"
        paths["pulse"].write_text(duplicate_text, encoding="utf-8")
        paths["source"].write_text(duplicate_text, encoding="utf-8")

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=write_duplicate_pulse,
    )

    assert "weekly product pulse contains duplicate JSON keys" in issues


@pytest.mark.parametrize(
    ("case", "expected_issue"),
    [
        (
            "wrong_source_cases",
            "browser workflow proof source-backed cases are not exact",
        ),
        ("wrong_real_cases", "browser workflow proof real-browser cases are not exact"),
        (
            "float_exit",
            "browser workflow proof real-browser exit_code is not exact integer 0",
        ),
        (
            "bool_exit",
            "browser workflow proof real-browser exit_code is not exact integer 0",
        ),
        (
            "terminal_passed",
            "browser workflow proof real-browser terminal_passed_count is not exact integer 2",
        ),
        (
            "terminal_xfail",
            "browser workflow proof real-browser terminal_xfail_count is not exact integer 0",
        ),
        (
            "terminal_xpass",
            "browser workflow proof real-browser terminal_xpass_count is not exact integer 0",
        ),
        (
            "junit_failure",
            "browser workflow proof real-browser junit_declared_failure_count is not exact integer 0",
        ),
        (
            "junit_inconsistent",
            "browser workflow proof real-browser JUnit declared totals are not consistent",
        ),
        ("stale", "browser workflow proof generated_at is stale (older than 1 day)"),
        ("future", "browser workflow proof generated_at is in the future"),
        (
            "revision",
            "browser workflow proof source_revision does not match release manifest commit_sha",
        ),
        ("nested_blocked", "browser workflow proof real-browser lane is not pass"),
        (
            "nested_limitations",
            "browser workflow proof real-browser limitations are not empty",
        ),
        (
            "current_limitations",
            "browser workflow proof current_limitations is not an empty list",
        ),
        (
            "blocking_reasons",
            "browser workflow proof blocking_reasons is not an empty list",
        ),
        ("dirty", "browser workflow proof source_worktree_dirty is not false"),
    ],
)
def test_flagship_release_readiness_gate_rejects_forged_browser_proof_pass(
    tmp_path: Path,
    case: str,
    expected_issue: str,
) -> None:
    def forge_browser_proof(paths: dict[str, Path]) -> None:
        proof = json.loads(paths["browser"].read_text(encoding="utf-8"))
        source_lane = proof["source_backed_journey_proof"]
        real_lane = proof["real_browser_e2e_proof"]
        if case == "wrong_source_cases":
            source_lane["cases"] = ["forged_case"]
        elif case == "wrong_real_cases":
            real_lane["cases"] = ["forged_case"]
        elif case == "float_exit":
            real_lane["exit_code"] = 0.0
        elif case == "bool_exit":
            real_lane["exit_code"] = False
        elif case == "terminal_passed":
            real_lane["terminal_passed_count"] = 1
        elif case == "terminal_xfail":
            real_lane["terminal_xfail_count"] = 1
        elif case == "terminal_xpass":
            real_lane["terminal_xpass_count"] = 1
        elif case == "junit_failure":
            real_lane["junit_declared_failure_count"] = 1
        elif case == "junit_inconsistent":
            real_lane["junit_totals_consistent"] = False
        elif case == "stale":
            proof["generated_at"] = (NOW - timedelta(days=2)).isoformat()
        elif case == "future":
            proof["generated_at"] = (NOW + timedelta(minutes=6)).isoformat()
        elif case == "revision":
            proof["source_revision"] = "b" * 40
        elif case == "nested_blocked":
            real_lane["status"] = "blocked"
        elif case == "nested_limitations":
            real_lane["limitations"] = ["browser did not run"]
        elif case == "current_limitations":
            proof["current_limitations"] = ["preview only"]
        elif case == "blocking_reasons":
            proof["blocking_reasons"] = ["nested failure"]
        elif case == "dirty":
            proof["source_worktree_dirty"] = True
        _write_json(paths["browser"], proof)

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=forge_browser_proof,
    )

    assert expected_issue in issues


@pytest.mark.parametrize(
    ("field", "value", "expected_issue"),
    [
        (
            "contract_name",
            "forged.browser_proof",
            "browser workflow proof contract_name is not ea.browser_workflow_proof",
        ),
        (
            "version",
            True,
            "browser workflow proof version is not exact integer 3",
        ),
        (
            "kind",
            "claim",
            "browser workflow proof kind is not proof_receipt",
        ),
        (
            "product",
            "other",
            "browser workflow proof product is not executive-assistant",
        ),
        (
            "surface",
            "other",
            "browser workflow proof surface is not browser_workflow_proof",
        ),
        (
            "generated_by",
            "forged.py",
            "browser workflow proof generated_by is not scripts/materialize_ea_browser_workflow_proof.py",
        ),
    ],
)
def test_flagship_release_readiness_gate_rejects_browser_proof_metadata_drift(
    tmp_path: Path,
    field: str,
    value: object,
    expected_issue: str,
) -> None:
    def forge_metadata(paths: dict[str, Path]) -> None:
        proof = json.loads(paths["browser"].read_text(encoding="utf-8"))
        proof[field] = value
        _write_json(paths["browser"], proof)

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=forge_metadata,
    )

    assert expected_issue in issues


@pytest.mark.parametrize(
    ("mutation", "expected_issue"),
    [
        (
            "missing",
            "browser workflow proof source_state_samples are not exact",
        ),
        (
            "stage",
            "browser workflow proof source state sample stage is not after_source",
        ),
        (
            "revision",
            "browser workflow proof source state sample after_source revision does not match release manifest commit_sha",
        ),
        (
            "dirty",
            "browser workflow proof source state sample after_source dirty is not false",
        ),
    ],
)
def test_flagship_release_readiness_gate_rejects_inexact_source_state_samples(
    tmp_path: Path,
    mutation: str,
    expected_issue: str,
) -> None:
    def forge_samples(paths: dict[str, Path]) -> None:
        proof = json.loads(paths["browser"].read_text(encoding="utf-8"))
        if mutation == "missing":
            proof.pop("source_state_samples")
        elif mutation == "stage":
            proof["source_state_samples"][1]["stage"] = "after_forged_lane"
        elif mutation == "revision":
            proof["source_state_samples"][1]["revision"] = "b" * 40
        elif mutation == "dirty":
            proof["source_state_samples"][1]["dirty"] = True
        _write_json(paths["browser"], proof)

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=forge_samples,
    )

    assert expected_issue in issues


def test_flagship_release_readiness_gate_rejects_malformed_browser_revision(
    tmp_path: Path,
) -> None:
    def forge_revision(paths: dict[str, Path]) -> None:
        proof = json.loads(paths["browser"].read_text(encoding="utf-8"))
        proof["source_revision"] = "A" * 40
        for sample in proof["source_state_samples"]:
            sample["revision"] = "A" * 40
        _write_json(paths["browser"], proof)

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=forge_revision,
    )

    assert (
        "browser workflow proof source_revision is not a canonical lowercase 40- or 64-hex revision"
        in issues
    )


def test_flagship_release_readiness_gate_rejects_handwritten_minimal_lane(
    tmp_path: Path,
) -> None:
    def forge_lane(paths: dict[str, Path]) -> None:
        proof = json.loads(paths["browser"].read_text(encoding="utf-8"))
        proof["real_browser_e2e_proof"] = {
            "status": "pass",
            "test_file": VERIFIER.BROWSER_REAL_TEST_FILE,
            "cases": VERIFIER.BROWSER_REAL_CASES,
            "exit_code": 0,
            "limitations": [],
        }
        _write_json(paths["browser"], proof)

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=forge_lane,
    )

    assert (
        "browser workflow proof real-browser selection_mode is not exact_node_ids"
        in issues
    )
    assert (
        "browser workflow proof real-browser executed_count is not exact integer 2"
        in issues
    )


@pytest.mark.parametrize("bound_path", ["manifest", "pulse", "source"])
def test_flagship_release_readiness_gate_rejects_symlinked_parity_inputs(
    tmp_path: Path, bound_path: str
) -> None:
    def replace_with_symlink(paths: dict[str, Path]) -> None:
        original = paths[bound_path]
        backing = original.with_name(f"{original.name}.backing")
        original.rename(backing)
        original.symlink_to(backing)

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=replace_with_symlink,
    )

    assert any("path contains a symlink" in issue for issue in issues)


def test_flagship_release_readiness_gate_rejects_old_launch_decision_id(
    tmp_path: Path,
) -> None:
    pulse = _canonical_pulse()
    pulse["governor_decisions"] = [
        {"decision_id": "2026-07-12-launch-governance", "action": "launch_expand"}
    ]

    issues = _verify_canonical_pulse(tmp_path, pulse)

    assert (
        "weekly launch-governance action is missing, expected launch_expand" in issues
    )


def test_flagship_release_readiness_gate_rejects_inconsistent_generated_at_and_as_of(
    tmp_path: Path,
) -> None:
    pulse = _canonical_pulse()
    pulse["as_of"] = "2026-07-12"

    issues = _verify_canonical_pulse(tmp_path, pulse)

    assert (
        "weekly product pulse generated_at and as_of dates are inconsistent" in issues
    )
    assert (
        "weekly launch-governance action is missing, expected launch_expand" in issues
    )


def test_flagship_release_readiness_gate_rejects_mapping_launch_readiness(
    tmp_path: Path,
) -> None:
    pulse = _canonical_pulse()
    pulse["supporting_signals"] = {"launch_readiness": {"state": "green"}}

    issues = _verify_canonical_pulse(tmp_path, pulse)

    assert "weekly launch_readiness must be a non-empty string" in issues


def test_design_mirror_manifest_binds_absolute_canonical_pulse_source() -> None:
    rows = VERIFIER.inspect_manifest(
        ROOT,
        ROOT / ".codex-design" / "repo" / "DESIGN_MIRROR_MANIFEST.yaml",
    )
    row = next(item for item in rows if item["key"] == "weekly_product_pulse")

    assert (
        row["local_path"]
        == (
            ROOT / ".codex-design" / "product" / "WEEKLY_PRODUCT_PULSE.generated.json"
        ).as_posix()
    )
    assert row["source_path"] == (
        "/docker/chummercomplete/chummer-design/products/chummer/"
        "WEEKLY_PRODUCT_PULSE.generated.json"
    )
    assert Path(row["local_path"]).is_absolute()
    assert Path(row["source_path"]).is_absolute()
    assert row["required"] is True
    assert row["kind"] == "file"


def test_flagship_release_readiness_gate_rejects_failed_release_authority(
    tmp_path: Path,
) -> None:
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
            "supporting_signals": {
                "launch_readiness": "Release truth is clear enough to widen claims."
            },
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


def _load_verifier() -> ModuleType:
    scripts_path = str(ROOT / "scripts")
    inserted = scripts_path not in sys.path
    if inserted:
        sys.path.insert(0, scripts_path)
    try:
        spec = importlib.util.spec_from_file_location(
            "flagship_release_readiness_verifier", SCRIPT
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            sys.path.remove(scripts_path)


VERIFIER = _load_verifier()


def _valid_browser_proof(
    *,
    generated_at: datetime = NOW,
    source_revision: str = "a" * 40,
    source_tree: str = "b" * 40,
) -> dict[str, object]:
    run_id = "c" * 32

    def lane(
        test_file: str, cases: list[str], *, real_browser: bool
    ) -> dict[str, object]:
        xml_text = (
            "<testsuites><testsuite "
            f'tests="{len(cases)}" failures="0" errors="0" skipped="0">'
            + "".join(f'<testcase classname="proof" name="{case}" />' for case in cases)
            + "</testsuite></testsuites>"
        )
        return {
            "status": "pass",
            "run_id": run_id,
            "trust_model": VERIFIER.BROWSER_PROOF_TRUST_MODEL,
            "source_revision": source_revision,
            "source_tree": source_tree,
            "test_file": test_file,
            "cases": list(cases),
            "selection_mode": "exact_node_ids",
            "node_ids": [f"{test_file}::{case}" for case in cases],
            "runner_root_kind": VERIFIER.BROWSER_RUNNER_ROOT_KIND,
            "snapshot_read_only": True,
            "environment_policy": VERIFIER._expected_lane_environment_policy(
                real_browser
            ),
            "argv_template": VERIFIER._expected_lane_argv_template(test_file, cases),
            "python_identity": {
                "executable": "/usr/bin/python3",
                "sha256": "d" * 64,
                "version": "3.12.0",
                "dependency_root": "/opt/ea-dependencies",
                "dependency_versions": {
                    "playwright": "1.0",
                    "pytest": "9.0",
                    "uvicorn": "1.0",
                },
            },
            "browser_identity": (
                {"executable": "/opt/chromium/chrome", "sha256": "e" * 64}
                if real_browser
                else None
            ),
            "report_format": "junit_xml_embedded",
            "junit_xml": xml_text,
            "junit_xml_sha256": hashlib.sha256(xml_text.encode()).hexdigest(),
            "exit_code": 0,
            "duration_seconds": 0.1,
            "output_excerpt": [f"{len(cases)} passed in 0.01s"],
            "terminal_summary": f"{len(cases)} passed in 0.01s",
            "executed_count": len(cases),
            "passed_count": len(cases),
            "terminal_passed_count": len(cases),
            "failed_count": 0,
            "error_count": 0,
            "skipped_count": 0,
            "xfail_count": 0,
            "xpass_count": 0,
            "terminal_xfail_count": 0,
            "terminal_xpass_count": 0,
            "junit_declared_tests_count": len(cases),
            "junit_declared_failure_count": 0,
            "junit_declared_error_count": 0,
            "junit_declared_skipped_count": 0,
            "junit_totals_consistent": True,
            "executed_cases": list(cases),
            "passed_cases": list(cases),
            "limitations": [],
            "blocking_reasons": [],
        }

    return {
        "contract_name": VERIFIER.BROWSER_PROOF_CONTRACT_NAME,
        "version": VERIFIER.BROWSER_PROOF_CONTRACT_VERSION,
        "product": VERIFIER.BROWSER_PROOF_PRODUCT,
        "surface": VERIFIER.BROWSER_PROOF_SURFACE,
        "kind": VERIFIER.BROWSER_PROOF_KIND,
        "generated_by": VERIFIER.BROWSER_PROOF_GENERATED_BY,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "trust_model": VERIFIER.BROWSER_PROOF_TRUST_MODEL,
        "environment_policy": {
            "name": VERIFIER.BROWSER_ENVIRONMENT_POLICY_NAME,
            "version": VERIFIER.BROWSER_ENVIRONMENT_POLICY_VERSION,
        },
        "status": "pass",
        "source_revision": source_revision,
        "source_tree": source_tree,
        "source_worktree_dirty": False,
        "source_state_samples": [
            {
                "stage": stage,
                "revision": source_revision,
                "tree": source_tree,
                "dirty": False,
            }
            for stage in VERIFIER.BROWSER_SOURCE_STATE_STAGES
        ],
        "snapshot": {
            "archive_format": "git_archive_tar",
            "read_only": True,
            "source_revision": source_revision,
            "source_tree": source_tree,
            "seal_algorithm": VERIFIER.BROWSER_SNAPSHOT_SEAL_ALGORITHM,
            "read_only_enforcement": (VERIFIER.BROWSER_SNAPSHOT_READ_ONLY_ENFORCEMENT),
            "seal_samples": [
                {"stage": stage, "sha256": "f" * 64}
                for stage in VERIFIER.BROWSER_SNAPSHOT_SEAL_STAGES
            ],
            "mutation_watch": {
                "algorithm": VERIFIER.BROWSER_SNAPSHOT_MUTATION_WATCH_ALGORITHM,
                "samples": [
                    {"stage": stage, "event_count": 0, "overflow": False}
                    for stage in VERIFIER.BROWSER_SNAPSHOT_MUTATION_WATCH_STAGES
                ],
            },
        },
        "operator_summary": "Current local unsigned process evidence is green.",
        "seed_source": VERIFIER.BROWSER_PROOF_SEED_SOURCE,
        "release_claim_summary": VERIFIER.BROWSER_PROOF_RELEASE_CLAIM_SUMMARY,
        "expected_browser_signals": list(VERIFIER.BROWSER_PROOF_EXPECTED_SIGNALS),
        "source_backed_journey_proof": lane(
            VERIFIER.BROWSER_SOURCE_BACKED_TEST_FILE,
            VERIFIER.BROWSER_SOURCE_BACKED_CASES,
            real_browser=False,
        ),
        "real_browser_e2e_proof": lane(
            VERIFIER.BROWSER_REAL_TEST_FILE,
            VERIFIER.BROWSER_REAL_CASES,
            real_browser=True,
        ),
        "blocking_reasons": [],
        "current_limitations": [],
    }


def _canonical_pulse(
    *,
    generated_at: datetime = NOW,
    launch_action: str = "launch_expand",
    launch_readiness: str = "Current governed launch evidence is green.",
    journey_source: str | None = None,
) -> dict[str, object]:
    signals: dict[str, object] = {"launch_readiness": launch_readiness}
    pulse: dict[str, object] = {
        "contract_name": "chummer.weekly_product_pulse",
        "contract_version": 3,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "as_of": generated_at.date().isoformat(),
        "scorecard_source": "products/chummer/PRODUCT_HEALTH_SCORECARD.yaml",
        "progress_report_source": "products/chummer/PROGRESS_REPORT.generated.json",
        "progress_history_source": "products/chummer/PROGRESS_HISTORY.generated.json",
        "release_health": {"state": "green_or_explained"},
        "flagship_readiness": {"state": "ready"},
        "journey_gate_health": {
            "state": "ready",
            "blocked_count": 0,
            "warning_count": 0,
        },
        "governor_decisions": [
            {
                "decision_id": f"{generated_at.date().isoformat()}-launch-governance",
                "action": launch_action,
            }
        ],
        "supporting_signals": signals,
    }
    if journey_source is not None:
        pulse["journey_gate_source"] = journey_source
        signals["journey_gate_source"] = journey_source
    return pulse


def _verify_canonical_pulse(
    tmp_path: Path,
    pulse: dict[str, object],
    *,
    canonical_source: dict[str, object] | None = None,
    journey_missing: bool = False,
    external_warning_count: object = 0,
    mutate: Callable[[dict[str, Path]], None] | None = None,
) -> list[str]:
    pulse_path = tmp_path / "mirror" / "WEEKLY_PRODUCT_PULSE.generated.json"
    source_path = tmp_path / "source" / "WEEKLY_PRODUCT_PULSE.generated.json"
    mirror_manifest = tmp_path / "DESIGN_MIRROR_MANIFEST.yaml"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    scope = tmp_path / "scope.md"
    release_manifest = tmp_path / "release_manifest.generated.json"
    project_modes = tmp_path / "PROJECT_MODES.generated.json"

    _write_json(pulse_path, pulse)
    _write_json(source_path, canonical_source or pulse)
    _write_json(
        mirror_manifest,
        {
            "version": 1,
            "bindings": [
                {
                    "key": "weekly_product_pulse",
                    "kind": "file",
                    "local_path": pulse_path.as_posix(),
                    "source_path": source_path.as_posix(),
                    "required": True,
                }
            ],
        },
    )
    _write_json(receipt, {"status": "pass"})
    _write_json(browser, _valid_browser_proof())
    if not journey_missing:
        _write_json(
            journey,
            {
                "summary": {
                    "overall_state": "ready",
                    "blocked_count": 0,
                    "warning_count": external_warning_count,
                }
            },
        )
    scope.write_text(VALID_SCOPE_TEXT, encoding="utf-8")
    _write_release_authority_inputs(release_manifest, project_modes)
    if mutate is not None:
        mutate(
            {
                "manifest": mirror_manifest,
                "pulse": pulse_path,
                "source": source_path,
                "receipt": receipt,
                "browser": browser,
                "journey": journey,
                "release_manifest": release_manifest,
                "project_modes": project_modes,
            }
        )

    return VERIFIER.verify(
        pulse_path=pulse_path,
        flagship_receipt_path=receipt,
        browser_proof_path=browser,
        journey_gates_path=journey,
        implementation_scope_path=scope,
        release_manifest_path=release_manifest,
        project_modes_path=project_modes,
        design_mirror_manifest_path=mirror_manifest,
        canonical_pulse_source_path=source_path,
        observed_at=NOW,
        required_contract_paths=(),
    )


@pytest.mark.parametrize(
    ("case", "expected_issue"),
    [
        ("v2", "browser workflow proof version is not exact integer 3"),
        (
            "junit",
            "browser workflow proof real-browser embedded JUnit sha256 does not match",
        ),
        (
            "digest",
            "browser workflow proof real-browser embedded JUnit sha256 does not match",
        ),
        ("argv", "browser workflow proof real-browser argv template is not exact"),
        (
            "policy",
            "browser workflow proof real-browser environment policy is not exact",
        ),
        ("run", "browser workflow proof real-browser run_id linkage is not exact"),
        (
            "tree",
            "browser workflow proof real-browser source_tree linkage is not exact",
        ),
        (
            "format",
            "browser workflow proof real-browser report_format is not junit_xml_embedded",
        ),
        (
            "seal",
            "browser workflow proof snapshot seal changed during proof",
        ),
        (
            "mutation",
            "browser workflow proof snapshot mutation watch sample after_source is not zero and exact",
        ),
        (
            "source_browser",
            "browser workflow proof source-backed browser_identity must be null",
        ),
        (
            "nan",
            "browser workflow proof missing or invalid",
        ),
        ("seed", "browser workflow proof seed_source is not exact"),
        (
            "claim",
            "browser workflow proof release_claim_summary is not exact",
        ),
        (
            "signals",
            "browser workflow proof expected_browser_signals are not exact",
        ),
        ("schema", "browser workflow proof top-level schema is not exact v3"),
    ],
)
def test_flagship_release_readiness_gate_rejects_v3_evidence_tampering(
    tmp_path: Path, case: str, expected_issue: str
) -> None:
    def tamper(paths: dict[str, Path]) -> None:
        proof = json.loads(paths["browser"].read_text(encoding="utf-8"))
        lane = proof["real_browser_e2e_proof"]
        if case == "v2":
            proof["version"] = 2
        elif case == "junit":
            lane["junit_xml"] += " "
        elif case == "digest":
            lane["junit_xml_sha256"] = "0" * 64
        elif case == "argv":
            lane["argv_template"].append("--collect-only")
        elif case == "policy":
            lane["environment_policy"]["allowed_keys"].append("CI")
        elif case == "run":
            lane["run_id"] = "f" * 32
        elif case == "tree":
            lane["source_tree"] = "f" * 40
        elif case == "format":
            lane["report_format"] = "junit_xml"
        elif case == "seal":
            proof["snapshot"]["seal_samples"][1]["sha256"] = "0" * 64
        elif case == "mutation":
            proof["snapshot"]["mutation_watch"]["samples"][0]["event_count"] = 1
        elif case == "source_browser":
            proof["source_backed_journey_proof"]["browser_identity"] = {
                "executable": "/opt/chromium/chrome",
                "sha256": "e" * 64,
            }
        elif case == "nan":
            lane["duration_seconds"] = float("nan")
        elif case == "seed":
            proof["seed_source"] = "unbound.json"
        elif case == "claim":
            proof["release_claim_summary"] = ""
        elif case == "signals":
            proof["expected_browser_signals"] = []
        elif case == "schema":
            proof["signature"] = "not-authority"
        _write_json(paths["browser"], proof)

    issues = _verify_canonical_pulse(
        tmp_path,
        _canonical_pulse(),
        mutate=tamper,
    )

    assert any(expected_issue in issue for issue in issues)


def test_browser_lane_validator_rejects_nonfinite_duration() -> None:
    proof = _valid_browser_proof()
    lane = proof["real_browser_e2e_proof"]
    assert isinstance(lane, dict)
    lane["duration_seconds"] = float("nan")

    issues = VERIFIER._browser_lane_issues(
        lane,
        label="real-browser",
        expected_test_file=VERIFIER.BROWSER_REAL_TEST_FILE,
        expected_cases=VERIFIER.BROWSER_REAL_CASES,
        real_browser=True,
        expected_run_id=proof["run_id"],
        expected_revision=proof["source_revision"],
        expected_tree=proof["source_tree"],
    )

    assert (
        "browser workflow proof real-browser duration_seconds is not nonnegative"
        in issues
    )
