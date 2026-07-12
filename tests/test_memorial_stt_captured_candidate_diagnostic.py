from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest


ROOT = Path(__file__).resolve().parents[1]
NOW_DT = datetime.now(UTC).replace(microsecond=0)
GENERATED_AT = NOW_DT.isoformat().replace("+00:00", "Z")
AUDIO_SHA = "a" * 64
EXPECTED_SHA = "b" * 64
TOKEN_SHA = "c" * 64
HOSTILE_SHA = "d" * 64
UPLOAD_AUTHORIZATION = {
    "full_runtime": True,
    "shadow": False,
    "onemin_sample": False,
}


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _at(*, hours: int = 0, minutes: int = 0) -> str:
    return (NOW_DT + timedelta(hours=hours, minutes=minutes)).isoformat().replace("+00:00", "Z")


def _source_stamps(materializer: ModuleType) -> dict[str, object]:
    return {
        "source_git_head": materializer.resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": materializer.resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _candidate_receipt(materializer: ModuleType, *, status: str = "pass") -> dict[str, object]:
    quality = {
        "status": "pass",
        "failed_codes": [],
        "audio_duration_seconds": 3.0,
        "expected_min_duration_seconds": 2.4,
        "max_duration_seconds": 120.0,
        "wav_format": {
            "audio_format": 1,
            "channels": 1,
            "sample_rate_hz": 16_000,
            "sample_width_bytes": 2,
        },
    }
    review_payload = {
        "contract_name": "ea.memorial_stt_operator_ground_truth_review_binding.v2",
        "status": "approved",
        "reviewed_at": GENERATED_AT,
        "reviewer_authority": "memorial_operator",
        "audio_sha256": AUDIO_SHA,
        "bundle_id": "bundle-123",
        "sample": "captured_candidate",
        "expected_text_sha256": EXPECTED_SHA,
        "required_token_sha256": [TOKEN_SHA],
        "speaker_consent": "operator_attested_for_private_stt_regression",
        "allowed_purpose": "memorial_stt_regression_and_provider_bakeoff",
        "retention": "private_repo_captured_regression_fixture",
        "language": "de",
        "accent": "Austrian German",
        "provider_upload_authorization": UPLOAD_AUTHORIZATION,
    }
    review_sha = materializer._canonical_sha256(review_payload)
    binding_payload = {
        "contract_name": "ea.memorial_stt_fixture_candidate_binding.v2",
        "status": status,
        "failed_codes": [] if status == "pass" else ["audio_too_short_for_expected_text"],
        "audio_sha256": AUDIO_SHA,
        "bundle_id": "bundle-123",
        "sample": "captured_candidate",
        "fixture_file": "captured_candidate_captured.wav",
        "origin": "captured_operator_manfred_memorial_stt_error_bundle",
        "expected_text_sha256": EXPECTED_SHA,
        "required_token_sha256": [TOKEN_SHA],
        "speaker_consent": "operator_attested_for_private_stt_regression",
        "allowed_purpose": "memorial_stt_regression_and_provider_bakeoff",
        "retention": "private_repo_captured_regression_fixture",
        "language": "de",
        "accent": "Austrian German",
        "fixture_quality": quality,
        "privacy_mode": "redacted",
        "provider_upload_authorization": UPLOAD_AUTHORIZATION,
        "operator_ground_truth_review_binding_sha256": review_sha,
    }
    return {
        "contract_name": "ea.memorial_stt_fixture_candidate",
        "contract_version": 3,
        "generated_at": GENERATED_AT,
        "generated_by": "scripts/materialize_memorial_stt_fixture_candidate.py",
        **_source_stamps(materializer),
        "status": status,
        "failed_codes": [] if status == "pass" else ["audio_too_short_for_expected_text"],
        "candidate_scope": "audio_quality_provenance_and_bound_ground_truth",
        "promotion_gate": {
            "status": "pending_captured_candidate_benchmark" if status == "pass" else "blocked",
            "required_receipt": ".codex-studio/published/memorial_stt_provider_benchmark_captured_candidate.generated.json",
            "required_rule": "captured candidate must pass full-runtime STT scoring against operator-confirmed ground truth before fixture-manifest promotion",
            "may_update_fixture_manifest": False,
            "next_action": "run_captured_candidate_benchmark_before_fixture_manifest"
            if status == "pass"
            else "fix_candidate_failed_codes_before_benchmark",
        },
        "bundle": {
            "root": "[memorial_stt_error_root]",
            "id": "bundle-123",
            "id_sha256": materializer._sha256_text("bundle-123"),
            "has_error_json": False,
            "event_type_code": "",
            "event_type_sha256": "",
            "reason_code": "",
            "reason_sha256": "",
        },
        "audio": {
            "input_file": "input.wav",
            "sha256": AUDIO_SHA,
            "bytes": 88_000,
            "max_bytes": 25 * 1024 * 1024,
            "duration_seconds": 3.0,
            "expected_min_duration_seconds": 2.4,
            "max_duration_seconds": 120.0,
        },
        "fixture_quality": quality,
        "candidate_manifest_entry": {
            "sample": "captured_candidate",
            "file": "captured_candidate_captured.wav",
            "origin": "captured_operator_manfred_memorial_stt_error_bundle",
            "speaker_consent": "operator_attested_for_private_stt_regression",
            "allowed_purpose": "memorial_stt_regression_and_provider_bakeoff",
            "retention": "private_repo_captured_regression_fixture",
            "synthetic": False,
            "language": "de",
            "accent": "Austrian German",
            "provider_upload_authorization": UPLOAD_AUTHORIZATION,
            "expected_text": {
                "text_chars": 32,
                "text_sha256": EXPECTED_SHA,
                "text_redacted": True,
            },
            "required_tokens": [
                {"text_chars": 4, "text_sha256": TOKEN_SHA, "text_redacted": True},
            ],
            "sha256": AUDIO_SHA,
        },
        "operator_ground_truth_review": {
            "contract_name": "ea.memorial_stt_operator_ground_truth_review_binding.v2",
            "status": "approved",
            "reviewed_at": GENERATED_AT,
            "reviewer_authority": "memorial_operator",
            "sha256": review_sha,
        },
        "candidate_binding": {
            "contract_name": "ea.memorial_stt_fixture_candidate_binding.v2",
            "canonicalization": "json_utf8_sorted_keys_compact_v1",
            "sha256": materializer._canonical_sha256(binding_payload),
            "payload": binding_payload,
        },
        "privacy_mode": "redacted",
        "text_mode": "redacted",
        "raw_text_fields": False,
    }


def _rebind_candidate(materializer: ModuleType, candidate: dict[str, object]) -> None:
    values = materializer._candidate_values(candidate)
    review = dict(candidate["operator_ground_truth_review"])  # type: ignore[arg-type]
    review["sha256"] = materializer._canonical_sha256(
        materializer._ground_truth_review_payload(candidate, values)
    )
    candidate["operator_ground_truth_review"] = review
    values = materializer._candidate_values(candidate)
    binding = dict(candidate["candidate_binding"])  # type: ignore[arg-type]
    binding_payload = materializer._candidate_binding_payload(candidate, values)
    binding["payload"] = binding_payload
    binding["sha256"] = materializer._canonical_sha256(binding_payload)
    candidate["candidate_binding"] = binding


def _provider_result(
    *,
    passed: bool = True,
    actual_hash: str | None = None,
    unauthorized: bool = False,
    expected_hash: str = EXPECTED_SHA,
    expected_chars: int = 32,
    token_hashes: list[str] | None = None,
    min_token_f1: float = 0.55,
    max_wer: float = 0.55,
) -> dict[str, object]:
    governed_token_hashes = list(token_hashes or [TOKEN_SHA])
    status = "not_authorized" if unauthorized else ("transcribed" if passed else "error")
    evidence_code = "provider_upload_not_authorized" if unauthorized else "provider_error"
    result: dict[str, object] = {
        "status": status,
        "passed": passed and not unauthorized,
        "usable": passed and not unauthorized,
        "intent_correct": passed and not unauthorized,
        "token_f1": 1.0 if passed and not unauthorized else 0.2,
        "min_token_f1": min_token_f1,
        "wer": 0.0 if passed and not unauthorized else 0.9,
        "max_wer": max_wer,
        "ms": 0.0 if unauthorized else 300.0,
        "expected_text_chars": expected_chars,
        "actual_text_chars": expected_chars if passed and not unauthorized else 0,
        "expected_text_sha256": expected_hash,
        "actual_text_sha256": actual_hash
        or (expected_hash if passed and not unauthorized else hashlib.sha256(b"").hexdigest()),
        "required_token_count": len(governed_token_hashes),
        "required_token_sha256": governed_token_hashes,
        "text_mode": "redacted",
        "text_redacted": True,
        "provider_evidence_status": "eligible" if passed and not unauthorized else "blocked",
        "provider_evidence_failed_codes": [] if passed and not unauthorized else [evidence_code],
    }
    if passed and not unauthorized:
        result.update(
            {
                "transcriber": {
                    "family": "cartesia",
                    "identifier_sha256": hashlib.sha256(
                        b"cartesia/ink-whisper+enhanced_wav"
                    ).hexdigest(),
                },
                "scored_text_source": "primary_transcript_text",
            }
        )
    return result


def _transformation(
    materializer: ModuleType,
    *,
    transformation_id: str,
    source_sha: str,
    output_sha: str,
    duration_seconds: float,
) -> dict[str, object]:
    parameters: dict[str, object] = {}
    if transformation_id == "hostile_room_v1":
        parameters = {
            "gain": 1.18,
            "echo_delay_ms": 76,
            "echo_mix": 0.22,
            "noise_cycle_pcm16": [132, -132, 66, -66],
            "speed_factor": 1.0,
        }
    payload = {
        "contract_name": "ea.memorial_stt_audio_transformation_receipt.v1",
        "transformation_id": transformation_id,
        "transformation_version": 1,
        "source_audio_sha256": source_sha,
        "output_audio_sha256": output_sha,
        "source_duration_seconds": duration_seconds,
        "output_duration_seconds": duration_seconds,
        "duration_preserved": True,
        "parameters": parameters,
    }
    return {
        "contract_name": "ea.memorial_stt_audio_transformation_receipt.v1",
        "canonicalization": "json_utf8_sorted_keys_compact_v1",
        "sha256": materializer._canonical_sha256(payload),
        "payload": payload,
    }


def _benchmark_receipt(
    materializer: ModuleType,
    candidate: dict[str, object],
    *,
    candidate_receipt_sha256: str,
) -> dict[str, object]:
    candidate_binding = dict(candidate.get("candidate_binding") or {})  # type: ignore[arg-type]
    binding_payload = dict(candidate_binding.get("payload") or {})  # type: ignore[arg-type]
    entry = dict(candidate.get("candidate_manifest_entry") or {})  # type: ignore[arg-type]
    candidate_binding_sha = str(candidate_binding.get("sha256") or "")
    review_sha = str(dict(candidate["operator_ground_truth_review"]).get("sha256") or "")  # type: ignore[arg-type]
    bundle = dict(candidate.get("bundle") or {})  # type: ignore[arg-type]
    provenance = {
        "origin": str(entry.get("origin") or ""),
        "speaker_consent": str(entry.get("speaker_consent") or ""),
        "allowed_purpose": str(entry.get("allowed_purpose") or ""),
        "retention": str(entry.get("retention") or ""),
        "synthetic": False,
        "accent": str(entry.get("accent") or ""),
        "external_bundle": True,
        "bundle_root": str(bundle.get("root") or ""),
        "bundle_id": str(binding_payload.get("bundle_id") or ""),
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "candidate_binding_contract_name": "ea.memorial_stt_fixture_candidate_binding.v2",
        "candidate_binding_sha256": candidate_binding_sha,
        "operator_ground_truth_review_binding_sha256": review_sha,
        "provider_upload_authorization": copy.deepcopy(
            binding_payload.get("provider_upload_authorization") or {}
        ),
    }
    captured_binding = {
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "candidate_binding_contract_name": "ea.memorial_stt_fixture_candidate_binding.v2",
        "candidate_binding_sha256": candidate_binding_sha,
        "operator_ground_truth_review_binding_sha256": review_sha,
        "source_audio_sha256": str(binding_payload.get("audio_sha256") or ""),
        "bundle_id": str(binding_payload.get("bundle_id") or ""),
        "sample": str(binding_payload.get("sample") or ""),
        "provider_upload_authorization": copy.deepcopy(
            binding_payload.get("provider_upload_authorization") or {}
        ),
    }
    candidate_quality = {
        "status": "pass",
        "failed_codes": [],
        "audio_duration_seconds": 3.0,
        "expected_min_duration_seconds": 2.4,
        "max_duration_seconds": 120.0,
        "wav_format": {
            "audio_format": 1,
            "channels": 1,
            "sample_rate_hz": 16_000,
            "sample_width_bytes": 2,
        },
    }
    rows: list[dict[str, object]] = []
    for sample, variant, actual_sha, transformation_id in (
        ("captured_candidate", "captured", AUDIO_SHA, "identity_v1"),
        ("captured_candidate_hostile", "hostile", HOSTILE_SHA, "hostile_room_v1"),
    ):
        rows.append(
            {
                "sample": sample,
                "variant": variant,
                "fixture": "input.wav",
                "fixture_sha256": actual_sha,
                "source_fixture_sha256": AUDIO_SHA,
                "fixture_quality": copy.deepcopy(candidate_quality),
                "source_fixture_quality": copy.deepcopy(candidate_quality),
                "transformation": _transformation(
                    materializer,
                    transformation_id=transformation_id,
                    source_sha=AUDIO_SHA,
                    output_sha=actual_sha,
                    duration_seconds=3.0,
                ),
                "provenance": copy.deepcopy(provenance),
                "captured_candidate_binding": copy.deepcopy(captured_binding),
                "provider_upload_authorization": copy.deepcopy(
                    binding_payload.get("provider_upload_authorization") or {}
                ),
                "full_runtime": _provider_result(passed=True),
                "onemin_sample": _provider_result(
                    passed=False,
                    actual_hash="e" * 64,
                    unauthorized=True,
                ),
                "shadow": _provider_result(
                    passed=False,
                    actual_hash="f" * 64,
                    unauthorized=True,
                ),
            }
        )

    tracked_issues: list[str] = []
    tracked_specs = materializer._tracked_benchmark_specs(issues=tracked_issues)
    assert not tracked_issues
    for identity, spec in tracked_specs.items():
        sample, variant = identity
        source_sha = str(spec["source_fixture_sha256"])
        actual_sha = (
            source_sha
            if variant == "synthetic"
            else hashlib.sha256(f"{source_sha}:hostile".encode("utf-8")).hexdigest()
        )
        expected_min = float(spec["expected_min_duration_seconds"])
        duration = max(3.0, round(expected_min + 0.5, 3))
        quality = {
            "status": "pass",
            "failed_codes": [],
            "audio_duration_seconds": duration,
            "expected_min_duration_seconds": expected_min,
            "max_duration_seconds": 120.0,
            "wav_format": {
                "audio_format": 1,
                "channels": 1,
                "sample_rate_hz": 16_000,
                "sample_width_bytes": 2,
            },
        }
        authorization = copy.deepcopy(spec["provider_upload_authorization"])
        provider_args = {
            "expected_hash": str(spec["expected_text_sha256"]),
            "expected_chars": int(spec["expected_text_chars"]),
            "token_hashes": list(spec["required_token_sha256"]),
            "min_token_f1": float(spec["min_token_f1"]),
            "max_wer": float(spec["max_wer"]),
        }
        rows.append(
            {
                "sample": sample,
                "variant": variant,
                "fixture": spec["fixture"],
                "fixture_sha256": actual_sha,
                "source_fixture_sha256": source_sha,
                "fixture_quality": copy.deepcopy(quality),
                "source_fixture_quality": copy.deepcopy(quality),
                "transformation": _transformation(
                    materializer,
                    transformation_id=str(spec["transformation_id"]),
                    source_sha=source_sha,
                    output_sha=actual_sha,
                    duration_seconds=duration,
                ),
                "provenance": copy.deepcopy(spec["provenance"]),
                "captured_candidate_binding": {},
                "provider_upload_authorization": authorization,
                "full_runtime": _provider_result(passed=True, **provider_args),
                "onemin_sample": _provider_result(passed=False, **provider_args),
                "shadow": _provider_result(passed=False, **provider_args),
            }
        )

    def provider_summary(provider: str) -> dict[str, object]:
        results = [dict(row[provider]) for row in rows]  # type: ignore[arg-type]
        passed_samples = sum(result["passed"] is True for result in results)
        token_values = [float(result["token_f1"]) for result in results]
        wer_values = [float(result["wer"]) for result in results]
        latencies = [float(result.get("ms") or 0.0) for result in results if float(result.get("ms") or 0.0) > 0]
        return {
            "provider": provider,
            "passed_samples": passed_samples,
            "sample_count": len(results),
            "scored_samples": len(results),
            "intent_correct_samples": sum(result["intent_correct"] is True for result in results),
            "avg_token_f1": round(sum(token_values) / len(token_values), 4),
            "avg_wer": round(sum(wer_values) / len(wer_values), 4),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            "production_eligible": passed_samples == len(results),
        }

    ranking = [provider_summary(provider) for provider in ("full_runtime", "shadow", "onemin_sample")]
    ranking.sort(
        key=lambda item: (
            int(item["passed_samples"]),
            int(item["scored_samples"]),
            int(item["intent_correct_samples"]),
            float(item["avg_token_f1"]),
            -float(item["avg_wer"]),
            -float(item["avg_latency_ms"]),
        ),
        reverse=True,
    )
    return {
        "contract_name": "ea.memorial_stt_provider_benchmark",
        "generated_at": GENERATED_AT,
        "generated_by": "scripts/benchmark_memorial_stt_providers.py",
        **_source_stamps(materializer),
        "captured_candidate_binding": captured_binding,
        "status": "pass",
        "scoring": copy.deepcopy(materializer._EXPECTED_SCORING),
        "fixture_quality_status": "pass",
        "fixture_quality_failed_codes": [],
        "availability": {
            "providers": {
                "full_runtime": {"configured": True, "credential_source": "direct_env"},
                "shadow": {"configured": True, "provider_family": "blipai"},
                "onemin_sample": {"configured": False, "key_count": 0, "max_key_attempts": 3},
            },
            "credential_environment": {
                "file_count": 0,
                "loaded_count": 0,
                "provider_families": {
                    "cartesia": True,
                    "onemin": False,
                    "blipai_shadow": True,
                },
            },
            "governance_preflight": {
                "blocked": False,
                "failed_codes": [],
                "external_candidate_failed_codes": [],
                "tracked_fixture_failed_codes": [],
                "captured_candidate_pair_count": 1,
            },
        },
        "provider_ranking": ranking,
        "rows": rows,
    }


def _case(
    tmp_path: Path,
    *,
    candidate_mutator: Callable[[dict[str, object]], None] | None = None,
    benchmark_mutator: Callable[[dict[str, object]], None] | None = None,
) -> tuple[ModuleType, ModuleType, Path, Path, Path, dict[str, object]]:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    verifier = _load_script("verify_memorial_stt_captured_candidate_diagnostic")
    candidate_path = tmp_path / "candidate.json"
    benchmark_path = tmp_path / "benchmark.json"
    output_path = tmp_path / "diagnostic.json"
    candidate = _candidate_receipt(materializer)
    if candidate_mutator:
        candidate_mutator(candidate)
    _write(candidate_path, candidate)
    benchmark = _benchmark_receipt(
        materializer,
        candidate,
        candidate_receipt_sha256=_file_sha(candidate_path),
    )
    if benchmark_mutator:
        benchmark_mutator(benchmark)
    _write(benchmark_path, benchmark)
    receipt = materializer.materialize_diagnostic(
        output_path=output_path,
        candidate_receipt_path=candidate_path,
        benchmark_receipt_path=benchmark_path,
        generated_at=GENERATED_AT,
    )
    return materializer, verifier, candidate_path, benchmark_path, output_path, receipt


def _verify(
    verifier: ModuleType,
    output: Path,
    candidate: Path,
    benchmark: Path,
) -> dict[str, object]:
    return verifier.verify_diagnostic(
        output,
        candidate_receipt_path=candidate,
        benchmark_receipt_path=benchmark,
    )


def test_diagnostic_passes_only_with_exact_current_bound_pair(tmp_path: Path) -> None:
    materializer, verifier, candidate, benchmark, output, receipt = _case(tmp_path)

    assert receipt["status"] == "pass"
    assert receipt["promotion_allowed"] is True
    assert receipt["may_update_fixture_manifest"] is True
    assert receipt["captured_row_count"] == 2
    assert receipt["generated_by"] == "scripts/materialize_memorial_stt_captured_candidate_diagnostic.py"
    input_binding = dict(receipt["input_binding"])  # type: ignore[arg-type]
    assert input_binding["contract_name"] == "ea.memorial_stt_captured_candidate_diagnostic_input_binding.v1"
    assert input_binding["sha256"] == materializer._canonical_sha256(input_binding["payload"])
    assert receipt["input_binding_sha256"] == input_binding["sha256"]
    assert _verify(verifier, output, candidate, benchmark)["status"] == "pass"
    rendered = json.dumps(receipt).lower()
    assert '"actual_text"' not in rendered
    assert '"expected_text"' not in rendered
    assert "operator_full_text_debug" not in rendered
    assert "benchmark_text_mode=full" not in rendered
    assert "[private_bundle]" not in rendered


def _candidate_contract_wrong(payload: dict[str, object]) -> None:
    payload["contract_name"] = "ea.wrong"


def _candidate_version_wrong(payload: dict[str, object]) -> None:
    payload["contract_version"] = 1


def _candidate_generated_by_wrong(payload: dict[str, object]) -> None:
    payload["generated_by"] = "operator.py"


def _candidate_blocked(payload: dict[str, object]) -> None:
    payload["status"] = "blocked"
    payload["failed_codes"] = ["fixture_invalid"]


def _candidate_scope_wrong(payload: dict[str, object]) -> None:
    payload["candidate_scope"] = "promotion_authority"


def _candidate_raw(payload: dict[str, object]) -> None:
    payload["text_mode"] = "full"
    payload["privacy_mode"] = "full"
    payload["raw_text_fields"] = True


def _candidate_stale(payload: dict[str, object]) -> None:
    payload["generated_at"] = _at(hours=-73)


def _candidate_future(payload: dict[str, object]) -> None:
    payload["generated_at"] = (
        datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=6)
    ).isoformat().replace("+00:00", "Z")


def _candidate_head_wrong(payload: dict[str, object]) -> None:
    payload["source_git_head"] = "stale-head"


def _candidate_fingerprint_wrong(payload: dict[str, object]) -> None:
    payload["source_state_fingerprint"] = "stale-fingerprint"


def _candidate_review_tampered(payload: dict[str, object]) -> None:
    review = dict(payload["operator_ground_truth_review"])
    review["sha256"] = "9" * 64
    payload["operator_ground_truth_review"] = review


def _candidate_binding_tampered(payload: dict[str, object]) -> None:
    binding = dict(payload["candidate_binding"])
    binding["sha256"] = "8" * 64
    payload["candidate_binding"] = binding


def _candidate_legacy_missing_binding(payload: dict[str, object]) -> None:
    payload.pop("candidate_binding", None)


@pytest.mark.parametrize(
    ("mutator", "issue"),
    [
        (_candidate_contract_wrong, "candidate_contract_mismatch"),
        (_candidate_version_wrong, "candidate_contract_version_mismatch"),
        (_candidate_generated_by_wrong, "candidate_generated_by_mismatch"),
        (_candidate_blocked, "candidate_status_not_pass"),
        (_candidate_scope_wrong, "candidate_scope_mismatch"),
        (_candidate_raw, "candidate_redaction_contract_invalid"),
        (_candidate_stale, "candidate_generated_at_stale"),
        (_candidate_future, "candidate_generated_at_future"),
        (_candidate_head_wrong, "candidate_source_git_head_not_current"),
        (_candidate_fingerprint_wrong, "candidate_source_state_fingerprint_not_current"),
        (_candidate_review_tampered, "candidate_ground_truth_review_binding_mismatch"),
        (_candidate_binding_tampered, "candidate_binding_sha256_mismatch"),
        (_candidate_legacy_missing_binding, "candidate_binding_shape_invalid"),
    ],
)
def test_candidate_envelope_and_binding_fail_closed(
    tmp_path: Path,
    mutator: Callable[[dict[str, object]], None],
    issue: str,
) -> None:
    _materializer, _verifier, _candidate, _benchmark, _output, receipt = _case(
        tmp_path,
        candidate_mutator=mutator,
    )

    assert receipt["status"] == "blocked"
    assert receipt["promotion_allowed"] is False
    assert issue in receipt["issues"]


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        ("speaker_consent", "consent_denied", "candidate_speaker_consent_not_authorized"),
        ("retention", "publish_without_limit", "candidate_retention_not_authorized"),
        ("reviewer_authority", "untrusted_reviewer", "candidate_ground_truth_review_not_approved"),
        ("origin", "unapproved_private_origin", "candidate_manifest_entry_origin_invalid"),
        ("file", "../private.wav", "candidate_manifest_entry_file_invalid"),
    ],
)
def test_candidate_policy_enums_fail_closed_even_when_rebound(
    tmp_path: Path,
    field: str,
    value: str,
    issue: str,
) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")

    def mutate(candidate: dict[str, object]) -> None:
        if field == "reviewer_authority":
            review = dict(candidate["operator_ground_truth_review"])  # type: ignore[arg-type]
            review[field] = value
            candidate["operator_ground_truth_review"] = review
        else:
            entry = dict(candidate["candidate_manifest_entry"])  # type: ignore[arg-type]
            entry[field] = value
            candidate["candidate_manifest_entry"] = entry
        _rebind_candidate(materializer, candidate)

    _materializer, verifier, candidate, benchmark, output, receipt = _case(
        tmp_path,
        candidate_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert issue in receipt["issues"]
    assert value not in output.read_text(encoding="utf-8")
    assert _verify(verifier, output, candidate, benchmark)["status"] == "pass"


def test_public_receipt_and_cli_never_echo_wrong_type_source_scalar(tmp_path: Path) -> None:
    sentinel = "private-phrase-that-must-never-appear"

    def mutate(candidate: dict[str, object]) -> None:
        audio = dict(candidate["audio"])  # type: ignore[arg-type]
        audio["bytes"] = sentinel
        candidate["audio"] = audio

    _materializer, verifier, candidate, benchmark, output, receipt = _case(
        tmp_path,
        candidate_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert "candidate_audio_byte_limits_invalid" in receipt["issues"]
    assert sentinel not in output.read_text(encoding="utf-8")
    assert _verify(verifier, output, candidate, benchmark)["status"] == "pass"

    cli_output = tmp_path / "diagnostic-cli.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "materialize_memorial_stt_captured_candidate_diagnostic.py"),
            "--candidate-receipt",
            str(candidate),
            "--benchmark-receipt",
            str(benchmark),
            "--output",
            str(cli_output),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert sentinel not in completed.stdout
    assert sentinel not in cli_output.read_text(encoding="utf-8")


def test_provider_public_summary_never_echoes_wrong_type_or_identifier(tmp_path: Path) -> None:
    sentinel = "private provider transcript disguised as metadata"

    def mutate(benchmark: dict[str, object]) -> None:
        rows = list(benchmark["rows"])
        row = dict(rows[0])
        result = dict(row["full_runtime"])
        result["actual_text_chars"] = sentinel
        result["transcriber"] = sentinel
        result["debug_transcript"] = sentinel
        row["full_runtime"] = result
        rows[0] = row
        benchmark["rows"] = rows

    _materializer, verifier, candidate, benchmark, output, receipt = _case(
        tmp_path,
        benchmark_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert "benchmark_captured_full_runtime_actual_text_chars_invalid" in receipt["issues"]
    assert "benchmark_captured_full_runtime_transcriber_invalid" in receipt["issues"]
    assert "benchmark_raw_text_exposed" in receipt["issues"]
    assert sentinel not in output.read_text(encoding="utf-8")
    assert _verify(verifier, output, candidate, benchmark)["status"] == "pass"


@pytest.mark.parametrize(
    ("duration", "issue"),
    [
        (1.0, "candidate_fixture_quality_duration_policy_invalid"),
        (121.0, "candidate_fixture_quality_duration_policy_invalid"),
    ],
)
def test_candidate_duration_policy_is_recomputed_from_bound_numbers(
    tmp_path: Path,
    duration: float,
    issue: str,
) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")

    def mutate(candidate: dict[str, object]) -> None:
        audio = dict(candidate["audio"])  # type: ignore[arg-type]
        audio["duration_seconds"] = duration
        candidate["audio"] = audio
        quality = dict(candidate["fixture_quality"])  # type: ignore[arg-type]
        quality["audio_duration_seconds"] = duration
        candidate["fixture_quality"] = quality
        _rebind_candidate(materializer, candidate)

    _materializer, _verifier, _candidate, _benchmark, _output, receipt = _case(
        tmp_path,
        candidate_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert issue in receipt["issues"]


def test_candidate_must_explicitly_authorize_full_runtime_upload(tmp_path: Path) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")

    def mutate(candidate: dict[str, object]) -> None:
        authorization = dict(UPLOAD_AUTHORIZATION)
        authorization["full_runtime"] = False
        entry = dict(candidate["candidate_manifest_entry"])  # type: ignore[arg-type]
        entry["provider_upload_authorization"] = authorization
        candidate["candidate_manifest_entry"] = entry
        _rebind_candidate(materializer, candidate)

    _materializer, _verifier, _candidate, _benchmark, _output, receipt = _case(
        tmp_path,
        candidate_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert "candidate_full_runtime_upload_not_authorized" in receipt["issues"]


@pytest.mark.parametrize(
    ("authorization", "issue"),
    [
        (
            {**UPLOAD_AUTHORIZATION, "unexpected_lane": False},
            "candidate_provider_upload_authorization_shape_invalid",
        ),
        (
            {**UPLOAD_AUTHORIZATION, "shadow": "false"},
            "candidate_provider_upload_authorization_type_invalid",
        ),
    ],
)
def test_candidate_upload_authorization_has_exact_boolean_schema(
    tmp_path: Path,
    authorization: dict[str, object],
    issue: str,
) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")

    def mutate(candidate: dict[str, object]) -> None:
        entry = dict(candidate["candidate_manifest_entry"])  # type: ignore[arg-type]
        entry["provider_upload_authorization"] = authorization
        candidate["candidate_manifest_entry"] = entry
        _rebind_candidate(materializer, candidate)

    _materializer, _verifier, _candidate, _benchmark, _output, receipt = _case(
        tmp_path,
        candidate_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert issue in receipt["issues"]


@pytest.mark.parametrize("source", ["candidate", "benchmark", "row_quality"])
def test_wrong_type_failure_collections_never_mean_no_failures(tmp_path: Path, source: str) -> None:
    def mutate_candidate(candidate: dict[str, object]) -> None:
        if source == "candidate":
            candidate["failed_codes"] = "revoked"

    def mutate_benchmark(benchmark: dict[str, object]) -> None:
        if source == "benchmark":
            benchmark["fixture_quality_failed_codes"] = "fixture_invalid"
        elif source == "row_quality":
            rows = list(benchmark["rows"])
            row = dict(rows[0])
            quality = dict(row["fixture_quality"])
            quality["failed_codes"] = "fixture_invalid"
            row["fixture_quality"] = quality
            rows[0] = row
            benchmark["rows"] = rows

    _materializer, _verifier, _candidate, _benchmark, _output, receipt = _case(
        tmp_path,
        candidate_mutator=mutate_candidate,
        benchmark_mutator=mutate_benchmark,
    )

    assert receipt["status"] == "blocked"
    assert any(issue.endswith("failed_codes_invalid") for issue in receipt["issues"])


def _benchmark_contract_wrong(payload: dict[str, object]) -> None:
    payload["contract_name"] = "ea.wrong"


def _benchmark_generated_by_wrong(payload: dict[str, object]) -> None:
    payload["generated_by"] = "operator.py"


def _benchmark_blocked(payload: dict[str, object]) -> None:
    payload["status"] = "blocked"


def _benchmark_quality_blocked(payload: dict[str, object]) -> None:
    payload["fixture_quality_status"] = "blocked"
    payload["fixture_quality_failed_codes"] = ["fixture_invalid"]


def _benchmark_raw(payload: dict[str, object]) -> None:
    scoring = dict(payload["scoring"])
    scoring["text_mode"] = "full"
    scoring["raw_transcript_fields"] = True
    payload["scoring"] = scoring


def _benchmark_stale(payload: dict[str, object]) -> None:
    payload["generated_at"] = _at(hours=-73)


def _benchmark_future(payload: dict[str, object]) -> None:
    payload["generated_at"] = (
        datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=6)
    ).isoformat().replace("+00:00", "Z")


def _benchmark_binding_wrong(payload: dict[str, object]) -> None:
    binding = dict(payload["captured_candidate_binding"])
    binding["candidate_receipt_sha256"] = "0" * 64
    payload["captured_candidate_binding"] = binding


def _benchmark_duplicate(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    rows.append(copy.deepcopy(rows[0]))
    payload["rows"] = rows


def _benchmark_extra_associated(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    extra = copy.deepcopy(rows[0])
    extra["sample"] = "captured_candidate_extra"
    rows.append(extra)
    payload["rows"] = rows


def _benchmark_captured_actual_wrong(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[0])
    row["fixture_sha256"] = HOSTILE_SHA
    rows[0] = row
    payload["rows"] = rows


def _benchmark_hostile_identity(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[1])
    row["fixture_sha256"] = AUDIO_SHA
    rows[1] = row
    payload["rows"] = rows


def _benchmark_transformation_parameters_tampered(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[1])
    transformation = dict(row["transformation"])
    transformation_payload = dict(transformation["payload"])
    transformation_payload["parameters"] = {"gain": 9.0}
    transformation["payload"] = transformation_payload
    # A self-consistent attacker-controlled hash must still be rejected by the governed recipe check.
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    transformation["sha256"] = materializer._canonical_sha256(transformation_payload)
    row["transformation"] = transformation
    rows[1] = row
    payload["rows"] = rows


def _benchmark_transformation_duration_tampered(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[1])
    transformation = dict(row["transformation"])
    transformation_payload = dict(transformation["payload"])
    transformation_payload["output_duration_seconds"] = 99.0
    transformation_payload["duration_preserved"] = False
    transformation["payload"] = transformation_payload
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    transformation["sha256"] = materializer._canonical_sha256(transformation_payload)
    row["transformation"] = transformation
    rows[1] = row
    payload["rows"] = rows


def _benchmark_provider_binding_wrong(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[0])
    provider = dict(row["full_runtime"])
    provider["expected_text_sha256"] = "7" * 64
    row["full_runtime"] = provider
    rows[0] = row
    payload["rows"] = rows


def _benchmark_full_runtime_failed(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[0])
    row["full_runtime"] = _provider_result(passed=False)
    rows[0] = row
    payload["rows"] = rows


def _benchmark_ranking_overclaim(payload: dict[str, object]) -> None:
    ranking = list(payload["provider_ranking"])
    summary = dict(ranking[0])
    summary["passed_samples"] = 1
    summary["production_eligible"] = True
    ranking[0] = summary
    payload["provider_ranking"] = ranking


def _benchmark_legacy_source_missing(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[0])
    row.pop("source_fixture_sha256", None)
    rows[0] = row
    payload["rows"] = rows


def _benchmark_provider_thresholds_weakened(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[0])
    provider = dict(row["full_runtime"])
    provider["actual_text_sha256"] = "9" * 64
    provider["token_f1"] = 0.0
    provider["min_token_f1"] = -1.0
    provider["wer"] = 99.0
    provider["max_wer"] = 100.0
    row["full_runtime"] = provider
    rows[0] = row
    payload["rows"] = rows


def _benchmark_provider_passes_invalid_fixture(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[0])
    provider = dict(row["full_runtime"])
    provider["fixture_invalid"] = True
    row["full_runtime"] = provider
    rows[0] = row
    payload["rows"] = rows


def _benchmark_provider_status_forged(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[0])
    provider = dict(row["full_runtime"])
    provider["status"] = "forged_success"
    row["full_runtime"] = provider
    rows[0] = row
    payload["rows"] = rows


def _benchmark_unauthorized_lane_claims_provider_attempt(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[0])
    provider = dict(row["onemin_sample"])
    provider["status"] = "error"
    provider["provider_evidence_failed_codes"] = ["provider_error"]
    row["onemin_sample"] = provider
    rows[0] = row
    payload["rows"] = rows


def _benchmark_row_duration_below_minimum(payload: dict[str, object]) -> None:
    rows = list(payload["rows"])
    row = dict(rows[0])
    quality = dict(row["fixture_quality"])
    quality["expected_min_duration_seconds"] = 4.0
    row["fixture_quality"] = quality
    rows[0] = row
    payload["rows"] = rows


def _benchmark_disguised_candidate_receipt_link(payload: dict[str, object]) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    rows = list(payload["rows"])
    extra = copy.deepcopy(rows[0])
    unrelated_sha = "1" * 64
    extra["sample"] = "candidate_evasion_copy"
    extra["variant"] = "synthetic"
    extra["source_fixture_sha256"] = unrelated_sha
    extra["fixture_sha256"] = unrelated_sha
    transformation = dict(extra["transformation"])
    transformation_payload = dict(transformation["payload"])
    transformation_payload["source_audio_sha256"] = unrelated_sha
    transformation_payload["output_audio_sha256"] = unrelated_sha
    transformation["payload"] = transformation_payload
    transformation["sha256"] = materializer._canonical_sha256(transformation_payload)
    extra["transformation"] = transformation
    provenance = dict(extra["provenance"])
    provenance["external_bundle"] = False
    provenance["bundle_id"] = "other-bundle"
    provenance["candidate_binding_sha256"] = "2" * 64
    provenance["operator_ground_truth_review_binding_sha256"] = "3" * 64
    # The exact candidate receipt hash is the only surviving candidate linkage.
    extra["provenance"] = provenance
    row_binding = dict(extra["captured_candidate_binding"])
    row_binding.update(
        {
            "candidate_receipt_sha256": "4" * 64,
            "candidate_binding_sha256": "5" * 64,
            "operator_ground_truth_review_binding_sha256": "6" * 64,
            "source_audio_sha256": unrelated_sha,
            "bundle_id": "other-bundle",
            "sample": "candidate_evasion_copy",
        }
    )
    extra["captured_candidate_binding"] = row_binding
    rows.append(extra)
    payload["rows"] = rows
    ranking = list(payload["provider_ranking"])
    summary = dict(ranking[0])
    summary["sample_count"] = 3
    summary["passed_samples"] = 3
    ranking[0] = summary
    payload["provider_ranking"] = ranking


def _benchmark_disguised_review_link(payload: dict[str, object]) -> None:
    _benchmark_disguised_candidate_receipt_link(payload)
    rows = list(payload["rows"])
    original_provenance = dict(rows[0]["provenance"])
    extra = dict(rows[-1])
    provenance = dict(extra["provenance"])
    provenance["candidate_receipt_sha256"] = "4" * 64
    provenance["operator_ground_truth_review_binding_sha256"] = original_provenance[
        "operator_ground_truth_review_binding_sha256"
    ]
    extra["provenance"] = provenance
    rows[-1] = extra
    payload["rows"] = rows


@pytest.mark.parametrize(
    ("mutator", "issue"),
    [
        (_benchmark_contract_wrong, "benchmark_contract_mismatch"),
        (_benchmark_generated_by_wrong, "benchmark_generated_by_mismatch"),
        (_benchmark_blocked, "benchmark_status_not_pass"),
        (_benchmark_quality_blocked, "benchmark_fixture_quality_gate_not_pass"),
        (_benchmark_raw, "benchmark_redaction_contract_invalid"),
        (_benchmark_stale, "benchmark_generated_at_stale"),
        (_benchmark_future, "benchmark_generated_at_future"),
        (_benchmark_binding_wrong, "benchmark_captured_candidate_binding_mismatch"),
        (_benchmark_duplicate, "benchmark_external_candidate_rows_not_exact_pair"),
        (_benchmark_extra_associated, "benchmark_external_candidate_rows_not_exact_pair"),
        (_benchmark_captured_actual_wrong, "benchmark_captured_actual_fixture_not_identity"),
        (_benchmark_hostile_identity, "benchmark_hostile_actual_fixture_not_transformed"),
        (_benchmark_transformation_parameters_tampered, "benchmark_hostile_room_v1_transformation_parameters_invalid"),
        (_benchmark_transformation_duration_tampered, "benchmark_hostile_room_v1_transformation_output_duration_mismatch"),
        (_benchmark_provider_binding_wrong, "benchmark_captured_full_runtime_expected_text_binding_mismatch"),
        (_benchmark_full_runtime_failed, "benchmark_captured_full_runtime_not_pass"),
        (_benchmark_ranking_overclaim, "benchmark_provider_ranking_not_derived_from_rows"),
        (_benchmark_legacy_source_missing, "benchmark_captured_row_source_fixture_mismatch"),
        (_benchmark_provider_thresholds_weakened, "benchmark_captured_full_runtime_min_token_f1_invalid"),
        (_benchmark_provider_passes_invalid_fixture, "benchmark_captured_full_runtime_pass_contradiction"),
        (_benchmark_provider_status_forged, "benchmark_captured_full_runtime_status_invalid"),
        (
            _benchmark_unauthorized_lane_claims_provider_attempt,
            "benchmark_captured_onemin_sample_unauthorized_upload_evidence_invalid",
        ),
        (_benchmark_row_duration_below_minimum, "benchmark_captured_row_fixture_quality_duration_policy_invalid"),
        (_benchmark_disguised_candidate_receipt_link, "benchmark_external_candidate_rows_not_exact_pair"),
        (_benchmark_disguised_review_link, "benchmark_external_candidate_rows_not_exact_pair"),
    ],
)
def test_benchmark_evidence_and_external_pair_fail_closed(
    tmp_path: Path,
    mutator: Callable[[dict[str, object]], None],
    issue: str,
) -> None:
    _materializer, _verifier, _candidate, _benchmark, _output, receipt = _case(
        tmp_path,
        benchmark_mutator=mutator,
    )

    assert receipt["status"] == "blocked"
    assert receipt["promotion_allowed"] is False
    assert issue in receipt["issues"]


@pytest.mark.parametrize(
    ("row_index", "field", "issue"),
    [
        (0, "fixture", "benchmark_captured_row_fixture_mismatch"),
        (2, "fixture", "benchmark_row_2_fixture_mismatch"),
        (0, "bundle_root", "benchmark_captured_row_provenance_bundle_root_mismatch"),
        (2, "origin", "benchmark_row_2_provenance_invalid"),
    ],
)
def test_every_row_fixture_and_provenance_reject_arbitrary_carriers(
    tmp_path: Path,
    row_index: int,
    field: str,
    issue: str,
) -> None:
    sentinel = "private-carrier-that-must-not-be-echoed"

    def mutate(benchmark: dict[str, object]) -> None:
        rows = list(benchmark["rows"])
        row = dict(rows[row_index])
        if field == "fixture":
            row["fixture"] = sentinel
        else:
            provenance = dict(row["provenance"])
            provenance[field] = sentinel
            row["provenance"] = provenance
        rows[row_index] = row
        benchmark["rows"] = rows

    _materializer, _verifier, _candidate, _benchmark, output, receipt = _case(
        tmp_path,
        benchmark_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert issue in receipt["issues"]
    assert sentinel not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        ("detail", "private provider response", "benchmark_row_2_shadow_detail_invalid"),
        ("reason", "private provider response", "benchmark_row_2_shadow_shape_invalid"),
        (
            "detail",
            {
                "contract_name": "ea.memorial_stt_provider_error_detail.v1",
                "category": "provider_error",
                "code": "arbitrary_private_code",
                "detail_sha256": "1" * 64,
            },
            "benchmark_row_2_shadow_detail_invalid",
        ),
    ],
)
def test_provider_detail_and_reason_accept_only_safe_public_contract(
    tmp_path: Path,
    field: str,
    value: object,
    issue: str,
) -> None:
    def mutate(benchmark: dict[str, object]) -> None:
        rows = list(benchmark["rows"])
        row = dict(rows[2])
        provider = dict(row["shadow"])
        provider[field] = value
        row["shadow"] = provider
        rows[2] = row
        benchmark["rows"] = rows

    _materializer, _verifier, _candidate, _benchmark, output, receipt = _case(
        tmp_path,
        benchmark_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert issue in receipt["issues"]
    assert "private provider response" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("mutation", "issue"),
    [
        ("extra", "benchmark_availability_shape_invalid"),
        ("credential", "benchmark_availability_full_runtime_invalid"),
        ("family_type", "benchmark_availability_credential_environment_invalid"),
        ("preflight", "benchmark_availability_governance_preflight_blocked"),
    ],
)
def test_availability_has_exact_typed_safe_schema(
    tmp_path: Path,
    mutation: str,
    issue: str,
) -> None:
    def mutate(benchmark: dict[str, object]) -> None:
        availability = copy.deepcopy(benchmark["availability"])
        if mutation == "extra":
            availability["operator_hint"] = "private carrier"
        elif mutation == "credential":
            availability["providers"]["full_runtime"]["credential_source"] = "private carrier"
        elif mutation == "family_type":
            availability["credential_environment"]["provider_families"]["cartesia"] = "yes"
        else:
            availability["governance_preflight"]["blocked"] = True
            availability["governance_preflight"]["failed_codes"] = ["fixture_invalid"]
        benchmark["availability"] = availability

    _materializer, _verifier, _candidate, _benchmark, output, receipt = _case(
        tmp_path,
        benchmark_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert issue in receipt["issues"]
    assert "private carrier" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("mutation", "issue"),
    [
        ("extra", "benchmark_provider_ranking_0_shape_invalid"),
        ("unknown", "benchmark_provider_ranking_provider_set_invalid"),
        ("structured", "benchmark_provider_ranking_provider_set_invalid"),
        ("duplicate", "benchmark_provider_ranking_provider_set_invalid"),
        ("metric", "benchmark_provider_ranking_not_derived_from_rows"),
    ],
)
def test_ranking_is_exact_unique_and_derived_from_governed_rows(
    tmp_path: Path,
    mutation: str,
    issue: str,
) -> None:
    def mutate(benchmark: dict[str, object]) -> None:
        ranking = copy.deepcopy(benchmark["provider_ranking"])
        if mutation == "extra":
            ranking[0]["metadata"] = "private carrier"
        elif mutation == "unknown":
            ranking[0]["provider"] = "private_provider"
        elif mutation == "structured":
            ranking[0]["provider"] = {"private": "carrier"}
        elif mutation == "duplicate":
            ranking[1]["provider"] = ranking[0]["provider"]
        else:
            ranking[0]["avg_token_f1"] = 0.1234
        benchmark["provider_ranking"] = ranking

    _materializer, _verifier, _candidate, _benchmark, output, receipt = _case(
        tmp_path,
        benchmark_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert issue in receipt["issues"]
    assert "private carrier" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("mutation", "issue"),
    [
        ("threshold", "benchmark_row_2_full_runtime_min_token_f1_policy_mismatch"),
        ("forged_status", "benchmark_row_2_full_runtime_status_invalid"),
        ("evidence", "benchmark_row_2_full_runtime_successful_evidence_state_invalid"),
        ("optional_forged", "benchmark_row_2_shadow_status_invalid"),
        ("unauthorized_success", "benchmark_row_0_onemin_sample_unauthorized_evidence_state_invalid"),
    ],
)
def test_every_ranked_row_uses_governed_threshold_and_provider_state_table(
    tmp_path: Path,
    mutation: str,
    issue: str,
) -> None:
    def mutate(benchmark: dict[str, object]) -> None:
        rows = list(benchmark["rows"])
        row_index = 0 if mutation == "unauthorized_success" else 2
        row = dict(rows[row_index])
        provider_name = (
            "onemin_sample"
            if mutation == "unauthorized_success"
            else "shadow"
            if mutation == "optional_forged"
            else "full_runtime"
        )
        provider = dict(row[provider_name])
        if mutation == "threshold":
            provider["min_token_f1"] = 0.0
        elif mutation in {"forged_status", "optional_forged"}:
            provider["status"] = "forged_success"
        elif mutation == "evidence":
            provider["provider_evidence_status"] = "blocked"
            provider["provider_evidence_failed_codes"] = ["provider_error"]
        else:
            provider["status"] = "success"
        row[provider_name] = provider
        rows[row_index] = row
        benchmark["rows"] = rows

    _materializer, _verifier, _candidate, _benchmark, _output, receipt = _case(
        tmp_path,
        benchmark_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert issue in receipt["issues"]


@pytest.mark.parametrize("field", ["event_type", "reason"])
def test_candidate_bundle_code_digest_is_recomputed(field: str, tmp_path: Path) -> None:
    def mutate(candidate: dict[str, object]) -> None:
        bundle = dict(candidate["bundle"])
        bundle[f"{field}_code"] = "other"
        bundle[f"{field}_sha256"] = "0" * 64
        candidate["bundle"] = bundle

    _materializer, _verifier, _candidate, _benchmark, _output, receipt = _case(
        tmp_path,
        candidate_mutator=mutate,
    )

    assert receipt["status"] == "blocked"
    assert f"candidate_bundle_{field}_binding_invalid" in receipt["issues"]


def test_blocked_truthful_diagnostic_verifies(tmp_path: Path) -> None:
    materializer, verifier, candidate, benchmark, output, _receipt = _case(tmp_path)
    blocked_candidate = _candidate_receipt(materializer, status="blocked")
    _write(candidate, blocked_candidate)
    blocked_benchmark = _benchmark_receipt(
        materializer,
        blocked_candidate,
        candidate_receipt_sha256=_file_sha(candidate),
    )
    _write(benchmark, blocked_benchmark)
    receipt = materializer.materialize_diagnostic(
        output_path=output,
        candidate_receipt_path=candidate,
        benchmark_receipt_path=benchmark,
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "blocked"
    assert "candidate_status_not_pass" in receipt["issues"]
    assert _verify(verifier, output, candidate, benchmark)["status"] == "pass"


@pytest.mark.parametrize("tamper", ["flags", "path", "binding", "row", "raw_text"])
def test_verifier_reopens_sources_and_rejects_self_asserted_or_injected_receipt(
    tmp_path: Path,
    tamper: str,
) -> None:
    _materializer, verifier, candidate, benchmark, output, _receipt = _case(tmp_path)
    payload = json.loads(output.read_text(encoding="utf-8"))
    if tamper == "flags":
        payload["status"] = "blocked"
        payload["promotion_allowed"] = False
        payload["may_update_fixture_manifest"] = False
    elif tamper == "path":
        payload["candidate_receipt"]["path"] = "/etc/passwd"
    elif tamper == "binding":
        payload["input_binding"]["sha256"] = "0" * 64
        payload["input_binding_sha256"] = "0" * 64
    elif tamper == "row":
        payload["captured_rows"].append(copy.deepcopy(payload["captured_rows"][0]))
        payload["captured_row_count"] = 3
    else:
        payload["captured_rows"][0]["providers"]["full_runtime"]["actual_text"] = "private transcript"
    _write(output, payload)

    verification = _verify(verifier, output, candidate, benchmark)

    assert verification["status"] == "fail"
    assert "diagnostic_semantic_payload_mismatch" in verification["issues"]


def test_verifier_rejects_stale_and_future_diagnostic_receipts(tmp_path: Path) -> None:
    materializer, verifier, candidate, benchmark, output, _receipt = _case(tmp_path)
    observed_at = datetime.now(UTC).replace(microsecond=0)
    for generated_at, expected_issue in (
        (
            (observed_at - timedelta(hours=73)).isoformat().replace("+00:00", "Z"),
            "diagnostic_generated_at_stale",
        ),
        (
            (observed_at + timedelta(minutes=6)).isoformat().replace("+00:00", "Z"),
            "diagnostic_generated_at_future",
        ),
    ):
        materializer.materialize_diagnostic(
            output_path=output,
            candidate_receipt_path=candidate,
            benchmark_receipt_path=benchmark,
            generated_at=generated_at,
        )
        verification = _verify(verifier, output, candidate, benchmark)
        assert verification["status"] == "fail"
        assert expected_issue in verification["issues"]


def test_invalid_generated_at_is_rejected_without_echo(tmp_path: Path) -> None:
    materializer, verifier, candidate, benchmark, output, _receipt = _case(tmp_path)
    sentinel = "private timestamp-shaped transcript"

    with pytest.raises(ValueError, match="diagnostic_generated_at_invalid_or_timezone_missing"):
        materializer.materialize_diagnostic(
            output_path=tmp_path / "invalid.json",
            candidate_receipt_path=candidate,
            benchmark_receipt_path=benchmark,
            generated_at=sentinel,
        )

    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["generated_at"] = sentinel
    _write(output, payload)
    verification = _verify(verifier, output, candidate, benchmark)
    assert verification["status"] == "fail"
    assert sentinel not in json.dumps(verification)


def test_verifier_detects_source_changed_after_materialization(tmp_path: Path) -> None:
    _materializer, verifier, candidate, benchmark, output, _receipt = _case(tmp_path)
    candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
    candidate_payload["status"] = "blocked"
    candidate_payload["failed_codes"] = ["revoked"]
    _write(candidate, candidate_payload)

    verification = _verify(verifier, output, candidate, benchmark)

    assert verification["status"] == "fail"
    assert "diagnostic_input_binding_payload_mismatch" in verification["issues"]
    assert "diagnostic_semantic_payload_mismatch" in verification["issues"]


def test_source_receipt_symlinks_are_not_followed(tmp_path: Path) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    verifier = _load_script("verify_memorial_stt_captured_candidate_diagnostic")
    real_candidate = tmp_path / "real-candidate.json"
    candidate = tmp_path / "candidate-link.json"
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "diagnostic.json"
    candidate_payload = _candidate_receipt(materializer)
    _write(real_candidate, candidate_payload)
    candidate.symlink_to(real_candidate)
    _write(
        benchmark,
        _benchmark_receipt(
            materializer,
            candidate_payload,
            candidate_receipt_sha256=_file_sha(real_candidate),
        ),
    )

    receipt = materializer.materialize_diagnostic(
        output_path=output,
        candidate_receipt_path=candidate,
        benchmark_receipt_path=benchmark,
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "blocked"
    assert "candidate_receipt_missing_or_invalid" in receipt["issues"]
    assert receipt["candidate_receipt"] == {"path": "[candidate_receipt]", "exists": False}
    assert _verify(verifier, output, candidate, benchmark)["status"] == "pass"


def test_materializer_refuses_symlink_output(tmp_path: Path) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    candidate = tmp_path / "candidate.json"
    benchmark = tmp_path / "benchmark.json"
    target = tmp_path / "target.json"
    output = tmp_path / "diagnostic-link.json"
    candidate_payload = _candidate_receipt(materializer)
    _write(candidate, candidate_payload)
    _write(
        benchmark,
        _benchmark_receipt(
            materializer,
            candidate_payload,
            candidate_receipt_sha256=_file_sha(candidate),
        ),
    )
    target.write_text("unchanged", encoding="utf-8")
    output.symlink_to(target)

    with pytest.raises(RuntimeError, match="diagnostic_output_symlink_forbidden"):
        materializer.materialize_diagnostic(
            output_path=output,
            candidate_receipt_path=candidate,
            benchmark_receipt_path=benchmark,
            generated_at=GENERATED_AT,
        )

    assert target.read_text(encoding="utf-8") == "unchanged"


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_atomic_output_failure_preserves_existing_target_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    materializer, _verifier, candidate, benchmark, output, _receipt = _case(tmp_path)
    output.write_text("existing-target\n", encoding="utf-8")

    if failure == "write":
        def fail_write(*_args: object, **_kwargs: object) -> int:
            raise OSError("injected_write_failure")

        monkeypatch.setattr(materializer.os, "write", fail_write)
    else:
        def fail_replace(*_args: object, **_kwargs: object) -> None:
            raise OSError("injected_replace_failure")

        monkeypatch.setattr(materializer.os, "replace", fail_replace)

    with pytest.raises(OSError, match=f"injected_{failure}_failure"):
        materializer.materialize_diagnostic(
            output_path=output,
            candidate_receipt_path=candidate,
            benchmark_receipt_path=benchmark,
            generated_at=GENERATED_AT,
        )

    assert output.read_text(encoding="utf-8") == "existing-target\n"
    assert not list(tmp_path.glob(f".{output.name}.*.tmp"))


def test_atomic_output_fsyncs_file_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materializer, _verifier, candidate, benchmark, _output, _receipt = _case(tmp_path)
    output = tmp_path / "durable-diagnostic.json"
    original_fsync = materializer.os.fsync
    fsynced: list[int] = []

    def observe_fsync(descriptor: int) -> None:
        fsynced.append(descriptor)
        original_fsync(descriptor)

    monkeypatch.setattr(materializer.os, "fsync", observe_fsync)
    materializer.materialize_diagnostic(
        output_path=output,
        candidate_receipt_path=candidate,
        benchmark_receipt_path=benchmark,
        generated_at=GENERATED_AT,
    )

    assert output.is_file()
    assert len(fsynced) >= 2


def test_diagnostic_clis_require_and_reopen_explicit_sources(tmp_path: Path) -> None:
    materializer = _load_script("materialize_memorial_stt_captured_candidate_diagnostic")
    candidate = tmp_path / "candidate.json"
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "diagnostic.json"
    candidate_payload = _candidate_receipt(materializer)
    _write(candidate, candidate_payload)
    _write(
        benchmark,
        _benchmark_receipt(
            materializer,
            candidate_payload,
            candidate_receipt_sha256=_file_sha(candidate),
        ),
    )

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
            "--candidate-receipt",
            str(candidate),
            "--benchmark-receipt",
            str(benchmark),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout

    wrong_candidate = tmp_path / "wrong-candidate.json"
    _write(wrong_candidate, _candidate_receipt(materializer, status="blocked"))
    rejected = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_memorial_stt_captured_candidate_diagnostic.py"),
            "--receipt",
            str(output),
            "--candidate-receipt",
            str(wrong_candidate),
            "--benchmark-receipt",
            str(benchmark),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 1
