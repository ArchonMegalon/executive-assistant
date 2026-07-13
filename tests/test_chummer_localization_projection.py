from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.verify_chummer_localization_projection import BLOCKED_CONTRADICTORY_STATUS
from scripts.verify_chummer_localization_projection import BLOCKED_MISSING_STATUS
from scripts.verify_chummer_localization_projection import PASS_STATUS
from scripts.verify_chummer_localization_projection import build_projection


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_chummer_localization_projection.py"
OBSERVED_AT = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
LOCALES = ["en-US", "de-DE", "fr-FR", "ja-JP", "pt-BR", "zh-CN"]
DOMAINS = [
    "app_chrome",
    "install_update_support",
    "companion_runtime",
    "explain_receipts",
    "data_rules_names",
    "generated_artifacts",
]
GATES = [
    "pseudo_localization",
    "missing_key_fail_fast",
    "top_surface_overflow_checks",
    "locale_smoke_first_launch",
    "locale_smoke_companion",
    "locale_smoke_settings",
    "locale_smoke_explain",
    "locale_smoke_updater",
    "locale_smoke_support",
    "voice_opt_in_fallback_smoke",
    "non_english_generated_artifact_smoke",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _fixture_paths(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "matrix": tmp_path / "LOCALIZATION_PARITY_MATRIX.yaml",
        "system": tmp_path / "LOCALIZATION_AND_LANGUAGE_SYSTEM.md",
        "blockers": tmp_path / "GROUP_BLOCKERS.md",
        "gold": tmp_path / "FINAL_GOLD_GRAPH.generated.json",
        "weekly": tmp_path / "WEEKLY_PRODUCT_PULSE.generated.json",
        "proof": tmp_path / "UI_LOCALIZATION_RELEASE_GATE.generated.json",
    }
    matrix = {
        "product": "chummer",
        "shipping_locales": LOCALES,
        "domains": [{"id": domain, "label": domain} for domain in DOMAINS],
        "acceptance_gates": GATES,
        "locale_matrix": [
            {
                "locale": locale,
                "role": "source" if locale == "en-US" else "shipping_target",
                "domains": {domain: "release_required" for domain in DOMAINS},
            }
            for locale in LOCALES
        ],
    }
    paths["matrix"].write_text(yaml.safe_dump(matrix, sort_keys=False), encoding="utf-8")
    paths["system"].write_text(
        "\n".join(
            [
                "# Localization and language system",
                "## Acceptance gates",
                "Locale smoke tests cover companion cards.",
                "A voice-opt-in fallback smoke is required.",
                "The quality bar includes localized companion runtime copy.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    paths["blockers"].write_text(
        "# Group blockers\n\nLast reviewed: 2026-07-13\n\n"
        "### BLK-009 — flagship localization proof is below release bar\n\n"
        "Cleared 2026-07-13.\nCurrent evidence passes.\n\n"
        "### BLK-010 — another blocker\n",
        encoding="utf-8",
    )

    normalized_locales = [locale.lower() for locale in LOCALES]
    generated_at = "2026-07-12T12:00:00Z"
    proof = {
        "contract_name": "chummer6-ui.localization_release_gate",
        "generated_at": generated_at,
        "status": "pass",
        "source_git_head": "a" * 40,
        "localization_matrix_sha256": _sha256(paths["matrix"]),
        "localization_system_sha256": _sha256(paths["system"]),
        "shipping_locales": normalized_locales,
        "default_key_count": 10,
        "explicit_fallback_runtime": "pass",
        "signoff_smoke_runner": {"status": "pass"},
        "blocking_findings": [],
        "translation_backlog_findings": [],
        "domain_coverage": {domain: "pass" for domain in DOMAINS},
        "locale_domain_coverage": {
            locale: {domain: "pass" for domain in DOMAINS} for locale in normalized_locales
        },
        "locale_summary": [
            {
                "locale": locale,
                "override_count": 10,
                "minimum_override_count": 1,
                "untranslated_key_count": 0,
                "missing_release_seed_keys": [],
                "legacy_xml_present": True,
                "legacy_data_xml_present": True,
            }
            for locale in normalized_locales
        ],
        "acceptance_gates": GATES,
    }
    _write_json(paths["proof"], proof)
    _write_json(
        paths["gold"],
        {
            "contract_name": "chummer.final_gold_graph",
            "generated_at_utc": "2026-07-12T13:00:00Z",
            "status": "pass",
            "verdict": "GOLD_READY",
            "proof_inputs": [
                {
                    "kind": "ui_localization_release_gate",
                    "path": paths["proof"].as_posix(),
                    "status": "pass",
                    "generated_at": generated_at,
                }
            ],
            "completion_audit": {
                "requirements": [
                    {
                        "id": "localization",
                        "status": "pass",
                        "missing_or_failed_proof_kinds": [],
                    }
                ]
            },
        },
    )
    _write_json(
        paths["weekly"],
        {
            "contract_name": "chummer.weekly_product_pulse",
            "generated_at": "2026-07-13T04:00:00Z",
            "as_of": "2026-07-13",
            "release_health": {"state": "green_or_explained"},
            "flagship_readiness": {"state": "ready", "proof_status": "pass"},
        },
    )
    return paths


def _build(paths: dict[str, Path], **kwargs: object) -> dict[str, object]:
    return build_projection(
        matrix_path=paths["matrix"],
        system_path=paths["system"],
        blockers_path=paths["blockers"],
        gold_graph_path=paths["gold"],
        weekly_pulse_path=paths["weekly"],
        ui_receipt_path=paths["proof"],
        observed_at=OBSERVED_AT,
        **kwargs,
    )


def _cli_args(paths: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        str(SCRIPT),
        "--matrix",
        str(paths["matrix"]),
        "--system",
        str(paths["system"]),
        "--blockers",
        str(paths["blockers"]),
        "--gold-graph",
        str(paths["gold"]),
        "--weekly-pulse",
        str(paths["weekly"]),
        "--ui-receipt",
        str(paths["proof"]),
        "--observed-at",
        "2026-07-13T12:00:00Z",
    ]


def test_projection_passes_only_when_every_canonical_requirement_is_bound(tmp_path: Path) -> None:
    projection = _build(_fixture_paths(tmp_path))

    assert projection["status"] == PASS_STATUS
    assert projection["blocking_findings"] == []
    assert projection["canonical_release_authority"] is False
    assert projection["blocker_mutation_allowed"] is False
    assert projection["petition_required"] is False
    assert projection["boundary"]["allowed_action"] == "emit_derived_telemetry_and_design_petition"


def test_current_style_companion_gap_fails_closed_and_requests_petition(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    proof = json.loads(paths["proof"].read_text(encoding="utf-8"))
    proof["source_git_head"] = ""
    proof["localization_matrix_sha256"] = ""
    proof["localization_system_sha256"] = ""
    proof["domain_coverage"].pop("companion_runtime")
    proof["acceptance_gates"].remove("locale_smoke_companion")
    proof["acceptance_gates"].remove("voice_opt_in_fallback_smoke")
    for coverage in proof["locale_domain_coverage"].values():
        coverage.pop("companion_runtime")
    _write_json(paths["proof"], proof)

    projection = _build(paths)
    codes = set(projection["blocking_finding_codes"])

    assert projection["status"] == BLOCKED_CONTRADICTORY_STATUS
    assert projection["canonical_release_authority"] is False
    assert projection["blocker_mutation_allowed"] is False
    assert projection["petition_required"] is True
    assert "ui_receipt_domains_missing" in codes
    assert "ui_receipt_acceptance_gates_missing" in codes
    assert "ui_receipt_source_git_head_missing_or_invalid" in codes
    assert "ui_receipt_matrix_binding_missing_or_mismatch" in codes
    assert "ui_receipt_system_binding_missing_or_mismatch" in codes
    assert "blk_009_clearance_conflicts_with_structural_proof" in codes
    assert "gold_graph_localization_pass_conflicts_with_structural_proof" in codes


def test_projection_binds_every_input_without_mutating_it(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    before = {key: path.read_bytes() for key, path in paths.items()}

    projection = _build(paths)

    after = {key: path.read_bytes() for key, path in paths.items()}
    assert before == after
    bindings = projection["input_bindings"]
    assert set(bindings) == {
        "localization_matrix",
        "localization_system",
        "blocker_register",
        "final_gold_graph",
        "weekly_product_pulse",
        "ui_localization_receipt",
    }
    for binding in bindings.values():
        assert binding["read_status"] == "bound"
        assert len(binding["sha256"]) == 64
        assert binding["size_bytes"] > 0
        assert binding["mtime_utc"].endswith("Z")
        assert "content_timestamp" in binding


def test_missing_input_is_distinct_from_contradictory_evidence(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    paths["system"].unlink()

    projection = _build(paths)

    assert projection["status"] == BLOCKED_MISSING_STATUS
    assert projection["petition_required"] is True
    assert "input_missing:localization_system" in projection["blocking_finding_codes"]


def test_stale_ui_receipt_fails_closed(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    proof = json.loads(paths["proof"].read_text(encoding="utf-8"))
    proof["generated_at"] = "2026-07-01T00:00:00Z"
    _write_json(paths["proof"], proof)
    gold = json.loads(paths["gold"].read_text(encoding="utf-8"))
    gold["proof_inputs"][0]["generated_at"] = proof["generated_at"]
    _write_json(paths["gold"], gold)

    projection = _build(paths, max_proof_age_hours=24.0)

    assert projection["status"] == BLOCKED_CONTRADICTORY_STATUS
    assert "ui_receipt_stale" in projection["blocking_finding_codes"]


def test_ea_weekly_pulse_cannot_masquerade_as_canonical_chummer_pulse(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    weekly = json.loads(paths["weekly"].read_text(encoding="utf-8"))
    weekly["contract_name"] = "ea.weekly_product_pulse"
    _write_json(paths["weekly"], weekly)

    projection = _build(paths)

    assert projection["status"] == BLOCKED_CONTRADICTORY_STATUS
    assert "weekly_pulse_contract_mismatch" in projection["blocking_finding_codes"]


def test_cli_returns_zero_only_for_consistent_projection(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    passed = subprocess.run(
        [*_cli_args(paths), "--pretty"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert passed.returncode == 0
    assert json.loads(passed.stdout)["status"] == PASS_STATUS

    proof = json.loads(paths["proof"].read_text(encoding="utf-8"))
    proof["acceptance_gates"].remove("voice_opt_in_fallback_smoke")
    _write_json(paths["proof"], proof)
    blocked = subprocess.run(
        [*_cli_args(paths), "--pretty"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["status"] == BLOCKED_CONTRADICTORY_STATUS


def test_cli_writes_private_atomic_derived_receipt(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    output = tmp_path / "published" / "chummer_localization_projection.generated.json"

    completed = subprocess.run(
        [*_cli_args(paths), "--output", str(output)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert output.is_file()
    assert os.stat(output).st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == PASS_STATUS
    assert json.loads(completed.stdout)["output"] == output.as_posix()
