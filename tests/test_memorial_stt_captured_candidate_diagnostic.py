from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
GENERATED_AT = "2026-06-19T19:50:00Z"


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _candidate_receipt(*, status: str = "pass") -> dict[str, object]:
    return {
        "contract_name": "ea.memorial_stt_fixture_candidate",
        "status": status,
        "failed_codes": [] if status == "pass" else ["audio_too_short_for_expected_text"],
        "candidate_scope": "audio_quality_and_provenance_only",
        "promotion_gate": {
            "status": "pending_captured_candidate_benchmark",
            "required_receipt": ".codex-studio/published/memorial_stt_provider_benchmark_captured_candidate.generated.json",
            "may_update_fixture_manifest": False,
            "next_action": "run_captured_candidate_benchmark_before_fixture_manifest",
        },
        "bundle": {
            "root": "[memorial_stt_error_root]",
            "id": "bundle-123",
        },
        "audio": {
            "sha256": "a" * 64,
            "bytes": 88000,
            "duration_seconds": 3.0,
            "expected_min_duration_seconds": 2.4,
        },
        "candidate_manifest_entry": {
            "sample": "captured_candidate",
            "file": "captured_candidate.wav",
            "expected_text": {
                "text_chars": 32,
                "text_sha256": "b" * 64,
                "text_redacted": True,
            },
            "required_tokens": [
                {"text_chars": 4, "text_sha256": "c" * 64, "text_redacted": True},
            ],
        },
        "raw_text_fields": False,
    }


def _provider_result(*, passed: bool, actual_hash: str = "d" * 64) -> dict[str, object]:
    return {
        "status": "transcribed",
        "passed": passed,
        "usable": True,
        "intent_correct": passed,
        "token_f1": 1.0 if passed else 0.2,
        "min_token_f1": 0.55,
        "wer": 0.0 if passed else 0.9,
        "max_wer": 0.55,
        "ms": 300.0,
        "transcriber": "cartesia/ink-whisper+enhanced_wav",
        "expected_text_chars": 32,
        "actual_text_chars": 28,
        "expected_text_sha256": "b" * 64,
        "actual_text_sha256": "b" * 64 if passed else actual_hash,
        "required_token_count": 1,
        "required_token_sha256": ["c" * 64],
        "text_mode": "redacted",
        "text_redacted": True,
    }


def _benchmark_receipt(*, captured_passed: bool = False) -> dict[str, object]:
    return {
        "contract_name": "ea.memorial_stt_provider_benchmark",
        "status": "pass" if captured_passed else "blocked",
        "scoring": {
            "text_mode": "redacted",
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
        "fixture_quality_status": "pass",
        "fixture_quality_failed_codes": [],
        "provider_ranking": [],
        "rows": [
            {
                "sample": "captured_candidate",
                "variant": "captured",
                "fixture": "[private_bundle]/bundle-123/input.wav",
                "fixture_sha256": "a" * 64,
                "fixture_quality": {
                    "status": "pass",
                    "failed_codes": [],
                    "audio_duration_seconds": 3.0,
                    "expected_min_duration_seconds": 2.4,
                },
                "provenance": {
                    "external_bundle": True,
                    "bundle_root": "[memorial_stt_error_root]",
                    "bundle_id": "bundle-123",
                    "synthetic": False,
                    "speaker_consent": "operator_attested_for_private_stt_regression",
                    "allowed_purpose": "memorial_stt_regression_and_provider_bakeoff",
                    "retention": "private_captured_regression_candidate",
                    "accent": "Austrian German",
                },
                "full_runtime": _provider_result(passed=captured_passed),
                "onemin_sample": _provider_result(passed=False, actual_hash="e" * 64),
                "shadow": {
                    **_provider_result(passed=False, actual_hash="f" * 64),
                    "status": "error",
                    "usable": False,
                },
            },
            {
                "sample": "control_synthetic",
                "variant": "synthetic",
                "provenance": {"synthetic": True},
                "full_runtime": _provider_result(passed=True),
            },
        ],
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_captured_candidate_diagnostic_blocks_failed_candidate_without_raw_text(monkeypatch, tmp_path: Path) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    verifier = _load_script("verify_memorial_stt_captured_candidate_diagnostic")
    monkeypatch.setattr(materializer, "resolve_source_state_head", lambda _root: "HEAD")
    monkeypatch.setattr(
        materializer,
        "resolve_source_worktree_fingerprint",
        lambda _root: "worktree-fingerprint",
    )
    candidate = tmp_path / "candidate.json"
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "diagnostic.json"
    _write(candidate, _candidate_receipt())
    _write(benchmark, _benchmark_receipt(captured_passed=False))

    receipt = materializer.materialize_diagnostic(
        output_path=output,
        candidate_receipt_path=candidate,
        benchmark_receipt_path=benchmark,
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "blocked"
    assert receipt["promotion_allowed"] is False
    assert receipt["may_update_fixture_manifest"] is False
    assert receipt["generated_by"] == "scripts/materialize_memorial_stt_captured_candidate_diagnostic.py"
    assert receipt["source_git_head"] == "HEAD"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_state_fingerprint"] == "worktree-fingerprint"
    assert (
        receipt["source_state_fingerprint_semantics"]
        == "worktree_source_files_sha256_excluding_generated_only_paths"
    )
    assert receipt["privacy"]["raw_transcript_fields"] is False  # type: ignore[index]
    assert receipt["privacy"]["candidate_raw_text_fields"] is False  # type: ignore[index]
    assert "transcript_hash_mismatch" in receipt["blocker_summary"]["row_failure_codes"]  # type: ignore[index]
    assert "token_f1_below_min" in receipt["blocker_summary"]["row_failure_codes"]  # type: ignore[index]
    assert "full_text" in receipt["next_action"]
    rendered = json.dumps(receipt)
    assert '"actual_text":' not in rendered
    assert '"expected_text":' not in rendered

    verification = verifier.verify_diagnostic(output)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_captured_candidate_diagnostic_allows_promotion_only_when_full_runtime_rows_pass(tmp_path: Path) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    candidate = tmp_path / "candidate.json"
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "diagnostic.json"
    _write(candidate, _candidate_receipt())
    _write(benchmark, _benchmark_receipt(captured_passed=True))

    receipt = materializer.materialize_diagnostic(
        output_path=output,
        candidate_receipt_path=candidate,
        benchmark_receipt_path=benchmark,
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "pass"
    assert receipt["promotion_allowed"] is True
    assert receipt["may_update_fixture_manifest"] is True
    assert receipt["next_action"] == "promote_captured_candidate_to_fixture_manifest"


def test_captured_candidate_diagnostic_verifier_rejects_promotion_overclaim(tmp_path: Path) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    verifier = _load_script("verify_memorial_stt_captured_candidate_diagnostic")
    candidate = tmp_path / "candidate.json"
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "diagnostic.json"
    _write(candidate, _candidate_receipt())
    _write(benchmark, _benchmark_receipt(captured_passed=False))
    materializer.materialize_diagnostic(
        output_path=output,
        candidate_receipt_path=candidate,
        benchmark_receipt_path=benchmark,
        generated_at=GENERATED_AT,
    )
    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["status"] = "pass"
    tampered["promotion_allowed"] = True
    tampered["may_update_fixture_manifest"] = True
    output.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_diagnostic(output)

    assert verification["status"] == "fail"
    assert "diagnostic_promotion_overclaim" in verification["issues"]


def test_captured_candidate_diagnostic_clis_work(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.json"
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "diagnostic.json"
    _write(candidate, _candidate_receipt())
    _write(benchmark, _benchmark_receipt(captured_passed=False))

    materialized = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "materialize_memorial_stt_captured_candidate_diagnostic.py"),
            "--candidate-receipt",
            str(candidate),
            "--benchmark-receipt",
            str(benchmark),
            "--output",
            str(output),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout

    verified = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_memorial_stt_captured_candidate_diagnostic.py"),
            "--receipt",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout
