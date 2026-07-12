from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest


GENERATED_AT = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
ROOM_CHECK_IDS = [
    "actual_device_checked",
    "actual_speaker_checked",
    "first_syllable_not_clipped",
    "intelligibility_confirmed",
    "answer_text_fallback_visible",
    "no_internet_search_confirmed",
    "normal_spoken_turn_confirmed",
    "interruption_behavior_confirmed",
    "retry_path_confirmed",
]


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_test_fixture(name: str) -> ModuleType:
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"readiness_fixture_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manfred_contact_opening_captured_audio_has_explicit_known_fingerprint() -> None:
    route_source = (
        Path(__file__).resolve().parents[1] / "ea" / "app" / "api" / "routes" / "public_memorials.py"
    ).read_text(encoding="utf-8")

    assert "a5589abeb9b81ab6fb991d280e285d3416ec1c29a92013bc5e47fee3d2198d88" in route_source
    assert "Hallo Manfred, kannst du jetzt mit mir sprechen?" in route_source
    assert "local_non_silent_contact_opening_rescue" not in route_source


def _operator_status(*, ready: bool) -> dict[str, object]:
    return {
        "status": "pass" if ready else "blocked",
        "current_label": "Memorial public-origin gold: pass" if ready else "Memorial public-origin gold: blocked",
        "room_audio_receipt": "pass" if ready else "missing_or_blocked",
        "spoken_conversation_stt": {
            "status": "pass",
            "production_eligible": True,
            "production_provider": "full_runtime",
            "provider_label": "cartesia/ink-whisper+enhanced_wav",
            "passed_samples": 4,
            "sample_count": 4,
            "avg_token_f1": 1.0,
            "avg_wer": 0.0,
            "ground_truth_fixture_mode": "captured_external" if ready else "synthetic_only",
            "real_captured_fixture_status": "captured_candidate_benchmark_pass" if ready else "captured_candidate_diagnostic_blocked",
            "next_action": (
                ""
                if ready
                else "review_private_ground_truth_and_run_bound_stt_benchmark"
            ),
            "receipt_path": ".codex-studio/published/memorial_stt_provider_benchmark.generated.json",
            "scoring": {
                "raw_transcript_fields": False,
                "redacted_text_fields": True,
            },
        },
        "captured_candidate_diagnostic": {
            "status": "ready" if ready else "blocked",
            "diagnostic_status": "ready",
            "promotion_allowed": ready,
            "may_update_fixture_manifest": ready,
            "captured_row_count": 2,
            "issues": [],
            "row_failure_codes": [] if ready else ["transcript_hash_mismatch", "required_tokens_missing"],
            "next_action": (
                ""
                if ready
                else "review_private_ground_truth_and_run_bound_stt_benchmark"
            ),
            "input_binding": {
                "contract_name": "ea.memorial_stt_captured_candidate_diagnostic_input_binding.v1",
            },
            "input_binding_sha256": "a" * 64,
            "receipt_path": ".codex-studio/published/memorial_stt_captured_candidate_diagnostic.generated.json",
            "privacy": {
                "candidate_raw_text_fields": False,
                "raw_transcript_fields": False,
                "redacted_text_fields": True,
            },
        },
        "spoken_conversation_tts": {
            "status": "pass",
            "premium_status": "pass" if ready else "blocked",
            "direct_tts_audio_status": "pass",
            "conversation_turn_audio_status": "pass",
            "direct_tts_f1": 1.0,
            "conversation_turn_audio_f1": 1.0,
            "browser_audio_ready_for_ui": True,
            "browser_audio_transport": "ui_playback_probe",
            "browser_play_calls": 1,
            "browser_play_ended": 1,
            "room_audio_receipt": "pass" if ready else "blocked",
            "premium_failed_codes": [] if ready else ["room_audio_attestation_not_pass"],
            "next_action": "" if ready else "collect_real_room_audio_attestation",
            "receipt_path": ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
            "browser_receipt_path": ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
            "room_audio_receipt_path": ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
        },
        "room_audio_attestation_packet": {
            "status": "ready",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "required_check_ids": ROOM_CHECK_IDS,
            "operator_command": "make materialize-memorial-room-audio-gold-clean",
            "next_action": "collect_real_room_audio_attestation",
            "receipt_path": ".codex-studio/published/memorial_room_audio_attestation_packet.generated.json",
        },
    }
def _payload_sha256(payload: dict[str, object]) -> str:
    rendered = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _provider_result(
    *,
    expected_text_sha256: str,
    required_token_sha256: list[str],
    actual_text_sha256: str,
    passed: bool,
) -> dict[str, object]:
    return {
        "status": "transcribed" if passed else "unavailable",
        "passed": passed,
        "usable": passed,
        "intent_correct": passed,
        "fixture_invalid": False,
        "token_f1": 1.0 if passed else 0.0,
        "min_token_f1": 0.55,
        "wer": 0.0 if passed else 1.0,
        "max_wer": 0.55,
        "ms": 100.0,
        "transcriber": "cartesia/ink-whisper+enhanced_wav" if passed else "",
        "scored_text_source": "primary_transcript_text" if passed else "none",
        "expected_text_chars": 32,
        "actual_text_chars": 32 if passed else 0,
        "expected_text_sha256": expected_text_sha256,
        "actual_text_sha256": actual_text_sha256,
        "required_token_count": len(required_token_sha256),
        "required_token_sha256": required_token_sha256,
        "text_mode": "redacted",
        "text_redacted": True,
        "provider_evidence_status": "eligible" if passed else "blocked",
        "provider_evidence_failed_codes": [] if passed else ["provider_unavailable"],
    }


def _transformation(
    materializer: ModuleType,
    *,
    source_sha256: str,
    output_sha256: str,
    transformation_id: str,
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
        "source_audio_sha256": source_sha256,
        "output_audio_sha256": output_sha256,
        "source_duration_seconds": 3.0,
        "output_duration_seconds": 3.0,
        "duration_preserved": True,
        "parameters": parameters,
    }
    return {
        "contract_name": "ea.memorial_stt_audio_transformation_receipt.v1",
        "canonicalization": "json_utf8_sorted_keys_compact_v1",
        "sha256": materializer._canonical_sha256(payload),
        "payload": payload,
    }


def _strict_stt_evidence_payloads(*, generated_at: str) -> dict[str, dict[str, object]]:
    fixtures = _load_test_fixture("test_memorial_stt_captured_candidate_diagnostic")
    fixtures.GENERATED_AT = generated_at
    diagnostic_materializer = fixtures._load_script(  # type: ignore[attr-defined]
        "materialize_memorial_stt_captured_candidate_diagnostic"
    )
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        candidate_path = root / "candidate.json"
        captured_benchmark_path = root / "captured-benchmark.json"
        diagnostic_path = root / "diagnostic.json"
        candidate = fixtures._candidate_receipt(diagnostic_materializer)  # type: ignore[attr-defined]
        fixtures._write(candidate_path, candidate)  # type: ignore[attr-defined]
        captured_benchmark = fixtures._benchmark_receipt(  # type: ignore[attr-defined]
            diagnostic_materializer,
            candidate,
            candidate_receipt_sha256=fixtures._file_sha(candidate_path),  # type: ignore[attr-defined]
        )
        rows = list(captured_benchmark.get("rows") or [])
        for ranking in list(captured_benchmark.get("provider_ranking") or []):
            if not isinstance(ranking, dict):
                continue
            provider = str(ranking.get("provider") or "")
            provider_rows = [
                dict(row.get(provider) or {})
                for row in rows
                if isinstance(row, dict)
            ]
            token_f1_values = [float(row.get("token_f1") or 0.0) for row in provider_rows]
            wer_values = [float(row.get("wer") or 0.0) for row in provider_rows]
            latency_values = [
                float(row.get("ms") or 0.0)
                for row in provider_rows
                if float(row.get("ms") or 0.0) > 0.0
            ]
            ranking["avg_token_f1"] = round(
                sum(token_f1_values) / len(token_f1_values), 4
            )
            ranking["avg_wer"] = round(sum(wer_values) / len(wer_values), 4)
            ranking["avg_latency_ms"] = (
                round(sum(latency_values) / len(latency_values), 1)
                if latency_values
                else 0.0
            )
        fixtures._write(captured_benchmark_path, captured_benchmark)  # type: ignore[attr-defined]
        diagnostic = diagnostic_materializer.materialize_diagnostic(
            output_path=diagnostic_path,
            candidate_receipt_path=candidate_path,
            benchmark_receipt_path=captured_benchmark_path,
            generated_at=generated_at,
        )
    main_benchmark = json.loads(json.dumps(captured_benchmark, allow_nan=False))
    return {
        "memorial_stt_fixture_candidate.generated.json": candidate,
        "memorial_stt_provider_benchmark_captured_candidate.generated.json": captured_benchmark,
        "memorial_stt_provider_benchmark.generated.json": main_benchmark,
        "memorial_stt_captured_candidate_diagnostic.generated.json": diagnostic,
    }


def _ready_evidence_payloads(
    materializer: ModuleType,
    *,
    generated_at: str,
) -> dict[str, dict[str, object]]:
    source_state = {
        "generated_at": generated_at,
        "source_git_head": materializer.resolve_source_state_head(materializer.REPO_ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": materializer.resolve_source_worktree_fingerprint(materializer.REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }
    candidate_receipt_sha256 = "1" * 64
    candidate_binding_sha256 = "2" * 64
    review_binding_sha256 = "3" * 64
    source_audio_sha256 = "4" * 64
    hostile_audio_sha256 = "5" * 64
    expected_text_sha256 = "6" * 64
    required_token_sha256 = ["7" * 64]
    candidate_binding = {
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "candidate_binding_contract_name": "ea.memorial_stt_fixture_candidate_binding.v2",
        "candidate_binding_sha256": candidate_binding_sha256,
        "operator_ground_truth_review_binding_sha256": review_binding_sha256,
        "provider_upload_authorization": {
            "full_runtime": True,
            "onemin_sample": True,
            "shadow": True,
        },
        "source_audio_sha256": source_audio_sha256,
        "bundle_id": "bundle-123",
        "sample": "captured_candidate",
    }
    quality = {
        "status": "pass",
        "failed_codes": [],
        "audio_duration_seconds": 3.0,
        "expected_min_duration_seconds": 2.4,
    }
    provenance = {
        "origin": "Private captured regression candidate.",
        "speaker_consent": "operator_attested_for_private_stt_regression",
        "allowed_purpose": "memorial_stt_regression_and_provider_bakeoff",
        "retention": "private_repo_captured_regression_fixture",
        "synthetic": False,
        "accent": "Austrian German",
        "external_bundle": True,
        "bundle_root": "[memorial_stt_error_root]",
        "bundle_id": "bundle-123",
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "candidate_binding_contract_name": "ea.memorial_stt_fixture_candidate_binding.v2",
        "candidate_binding_sha256": candidate_binding_sha256,
        "operator_ground_truth_review_binding_sha256": review_binding_sha256,
        "provider_upload_authorization": candidate_binding["provider_upload_authorization"],
    }
    benchmark_rows: list[dict[str, object]] = []
    for sample, variant, output_sha256, transformation_id in (
        ("captured_candidate", "captured", source_audio_sha256, "identity_v1"),
        ("captured_candidate_hostile", "hostile", hostile_audio_sha256, "hostile_room_v1"),
    ):
        benchmark_rows.append(
            {
                "sample": sample,
                "variant": variant,
                "fixture": "[private_bundle]/bundle-123/input.wav",
                "fixture_sha256": output_sha256,
                "source_fixture_sha256": source_audio_sha256,
                "fixture_quality": dict(quality),
                "source_fixture_quality": dict(quality),
                "transformation": _transformation(
                    materializer,
                    source_sha256=source_audio_sha256,
                    output_sha256=output_sha256,
                    transformation_id=transformation_id,
                ),
                "provenance": dict(provenance),
                "full_runtime": _provider_result(
                    expected_text_sha256=expected_text_sha256,
                    required_token_sha256=required_token_sha256,
                    actual_text_sha256=expected_text_sha256,
                    passed=True,
                ),
                "onemin_sample": _provider_result(
                    expected_text_sha256=expected_text_sha256,
                    required_token_sha256=required_token_sha256,
                    actual_text_sha256="8" * 64,
                    passed=False,
                ),
                "shadow": _provider_result(
                    expected_text_sha256=expected_text_sha256,
                    required_token_sha256=required_token_sha256,
                    actual_text_sha256="9" * 64,
                    passed=False,
                ),
            }
        )
    benchmark = {
        "contract_name": "ea.memorial_stt_provider_benchmark",
        "generated_by": "scripts/benchmark_memorial_stt_providers.py",
        "captured_candidate_binding": candidate_binding,
        "status": "pass",
        "scoring": {
            "raw_provider_transcript_scored": True,
            "semantic_repair_applied": False,
            "text_mode": "redacted",
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
        "fixture_quality_status": "pass",
        "fixture_quality_failed_codes": [],
        "provider_ranking": [
            {
                "provider": "full_runtime",
                "production_eligible": True,
                "passed_samples": 2,
                "sample_count": 2,
                "scored_samples": 2,
                "intent_correct_samples": 2,
                "avg_token_f1": 1.0,
                "avg_wer": 0.0,
                "avg_latency_ms": 100.0,
            },
            {
                "provider": "onemin_sample",
                "production_eligible": False,
                "passed_samples": 0,
                "sample_count": 2,
                "scored_samples": 2,
                "intent_correct_samples": 0,
                "avg_token_f1": 0.0,
                "avg_wer": 1.0,
                "avg_latency_ms": 100.0,
            },
            {
                "provider": "shadow",
                "production_eligible": False,
                "passed_samples": 0,
                "sample_count": 2,
                "scored_samples": 2,
                "intent_correct_samples": 0,
                "avg_token_f1": 0.0,
                "avg_wer": 1.0,
                "avg_latency_ms": 100.0,
            },
        ],
        "rows": benchmark_rows,
        **source_state,
    }
    benchmark_receipt_sha256 = _payload_sha256(benchmark)
    diagnostic_rows: list[dict[str, object]] = []
    for benchmark_row in benchmark_rows:
        providers: dict[str, dict[str, object]] = {}
        for provider_name in ("full_runtime", "onemin_sample", "shadow"):
            benchmark_provider = dict(benchmark_row[provider_name])  # type: ignore[arg-type]
            providers[provider_name] = {
                "status": benchmark_provider["status"],
                "passed": benchmark_provider["passed"],
                "usable": benchmark_provider["usable"],
                "intent_correct": benchmark_provider["intent_correct"],
                "fixture_invalid": benchmark_provider["fixture_invalid"],
                "token_f1": benchmark_provider["token_f1"],
                "governed_min_token_f1": 0.55,
                "wer": benchmark_provider["wer"],
                "governed_max_wer": 0.55,
                "ms": benchmark_provider["ms"],
                "transcriber_sha256": (
                    hashlib.sha256(
                        str(benchmark_provider["transcriber"]).encode("utf-8")
                    ).hexdigest()
                    if provider_name == "full_runtime"
                    else ""
                ),
                "expected_text_chars": benchmark_provider["expected_text_chars"],
                "actual_text_chars": benchmark_provider["actual_text_chars"],
                "expected_text_sha256": benchmark_provider["expected_text_sha256"],
                "actual_text_sha256": benchmark_provider["actual_text_sha256"],
                "required_token_count": benchmark_provider["required_token_count"],
                "required_token_sha256": benchmark_provider["required_token_sha256"],
                "text_mode": "redacted",
                "text_redacted": True,
                "failure_codes": (
                    []
                    if benchmark_provider["passed"] is True
                    else [
                        "transcript_unusable",
                        "required_tokens_missing",
                        "provider_unavailable",
                    ]
                ),
            }
        transformation = dict(benchmark_row["transformation"])  # type: ignore[arg-type]
        transformation_payload = dict(transformation["payload"])  # type: ignore[arg-type]
        diagnostic_rows.append(
            {
                "sample_sha256": hashlib.sha256(
                    str(benchmark_row["sample"]).encode("utf-8")
                ).hexdigest(),
                "variant": benchmark_row["variant"],
                "source_fixture_sha256": source_audio_sha256,
                "actual_fixture_sha256": benchmark_row["fixture_sha256"],
                "fixture_quality": {
                    "status": "pass",
                    "failed_code_sha256": [],
                    "audio_duration_seconds": 3.0,
                    "expected_min_duration_seconds": 2.4,
                },
                "provenance": {
                    "external_bundle": True,
                    "synthetic": False,
                    "speaker_consent_authorized": True,
                    "allowed_purpose_authorized": True,
                    "retention_authorized": True,
                    "language_authorized": True,
                    "candidate_receipt_sha256": candidate_receipt_sha256,
                    "candidate_binding_sha256": candidate_binding_sha256,
                    "operator_ground_truth_review_binding_sha256": review_binding_sha256,
                    "provider_upload_authorization": candidate_binding[
                        "provider_upload_authorization"
                    ],
                },
                "transformation": {
                    "contract_name": transformation["contract_name"],
                    "transformation_id": transformation_payload["transformation_id"],
                    "transformation_version": transformation_payload["transformation_version"],
                    "source_audio_sha256": transformation_payload["source_audio_sha256"],
                    "output_audio_sha256": transformation_payload["output_audio_sha256"],
                    "source_duration_seconds": transformation_payload["source_duration_seconds"],
                    "output_duration_seconds": transformation_payload["output_duration_seconds"],
                    "duration_preserved": transformation_payload["duration_preserved"],
                    "sha256": transformation["sha256"],
                },
                "providers": providers,
                "row_failure_codes": [],
            }
        )
    input_payload = {
        "contract_name": "ea.memorial_stt_captured_candidate_diagnostic_input_binding.v1",
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "benchmark_receipt_sha256": benchmark_receipt_sha256,
        "candidate_binding_sha256": candidate_binding_sha256,
        "operator_ground_truth_review_binding_sha256": review_binding_sha256,
        "source_audio_sha256": source_audio_sha256,
        "source_git_head": source_state["source_git_head"],
        "source_state_fingerprint": source_state["source_state_fingerprint"],
    }
    input_binding_sha256 = materializer._canonical_sha256(input_payload)
    diagnostic = {
        "contract_name": "ea.memorial_stt_captured_candidate_diagnostic",
        "contract_version": 2,
        "generated_by": "scripts/materialize_memorial_stt_captured_candidate_diagnostic.py",
        "status": "pass",
        "diagnostic_status": "ready",
        "promotion_allowed": True,
        "may_update_fixture_manifest": True,
        "issues": [],
        "input_binding": {
            "contract_name": "ea.memorial_stt_captured_candidate_diagnostic_input_binding.v1",
            "canonicalization": "json_utf8_sorted_keys_compact_v1",
            "sha256": input_binding_sha256,
            "payload": input_payload,
        },
        "input_binding_sha256": input_binding_sha256,
        "candidate_receipt": {
            "path": ".codex-studio/published/memorial_stt_fixture_candidate.generated.json",
            "exists": True,
            "sha256": candidate_receipt_sha256,
        },
        "benchmark_receipt": {
            "path": ".codex-studio/published/memorial_stt_provider_benchmark.generated.json",
            "exists": True,
            "sha256": benchmark_receipt_sha256,
        },
        "candidate": {
            "status": "pass",
            "candidate_scope": "audio_quality_provenance_and_bound_ground_truth",
            "failed_code_sha256": [],
            "audio_sha256": source_audio_sha256,
            "sample_sha256": hashlib.sha256(b"captured_candidate").hexdigest(),
            "speaker_consent_authorized": True,
            "allowed_purpose_authorized": True,
            "retention_authorized": True,
            "language_authorized": True,
            "privacy_mode": "redacted",
            "raw_text_fields": False,
            "provider_upload_authorization": candidate_binding[
                "provider_upload_authorization"
            ],
            "candidate_binding": {
                "contract_name": "ea.memorial_stt_fixture_candidate_binding.v2",
                "sha256": candidate_binding_sha256,
            },
            "operator_ground_truth_review": {
                "contract_name": "ea.memorial_stt_operator_ground_truth_review_binding.v2",
                "status": "approved",
                "reviewer_authority": "memorial_operator",
                "sha256": review_binding_sha256,
            },
        },
        "benchmark_status": "pass",
        "benchmark_fixture_quality_status": "pass",
        "captured_row_count": 2,
        "captured_rows": diagnostic_rows,
        "blocker_summary": {
            "validation_issue_codes": [],
            "fixture_quality_failed_code_sha256": [],
            "full_runtime_failed_rows": [],
        },
        "privacy": {
            "text_mode": "redacted",
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
            "candidate_raw_text_fields": False,
            "public_receipt_must_not_include_full_text": True,
        },
        "next_action": "promote_captured_candidate_to_fixture_manifest",
        **source_state,
    }
    strict_stt_evidence = _strict_stt_evidence_payloads(generated_at=generated_at)
    return {
        **strict_stt_evidence,
        "memorial_voice_roundtrip_public_origin.generated.json": {
            "contract_name": "ea.memorial_voice_roundtrip_exit_gate",
            "status": "pass",
            "gold_claim_allowed": True,
            "failed_codes": [],
            "metrics": {
                "direct_tts_f1": 1.0,
                "conversation_turn_audio_f1": 1.0,
            },
            **source_state,
        },
        "memorial_realtime_browser_public_origin.generated.json": {
            "contract_name": "ea.memorial_realtime_browser_exit_gate",
            "status": "pass",
            "failed_codes": [],
            "audio_ready_for_ui": True,
            "ui_audio_play_calls": 1,
            "ui_audio_play_ended": 1,
            **source_state,
        },
        "memorial_room_audio_public_origin.generated.json": {
            "contract_name": "ea.memorial_room_audio_public_origin",
            "status": "pass",
            "gold_claim_allowed": True,
            "failed_codes": [],
            **source_state,
        },
        "memorial_room_audio_attestation_packet.generated.json": {
            "contract_name": "ea.memorial_room_audio_attestation_packet",
            "generated_by": "scripts/materialize_memorial_room_audio_attestation_packet.py",
            "status": "ready",
            "slug": "manfred",
            "proof_target": ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "operator_command": "make materialize-memorial-room-audio-gold-clean",
            "required_checks": [{"id": check_id} for check_id in ROOM_CHECK_IDS],
            **source_state,
        },
    }


def _write_evidence_payloads(root: Path, payloads: dict[str, dict[str, object]]) -> None:
    for name, payload in payloads.items():
        (root / name).write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    ("ready", "expected_status"),
    [
        (False, "blocked_realtime_prerequisites"),
        (True, "ready_for_realtime_conversation_review"),
    ],
)
def test_manfred_realtime_custom_evidence_root_is_bound_read_only_and_redacted(
    tmp_path: Path,
    *,
    ready: bool,
    expected_status: str,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    output_root = tmp_path / "custom-output"
    output_root.mkdir()
    payloads = _ready_evidence_payloads(
        materializer,
        generated_at=materializer._now(),
    )
    if not ready:
        room_receipt = payloads[
            "memorial_room_audio_public_origin.generated.json"
        ]
        room_receipt["status"] = "fail"
        room_receipt["gold_claim_allowed"] = False
        room_receipt["failed_codes"] = ["manual_attestation_missing"]
    _write_evidence_payloads(evidence_root, payloads)
    before = {
        child.name: (
            child.stat(follow_symlinks=False).st_mtime_ns,
            child.read_bytes(),
        )
        for child in evidence_root.iterdir()
    }
    receipt_path = output_root / "manfred-realtime.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=materializer._now(),
        refresh=True,
        evidence_root=evidence_root,
    )

    assert receipt["status"] == expected_status
    rendered_receipt = json.dumps(receipt, sort_keys=True)
    assert str(evidence_root) not in rendered_receipt
    assert str(output_root) not in rendered_receipt
    assert verifier.verify_manfred_realtime_conversation_readiness(
        receipt_path,
        evidence_root=evidence_root,
    ) == {
        "contract_name": "ea.manfred_realtime_conversation_readiness.verify.v1",
        "status": "pass",
        "issues": [],
    }

    sibling_default = verifier.verify_manfred_realtime_conversation_readiness(
        receipt_path
    )
    assert sibling_default["status"] == "fail"
    wrong_root = tmp_path / "wrong-evidence"
    wrong_root.mkdir()
    wrong_root_verification = verifier.verify_manfred_realtime_conversation_readiness(
        receipt_path,
        evidence_root=wrong_root,
    )
    assert wrong_root_verification["status"] == "fail"
    assert {
        child.name: (
            child.stat(follow_symlinks=False).st_mtime_ns,
            child.read_bytes(),
        )
        for child in evidence_root.iterdir()
    } == before


def test_manfred_realtime_verifier_rejects_unsafe_explicit_evidence_root(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "blocked.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=materializer._now(),
        operator_status=_operator_status(ready=False),
    )
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    linked_root = tmp_path / "linked-evidence"
    linked_root.symlink_to(evidence_root.name, target_is_directory=True)

    verification = verifier.verify_manfred_realtime_conversation_readiness(
        receipt_path,
        evidence_root=linked_root,
    )

    assert verification == {
        "contract_name": "ea.manfred_realtime_conversation_readiness.verify.v1",
        "status": "fail",
        "issues": ["manfred_realtime_evidence_root_unsafe"],
    }
    assert list(evidence_root.iterdir()) == []


def test_manfred_realtime_missing_first_run_evidence_root_materializes_blocked(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    evidence_root = tmp_path / "new-published-root"
    receipt_path = evidence_root / "readiness.json"
    assert not evidence_root.exists()

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=materializer._now(),
        evidence_root=evidence_root,
    )

    assert receipt["status"] == "blocked_realtime_prerequisites"
    assert receipt["evidence_source"] == "receipt_aggregation"
    assert all(
        row["present"] is False and row["status"] == "missing"
        for row in receipt["input_evidence"].values()
    )
    assert receipt_path.is_file()
    assert verifier.verify_manfred_realtime_conversation_readiness(
        receipt_path
    ) == {
        "contract_name": "ea.manfred_realtime_conversation_readiness.verify.v1",
        "status": "pass",
        "issues": [],
    }


def test_manfred_realtime_materializer_rejects_blank_evidence_root(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "blank-root.json"

    with pytest.raises(
        materializer.UnsafeLocalFileError,
        match="local_evidence_root_empty",
    ):
        materializer.materialize_manfred_realtime_conversation_readiness(
            receipt_path=receipt_path,
            generated_at=materializer._now(),
            evidence_root="",
        )

    assert not receipt_path.exists()
    script_path = (
        Path(__file__).resolve().parents[1]
        / "ea"
        / "scripts"
        / "materialize_manfred_realtime_conversation_readiness.py"
    )
    cli_receipt = tmp_path / "blank-root-cli.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--receipt",
            str(cli_receipt),
            "--evidence-root",
            "",
            "--generated-at",
            materializer._now(),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "local_evidence_root_empty" in completed.stderr
    assert not cli_receipt.exists()


def test_manfred_realtime_relative_evidence_root_does_not_drift_with_cwd(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    base = tmp_path / "base"
    base.mkdir()
    evidence_root = base / "evidence"
    evidence_root.mkdir()
    attacker_cwd = tmp_path / "attacker"
    attacker_cwd.mkdir()
    attacker_evidence = attacker_cwd / "evidence"
    attacker_evidence.mkdir()
    _write_evidence_payloads(
        evidence_root,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    attacker_payloads = _ready_evidence_payloads(
        materializer,
        generated_at=materializer._now(),
    )
    attacker_room = attacker_payloads[
        "memorial_room_audio_public_origin.generated.json"
    ]
    attacker_room["status"] = "fail"
    attacker_room["gold_claim_allowed"] = False
    attacker_room["failed_codes"] = ["attacker_replacement"]
    _write_evidence_payloads(attacker_evidence, attacker_payloads)
    original_load = materializer._load_evidence_receipt
    load_count = 0

    def change_cwd_after_first_read(**kwargs):
        nonlocal load_count
        result = original_load(**kwargs)
        load_count += 1
        if load_count == 1:
            os.chdir(attacker_cwd)
        return result

    monkeypatch.setattr(
        materializer,
        "_load_evidence_receipt",
        change_cwd_after_first_read,
    )
    original_cwd = Path.cwd()
    try:
        os.chdir(base)
        status = materializer._operator_status_from_receipts("evidence")
    finally:
        os.chdir(original_cwd)

    assert status["status"] == "pass"
    assert status["spoken_conversation_tts"]["room_audio_receipt"] == "pass"


def test_manfred_realtime_verifier_binds_relative_paths_before_cwd_drift(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    base = tmp_path / "base"
    base.mkdir()
    evidence_root = base / "evidence"
    evidence_root.mkdir()
    output_root = base / "output"
    output_root.mkdir()
    _write_evidence_payloads(
        evidence_root,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    receipt_path = output_root / "readiness.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=materializer._now(),
        evidence_root=evidence_root,
    )
    attacker_cwd = tmp_path / "attacker"
    attacker_cwd.mkdir()
    attacker_evidence = attacker_cwd / "evidence"
    attacker_evidence.mkdir()
    attacker_output = attacker_cwd / "output"
    attacker_output.mkdir()
    attacker_payloads = _ready_evidence_payloads(
        materializer,
        generated_at=materializer._now(),
    )
    attacker_room = attacker_payloads[
        "memorial_room_audio_public_origin.generated.json"
    ]
    attacker_room["status"] = "fail"
    attacker_room["gold_claim_allowed"] = False
    attacker_room["failed_codes"] = ["attacker_replacement"]
    _write_evidence_payloads(attacker_evidence, attacker_payloads)
    (attacker_output / receipt_path.name).write_text(
        "{}\n",
        encoding="utf-8",
    )
    original_read = verifier._read_regular_file_snapshot_at
    read_count = 0

    def change_cwd_after_receipt_read(*args, **kwargs):
        nonlocal read_count
        raw = original_read(*args, **kwargs)
        read_count += 1
        if read_count == 1:
            os.chdir(attacker_cwd)
        return raw

    monkeypatch.setattr(
        verifier,
        "_read_regular_file_snapshot_at",
        change_cwd_after_receipt_read,
    )
    original_cwd = Path.cwd()
    try:
        os.chdir(base)
        verification = verifier.verify_manfred_realtime_conversation_readiness(
            Path("output") / receipt_path.name,
            evidence_root="evidence",
        )
    finally:
        os.chdir(original_cwd)

    assert verification == {
        "contract_name": "ea.manfred_realtime_conversation_readiness.verify.v1",
        "status": "pass",
        "issues": [],
    }


def test_manfred_realtime_aggregation_rejects_root_replacement_mix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    moved_root = tmp_path / "evidence-opened"
    replacement_root = tmp_path / "replacement"
    replacement_root.mkdir()
    _write_evidence_payloads(
        evidence_root,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    replacement_payloads = _ready_evidence_payloads(
        materializer,
        generated_at=materializer._now(),
    )
    replacement_room = replacement_payloads[
        "memorial_room_audio_public_origin.generated.json"
    ]
    replacement_room["status"] = "fail"
    replacement_room["gold_claim_allowed"] = False
    replacement_room["failed_codes"] = ["replacement_root"]
    _write_evidence_payloads(replacement_root, replacement_payloads)
    original_load = materializer._load_evidence_receipt
    load_count = 0

    def replace_root_after_first_read(**kwargs):
        nonlocal load_count
        result = original_load(**kwargs)
        load_count += 1
        if load_count == 1:
            evidence_root.rename(moved_root)
            replacement_root.rename(evidence_root)
            os.utime(moved_root, None)
        return result

    monkeypatch.setattr(
        materializer,
        "_load_evidence_receipt",
        replace_root_after_first_read,
    )

    with pytest.raises(
        materializer.UnsafeLocalFileError,
        match="local_evidence_root_changed_during_aggregation",
    ):
        materializer._operator_status_from_receipts(evidence_root)


def test_manfred_realtime_verifier_rejects_root_replacement_mix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    moved_root = tmp_path / "evidence-opened"
    replacement_root = tmp_path / "replacement"
    replacement_root.mkdir()
    _write_evidence_payloads(
        evidence_root,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    receipt_path = tmp_path / "readiness.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=materializer._now(),
        evidence_root=evidence_root,
    )
    replacement_payloads = _ready_evidence_payloads(
        materializer,
        generated_at=materializer._now(),
    )
    replacement_room = replacement_payloads[
        "memorial_room_audio_public_origin.generated.json"
    ]
    replacement_room["status"] = "fail"
    replacement_room["gold_claim_allowed"] = False
    replacement_room["failed_codes"] = ["replacement_root"]
    _write_evidence_payloads(replacement_root, replacement_payloads)
    original_load = verifier._load_evidence_receipt
    load_count = 0

    def replace_root_after_first_read(**kwargs):
        nonlocal load_count
        result = original_load(**kwargs)
        load_count += 1
        if load_count == 1:
            evidence_root.rename(moved_root)
            replacement_root.rename(evidence_root)
            os.utime(moved_root, None)
        return result

    monkeypatch.setattr(
        verifier,
        "_load_evidence_receipt",
        replace_root_after_first_read,
    )

    verification = verifier.verify_manfred_realtime_conversation_readiness(
        receipt_path,
        evidence_root=evidence_root,
    )

    assert verification == {
        "contract_name": "ea.manfred_realtime_conversation_readiness.verify.v1",
        "status": "fail",
        "issues": [
            "manfred_realtime_evidence_root_changed_during_verification"
        ],
    }


def test_manfred_realtime_refresh_aggregates_current_redacted_receipts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    secret = "private-transcript-must-not-cross-readiness-boundary"
    source_state = {
        "generated_at": materializer._now(),
        "source_git_head": materializer.resolve_source_state_head(materializer.REPO_ROOT),
        "source_state_fingerprint": materializer.resolve_source_worktree_fingerprint(materializer.REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }
    receipts = {
        "memorial_stt_provider_benchmark.generated.json": {
            "contract_name": "ea.memorial_stt_provider_benchmark",
            "status": "blocked",
            "fixture_quality_status": "pass",
            "provider_ranking": [
                {
                    "provider": "full_runtime",
                    "production_eligible": False,
                    "passed_samples": 3,
                    "sample_count": 4,
                    "avg_token_f1": 0.97,
                    "avg_wer": 0.03,
                }
            ],
            "rows": [
                {
                    "sample": "captured_candidate",
                    "variant": "captured",
                    "full_runtime": {"passed": False, "actual_text": secret},
                }
            ],
            "private_debug": secret,
            **source_state,
        },
        "memorial_stt_captured_candidate_diagnostic.generated.json": {
            "contract_name": "ea.memorial_stt_captured_candidate_diagnostic",
            "status": "blocked",
            "diagnostic_status": "ready",
            "promotion_allowed": False,
            "may_update_fixture_manifest": False,
            "captured_row_count": 1,
            "blocker_summary": {"row_failure_codes": ["transcript_hash_mismatch"]},
            "private_debug": secret,
            **source_state,
        },
        "memorial_voice_roundtrip_public_origin.generated.json": {
            "contract_name": "ea.memorial_voice_roundtrip_exit_gate",
            "status": "pass",
            "gold_claim_allowed": True,
            "failed_codes": [],
            "metrics": {
                "direct_tts_f1": 1.0,
                "conversation_turn_audio_f1": 1.0,
            },
            "private_debug": secret,
            **source_state,
        },
        "memorial_realtime_browser_public_origin.generated.json": {
            "contract_name": "ea.memorial_realtime_browser_exit_gate",
            "status": "pass",
            "failed_codes": [],
            "audio_ready_for_ui": True,
            "ui_audio_play_calls": 1,
            "ui_audio_play_ended": 1,
            "private_debug": secret,
            **source_state,
        },
        "memorial_room_audio_public_origin.generated.json": {
            "contract_name": "ea.memorial_room_audio_public_origin",
            "status": "fail",
            "gold_claim_allowed": False,
            "failed_codes": ["manual_attestation_id_missing"],
            "private_notes": secret,
            **source_state,
        },
        "memorial_room_audio_attestation_packet.generated.json": {
            "contract_name": "ea.memorial_room_audio_attestation_packet",
            "status": "ready",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "operator_command": "make materialize-memorial-room-audio-gold-clean",
            "required_checks": [{"id": check_id} for check_id in ROOM_CHECK_IDS],
            "private_notes": secret,
            **source_state,
        },
    }
    strict_sources = _strict_stt_evidence_payloads(generated_at=source_state["generated_at"])
    for name in (
        "memorial_stt_fixture_candidate.generated.json",
        "memorial_stt_provider_benchmark_captured_candidate.generated.json",
    ):
        receipts[name] = strict_sources[name]
    for name, payload in receipts.items():
        (tmp_path / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(
        materializer,
        "_operator_status_from_receipts",
        lambda _evidence_root: status,
    )
    receipt_path = tmp_path / "manfred-realtime-refreshed.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["evidence_source"] == "receipt_aggregation"
    assert receipt["status"] == "blocked_realtime_prerequisites"
    assert receipt["ready_for_realtime_conversation_review"] is False
    assert receipt["stt"]["status"] == "blocked"
    assert receipt["captured_candidate_diagnostic"]["status"] == "blocked"
    assert receipt["tts"]["status"] == "pass"
    assert receipt["tts"]["premium_status"] == "blocked"
    assert receipt["tts"]["room_audio_receipt"] == "blocked"
    assert (
        receipt["next_action"]
        == "review_private_ground_truth_and_run_bound_stt_benchmark"
    )
    assert receipt["next_action_href"] == "/admin/memorials/manfred/gold"
    assert receipt["next_action_label"] == "Open voice gold"
    assert receipt["tts"]["next_action"] == receipt["next_action"]
    assert receipt["room_audio_attestation"]["next_action"] == ""
    assert receipt["operator_action"]["kind"] == "automated_readiness_remediation"
    assert receipt["operator_action"]["telegram_push_allowed"] is False
    assert receipt["operator_action"]["manual_only"] is False
    assert receipt["operator_action"]["required_check_ids"] == []
    assert set(receipt["input_evidence"]) == set(materializer.EVIDENCE_RECEIPTS)
    for evidence in receipt["input_evidence"].values():
        if evidence["present"]:
            assert len(evidence["receipt_sha256"]) == 64
        else:
            assert evidence["receipt_sha256"] == ""
        assert evidence["source_state_matches_current"] is True
        assert evidence["fresh"] is True
        assert evidence["raw_private_context_exposed"] is False
        assert evidence["raw_transcript_fields_exposed"] is False
        assert evidence["raw_credentials_exposed"] is False
        assert evidence["raw_receipt_payload_exposed"] is False
    assert secret not in json.dumps(receipt, sort_keys=True)

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "pass", verification
    assert verification["issues"] == []


def test_manfred_realtime_refresh_allows_only_fresh_current_ready_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    _write_evidence_payloads(
        tmp_path,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(
        materializer,
        "_operator_status_from_receipts",
        lambda _evidence_root: status,
    )
    receipt_path = tmp_path / "manfred-realtime-ready-aggregated.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["status"] == "ready_for_realtime_conversation_review"
    assert receipt["ready_for_realtime_conversation_review"] is True
    assert receipt["blocked_checks"] == []
    assert all(row["fresh"] is True for row in receipt["input_evidence"].values())
    assert all(
        row["source_state_matches_current"] is True
        for row in receipt["input_evidence"].values()
    )
    assert verifier.verify_manfred_realtime_conversation_readiness(receipt_path)["status"] == "pass"


def test_manfred_realtime_verifier_reaggregates_source_receipt_content(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    _write_evidence_payloads(tmp_path, payloads)
    aggregate = materializer._operator_status_from_receipts
    status = aggregate(tmp_path)
    monkeypatch.setattr(
        materializer,
        "_operator_status_from_receipts",
        lambda _evidence_root: status,
    )
    receipt_path = tmp_path / "manfred-realtime-source-bound.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )
    payloads["memorial_room_audio_public_origin.generated.json"]["failed_codes"] = [
        "manual_attestation_invalid"
    ]
    _write_evidence_payloads(tmp_path, payloads)
    refreshed_evidence = aggregate(tmp_path)["input_evidence"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["input_evidence"] = refreshed_evidence
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_tts_derivation_mismatch" in verification["issues"]


def test_manfred_realtime_verifier_rejects_ready_claim_outside_aggregation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    _write_evidence_payloads(
        tmp_path,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(
        materializer,
        "_operator_status_from_receipts",
        lambda _evidence_root: status,
    )
    receipt_path = tmp_path / "manfred-realtime-source-bypass.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["evidence_source"] = "conservative_default"
    receipt["input_evidence"] = {}
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_blocked_checks_inconsistent" in verification["issues"]
    assert "manfred_realtime_status_inconsistent" in verification["issues"]


def test_manfred_realtime_refresh_rejects_expired_ready_evidence(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    _write_evidence_payloads(
        tmp_path,
        _ready_evidence_payloads(materializer, generated_at="2020-01-01T00:00:00Z"),
    )

    status = materializer._operator_status_from_receipts(tmp_path)

    assert status["status"] == "blocked"
    assert status["spoken_conversation_stt"]["production_eligible"] is False
    assert status["spoken_conversation_tts"]["status"] == "blocked"
    assert status["room_audio_attestation_packet"]["status"] == "blocked"
    assert all(row["fresh"] is False for row in status["input_evidence"].values())


def test_manfred_realtime_refresh_rejects_contradictory_or_wrong_contract_evidence(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    payloads["memorial_room_audio_public_origin.generated.json"]["failed_codes"] = [
        "manual_attestation_invalid"
    ]
    _write_evidence_payloads(tmp_path, payloads)

    contradictory = materializer._operator_status_from_receipts(tmp_path)

    assert contradictory["status"] == "blocked"
    assert contradictory["spoken_conversation_tts"]["room_audio_receipt"] == "blocked"

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    payloads["memorial_room_audio_public_origin.generated.json"]["failed_codes"] = (
        "manual_attestation_invalid"
    )
    _write_evidence_payloads(tmp_path, payloads)

    malformed_failure_codes = materializer._operator_status_from_receipts(tmp_path)

    assert malformed_failure_codes["status"] == "blocked"
    assert (
        malformed_failure_codes["spoken_conversation_tts"]["room_audio_receipt"]
        == "blocked"
    )

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    payloads["memorial_stt_provider_benchmark.generated.json"]["contract_name"] = "wrong.contract"
    _write_evidence_payloads(tmp_path, payloads)

    wrong_contract = materializer._operator_status_from_receipts(tmp_path)

    assert wrong_contract["status"] == "blocked"
    assert wrong_contract["spoken_conversation_stt"]["production_eligible"] is False
    assert wrong_contract["input_evidence"]["stt_benchmark"]["contract_valid"] is False


def test_manfred_realtime_provided_status_is_strictly_sanitized(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    secret = "raw-private-transcript-and-api-key"
    operator_status = _operator_status(ready=False)
    operator_status["spoken_conversation_stt"]["raw_transcript"] = secret  # type: ignore[index]
    operator_status["captured_candidate_diagnostic"]["api_key"] = secret  # type: ignore[index]
    operator_status["spoken_conversation_tts"]["private_audio_path"] = secret  # type: ignore[index]
    operator_status["room_audio_attestation_packet"]["private_notes"] = secret  # type: ignore[index]
    operator_status["input_evidence"] = {"raw": secret}
    receipt_path = tmp_path / "provided-status-sanitized.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=operator_status,
    )

    assert receipt["evidence_source"] == "provided_operator_status"
    assert receipt["input_evidence"] == {}
    assert "current_evidence_aggregation_required" in receipt["blocked_checks"]
    assert receipt["realtime_conversation_claim_allowed"] is False
    assert secret not in json.dumps(receipt, sort_keys=True)
    assert verifier.verify_manfred_realtime_conversation_readiness(receipt_path)["status"] == "pass"


def test_manfred_realtime_verifier_rejects_unsafe_aggregated_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "unsafe-evidence.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["evidence_source"] = "receipt_aggregation"
    receipt["raw_private_transcript"] = "must-not-pass"
    receipt["operator_action"]["raw_private_payload"] = "must-not-pass"
    receipt["input_evidence"] = {
        key: {
            "receipt_name": receipt_name,
            "present": True,
            "contract_name": contract_name,
            "contract_valid": True,
            "status": "pass",
            "generated_at": GENERATED_AT,
            "receipt_sha256": "a" * 64,
            "source_git_head_present": True,
            "source_git_head_matches_current": True,
            "source_state_fingerprint_present": True,
            "source_state_matches_current": True,
            "raw_private_context_exposed": key == "stt_benchmark",
            "raw_transcript_fields_exposed": False,
            "raw_credentials_exposed": False,
            "raw_receipt_payload_exposed": False,
        }
        for key, (receipt_name, contract_name) in materializer.EVIDENCE_RECEIPTS.items()
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_top_level_fields_unexpected" in verification["issues"]
    assert "manfred_realtime_operator_action_fields_unexpected" in verification["issues"]
    assert (
        "manfred_realtime_input_evidence_raw_flag_not_false:stt_benchmark:raw_private_context_exposed"
        in verification["issues"]
    )
    assert "manfred_realtime_input_evidence_not_current:stt_benchmark" in verification["issues"]


def test_manfred_realtime_readiness_routes_mixed_stt_and_room_blockers_to_stt_first(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "manfred-realtime.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )

    assert receipt["status"] == "blocked_realtime_prerequisites"
    assert receipt["generated_by"] == "ea/scripts/materialize_manfred_realtime_conversation_readiness.py"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["source_state_fingerprint"]
    assert (
        receipt["source_state_fingerprint_semantics"]
        == "worktree_source_files_sha256_excluding_generated_only_paths"
    )
    assert receipt["ready_for_realtime_conversation_review"] is False
    assert receipt["realtime_conversation_claim_allowed"] is False
    assert receipt["premium_spoken_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["evidence_source"] == "provided_operator_status"
    assert "real_captured_stt_fixture_ready" in receipt["blocked_checks"]
    assert "captured_candidate_diagnostic_clean" in receipt["blocked_checks"]
    assert "room_audio_receipt_passed" in receipt["blocked_checks"]
    assert "manual_room_checks_confirmed" in receipt["blocked_checks"]
    assert receipt["room_audio_attestation"]["manual_only"] is True
    assert receipt["room_audio_attestation"]["ci_must_not_auto_assert"] is True
    assert "interruption_behavior_confirmed" in receipt["room_audio_attestation"]["required_check_ids"]
    assert receipt["privacy"]["raw_private_context_exposed"] is False
    assert (
        receipt["next_action"]
        == "review_private_ground_truth_and_run_bound_stt_benchmark"
    )
    assert receipt["next_action_href"] == "/admin/memorials/manfred/gold"
    assert receipt["next_action_label"] == "Open voice gold"
    assert receipt["tts"]["next_action"] == receipt["next_action"]
    assert receipt["room_audio_attestation"]["next_action"] == ""
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_action_key"] == "manfred_stt_tts_realtime_conversation"
    operator_action = receipt["operator_action"]
    assert operator_action["status"] == "action_required"
    assert operator_action["operator_action_key"] == "manfred_stt_tts_realtime_conversation"
    assert operator_action["user_action_required"] is True
    assert operator_action["kind"] == "automated_readiness_remediation"
    assert operator_action["delivery_policy"] == "queue_only"
    assert operator_action["telegram_push_allowed"] is False
    assert operator_action["manual_only"] is False
    assert operator_action["ci_must_not_auto_assert"] is False
    assert operator_action["required_check_count"] == 0
    assert operator_action["required_check_ids"] == []
    assert operator_action["raw_private_context_exposed"] is False
    assert operator_action["raw_transcript_fields_exposed"] is False

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "pass", verification
    assert verification["issues"] == []


def test_manfred_realtime_readiness_surfaces_manual_room_action_only_as_sole_blocker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    room_receipt = payloads["memorial_room_audio_public_origin.generated.json"]
    room_receipt["status"] = "fail"
    room_receipt["gold_claim_allowed"] = False
    room_receipt["failed_codes"] = ["manual_attestation_missing"]
    _write_evidence_payloads(tmp_path, payloads)
    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(
        materializer,
        "_operator_status_from_receipts",
        lambda _evidence_root: status,
    )
    receipt_path = tmp_path / "sole-room-blocker.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["blocked_checks"] == [
        "room_audio_receipt_passed",
        "manual_room_checks_confirmed",
    ]
    assert receipt["stt"]["status"] == "pass"
    assert receipt["stt"]["production_eligible"] is True
    assert receipt["captured_candidate_diagnostic"]["status"] == "ready"
    assert receipt["captured_candidate_diagnostic"]["promotion_allowed"] is True
    assert receipt["captured_candidate_diagnostic"]["may_update_fixture_manifest"] is True
    assert receipt["tts"]["status"] == "pass"
    assert receipt["tts"]["browser_audio_ready_for_ui"] is True
    assert receipt["next_action"] == "collect_real_room_audio_attestation"
    assert receipt["next_action_href"] == "/memorials/manfred/voice-config"
    assert receipt["next_action_label"] == "Spoken conversation proof"
    assert receipt["tts"]["next_action"] == "collect_real_room_audio_attestation"
    assert receipt["room_audio_attestation"]["next_action"] == "collect_real_room_audio_attestation"
    operator_action = receipt["operator_action"]
    assert operator_action["kind"] == "manual_room_audio_attestation"
    assert operator_action["delivery_policy"] == "action_required_only"
    assert operator_action["telegram_push_allowed"] is True
    assert operator_action["manual_only"] is True
    assert operator_action["ci_must_not_auto_assert"] is True
    assert operator_action["required_check_ids"] == ROOM_CHECK_IDS
    assert operator_action["required_check_count"] == len(ROOM_CHECK_IDS)
    assert receipt["realtime_conversation_claim_allowed"] is False
    assert receipt["premium_spoken_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "pass", verification
    assert verification["issues"] == []


def test_manfred_realtime_invalid_attestation_packet_never_enables_telegram(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    aggregate = materializer._operator_status_from_receipts
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    packet = payloads["memorial_room_audio_attestation_packet.generated.json"]
    packet["required_checks"] = list(packet["required_checks"]) + [  # type: ignore[arg-type]
        {"id": ROOM_CHECK_IDS[0]},
    ]
    _write_evidence_payloads(tmp_path, payloads)
    status = aggregate(tmp_path)
    monkeypatch.setattr(
        materializer,
        "_operator_status_from_receipts",
        lambda _evidence_root: status,
    )
    receipt_path = tmp_path / "invalid-attestation-packet.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["blocked_checks"] == ["manual_room_checks_confirmed"]
    assert receipt["next_action"] == "regenerate_current_safe_room_attestation_packet"
    assert receipt["next_action_href"] == "/admin/memorials/manfred/gold"
    operator_action = receipt["operator_action"]
    assert operator_action["kind"] == "automated_readiness_remediation"
    assert operator_action["action_required_reason"] == (
        "room_attestation_packet_not_current_or_safe"
    )
    assert operator_action["delivery_policy"] == "queue_only"
    assert operator_action["telegram_push_allowed"] is False
    assert operator_action["manual_only"] is False
    assert operator_action["ci_must_not_auto_assert"] is False
    assert operator_action["required_check_ids"] == []
    assert verifier.verify_manfred_realtime_conversation_readiness(receipt_path)["status"] == (
        "pass"
    )

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    packet = payloads["memorial_room_audio_attestation_packet.generated.json"]
    packet.pop("generated_by")
    packet["raw_response"] = "private room notes"
    room = payloads["memorial_room_audio_public_origin.generated.json"]
    room["status"] = "fail"
    room["gold_claim_allowed"] = False
    room["failed_codes"] = ["manual_attestation_missing"]
    _write_evidence_payloads(tmp_path, payloads)
    status = aggregate(tmp_path)
    receipt_path = tmp_path / "unsafe-attestation-envelope.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["room_audio_attestation"]["status"] == "blocked"
    assert receipt["operator_action"]["telegram_push_allowed"] is False
    assert receipt["operator_action"]["delivery_policy"] == "queue_only"


def test_manfred_realtime_contradictory_and_minimal_stt_evidence_fail_closed(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    diagnostic = payloads["memorial_stt_captured_candidate_diagnostic.generated.json"]
    diagnostic["diagnostic_status"] = "blocked"
    _write_evidence_payloads(tmp_path, payloads)

    contradictory = materializer._operator_status_from_receipts(tmp_path)

    assert contradictory["status"] == "blocked"
    assert contradictory["captured_candidate_diagnostic"]["status"] == "blocked"
    assert contradictory["captured_candidate_diagnostic"]["promotion_allowed"] is False

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    diagnostic = payloads["memorial_stt_captured_candidate_diagnostic.generated.json"]
    candidate = diagnostic["candidate"]
    assert isinstance(candidate, dict)
    candidate["candidate_scope"] = "audio_quality_and_provenance_only"
    _write_evidence_payloads(tmp_path, payloads)

    legacy_scope = materializer._operator_status_from_receipts(tmp_path)

    assert legacy_scope["status"] == "blocked"
    assert legacy_scope["captured_candidate_diagnostic"]["promotion_allowed"] is False

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    benchmark = payloads["memorial_stt_provider_benchmark.generated.json"]
    benchmark.pop("generated_by")
    benchmark["captured_candidate_binding"] = {}
    benchmark["rows"] = [
        {
            "sample": "captured_candidate",
            "variant": "captured",
            "full_runtime": {"passed": True},
        }
    ]
    _write_evidence_payloads(tmp_path, payloads)

    minimal = materializer._operator_status_from_receipts(tmp_path)

    assert minimal["status"] == "blocked"
    assert minimal["spoken_conversation_stt"]["production_eligible"] is False
    assert minimal["captured_candidate_diagnostic"]["promotion_allowed"] is True


def test_manfred_realtime_reopens_bound_candidate_and_captured_benchmark_sources(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    candidate = payloads["memorial_stt_fixture_candidate.generated.json"]
    candidate["status"] = "blocked"
    candidate["failed_codes"] = ["revoked_after_diagnostic"]
    _write_evidence_payloads(tmp_path, payloads)

    revoked_source = materializer._operator_status_from_receipts(tmp_path)

    assert revoked_source["spoken_conversation_stt"]["production_eligible"] is False
    assert revoked_source["captured_candidate_diagnostic"]["promotion_allowed"] is False

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    diagnostic = payloads["memorial_stt_captured_candidate_diagnostic.generated.json"]
    candidate_entry = diagnostic["candidate_receipt"]
    assert isinstance(candidate_entry, dict)
    candidate_entry["sha256"] = "0" * 64
    _write_evidence_payloads(tmp_path, payloads)

    forged_source_entry = materializer._operator_status_from_receipts(tmp_path)

    assert forged_source_entry["spoken_conversation_stt"]["production_eligible"] is False
    assert forged_source_entry["captured_candidate_diagnostic"]["promotion_allowed"] is False


def test_manfred_realtime_main_benchmark_must_exactly_cross_bind_captured_source(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    main = payloads["memorial_stt_provider_benchmark.generated.json"]
    binding = main["captured_candidate_binding"]
    assert isinstance(binding, dict)
    binding["candidate_receipt_sha256"] = "0" * 64
    _write_evidence_payloads(tmp_path, payloads)

    status = materializer._operator_status_from_receipts(tmp_path)

    assert status["spoken_conversation_stt"]["production_eligible"] is False
    assert status["captured_candidate_diagnostic"]["promotion_allowed"] is True

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    main = payloads["memorial_stt_provider_benchmark.generated.json"]
    rows = main["rows"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    full_runtime = rows[0]["full_runtime"]
    assert isinstance(full_runtime, dict)
    full_runtime["min_token_f1"] = 0.65
    full_runtime["max_wer"] = 0.45
    authoritative, _binding, _rows = materializer._benchmark_receipt_is_authoritative(
        main
    )
    assert authoritative is True
    _write_evidence_payloads(tmp_path, payloads)

    status = materializer._operator_status_from_receipts(tmp_path)

    assert status["spoken_conversation_stt"]["production_eligible"] is False
    assert status["captured_candidate_diagnostic"]["promotion_allowed"] is True


def test_manfred_realtime_rejects_raw_extension_fields_across_evidence_envelopes(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    secret = "private transcript or provider response"
    assert materializer._raw_transcript_key_exposed(
        {
            "public_receipt_must_not_include_full_text": True,
            "redacted_text_fields": True,
        }
    ) is False
    assert materializer._raw_transcript_key_exposed(
        {"public_receipt_must_not_include_full_text": False}
    ) is True
    assert materializer._raw_transcript_key_exposed(
        {"redacted_text_fields": False}
    ) is True
    redacted_descriptor = {
        "text_chars": 4,
        "text_redacted": True,
        "text_sha256": "a" * 64,
    }
    assert materializer._raw_transcript_key_exposed(
        {
            "expected_text": redacted_descriptor,
            "required_tokens": [redacted_descriptor],
        }
    ) is False
    assert materializer._raw_transcript_key_exposed(
        {"expected_text": "raw private words"}
    ) is True
    assert materializer._raw_transcript_key_exposed(
        {"required_tokens": [{**redacted_descriptor, "rawText": secret}]}
    ) is True
    for extension_key in ("raw", "rawText", "provider_transcript"):
        assert materializer._raw_transcript_key_exposed(
            {extension_key: secret}
        ) is True
    for receipt_name, field in (
        ("memorial_stt_fixture_candidate.generated.json", "raw_response"),
        (
            "memorial_stt_provider_benchmark_captured_candidate.generated.json",
            "raw_transcript",
        ),
        ("memorial_stt_provider_benchmark.generated.json", "transcript"),
        (
            "memorial_stt_captured_candidate_diagnostic.generated.json",
            "raw_response",
        ),
    ):
        payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
        payloads[receipt_name][field] = secret
        _write_evidence_payloads(tmp_path, payloads)

        status = materializer._operator_status_from_receipts(tmp_path)

        assert status["spoken_conversation_stt"]["production_eligible"] is False
        assert secret not in json.dumps(status, sort_keys=True)

    for receipt_name in (
        "memorial_voice_roundtrip_public_origin.generated.json",
        "memorial_realtime_browser_public_origin.generated.json",
        "memorial_room_audio_public_origin.generated.json",
        "memorial_room_audio_attestation_packet.generated.json",
    ):
        payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
        payloads[receipt_name]["rawResponse"] = secret
        _write_evidence_payloads(tmp_path, payloads)

        status = materializer._operator_status_from_receipts(tmp_path)

        assert status["status"] == "blocked"
        assert secret not in json.dumps(status, sort_keys=True)


def test_manfred_realtime_rejects_forged_or_ineligible_full_runtime_provider_rows() -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    cases = (
        ("status", "forged_success"),
        ("transcriber", "attacker/provider"),
        ("scored_text_source", "semantic_repair"),
        ("min_token_f1", -1.0),
        ("max_wer", -1.0),
        ("provider_evidence_status", "blocked"),
        ("failure_codes", ["forged_success"]),
    )
    for field, value in cases:
        payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
        benchmark = payloads["memorial_stt_provider_benchmark.generated.json"]
        rows = benchmark["rows"]
        assert isinstance(rows, list)
        full_runtime = rows[0]["full_runtime"]
        assert isinstance(full_runtime, dict)
        full_runtime[field] = value
        if field == "provider_evidence_status":
            full_runtime["provider_evidence_failed_codes"] = ["provider_evidence_not_eligible"]

        authoritative, _binding, _captured_rows = (
            materializer._benchmark_receipt_is_authoritative(benchmark)
        )

        assert authoritative is False, field

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    benchmark = payloads["memorial_stt_provider_benchmark.generated.json"]
    ranking = benchmark["provider_ranking"]
    assert isinstance(ranking, list)
    full_runtime_ranking = next(
        item
        for item in ranking
        if isinstance(item, dict) and item.get("provider") == "full_runtime"
    )
    full_runtime_ranking["avg_token_f1"] = 0.5
    authoritative, _binding, _rows = materializer._benchmark_receipt_is_authoritative(
        benchmark
    )
    assert authoritative is False

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    benchmark = payloads["memorial_stt_provider_benchmark.generated.json"]
    rows = benchmark["rows"]
    assert isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
    authoritative, _binding, captured_rows = materializer._benchmark_receipt_is_authoritative(
        benchmark
    )
    assert authoritative is True
    captured_identities = {
        (str(row["sample"]), str(row["variant"])) for row in captured_rows
    }
    non_associated = next(
        row
        for row in rows
        if (str(row["sample"]), str(row["variant"])) not in captured_identities
    )
    full_runtime = non_associated["full_runtime"]
    assert isinstance(full_runtime, dict)
    full_runtime["min_token_f1"] = -1.0
    authoritative, _binding, _rows = materializer._benchmark_receipt_is_authoritative(
        benchmark
    )
    assert authoritative is False


def test_manfred_realtime_routes_automated_voice_only_failure_without_room_or_stt_work(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    browser = payloads["memorial_realtime_browser_public_origin.generated.json"]
    browser["status"] = "fail"
    browser["failed_codes"] = ["browser_audio_failed"]
    browser["audio_ready_for_ui"] = False
    browser["ui_audio_play_ended"] = 0
    _write_evidence_payloads(tmp_path, payloads)
    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(
        materializer,
        "_operator_status_from_receipts",
        lambda _evidence_root: status,
    )
    receipt_path = tmp_path / "automated-voice-only.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["blocked_checks"] == ["automated_voice_browser_tts_ready"]
    assert receipt["tts"]["room_audio_receipt"] == "pass"
    assert receipt["next_action"] == "repair_automated_voice_browser_tts_prerequisites"
    operator_action = receipt["operator_action"]
    assert operator_action["action_required_reason"] == (
        "automated_voice_browser_tts_prerequisites_not_current_or_clean"
    )
    assert operator_action["telegram_push_allowed"] is False
    assert "ground-truth" not in operator_action["instruction"].lower()
    assert "stt" not in operator_action["instruction"].lower()
    assert operator_action["required_next_receipt"] == (
        "current automated voice roundtrip and browser playback readiness evidence"
    )
    assert verifier.verify_manfred_realtime_conversation_readiness(receipt_path)["status"] == (
        "pass"
    )


def test_manfred_realtime_readiness_can_be_ready_without_closing_whole_goal(monkeypatch, tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    _write_evidence_payloads(
        tmp_path,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(
        materializer,
        "_operator_status_from_receipts",
        lambda _evidence_root: status,
    )
    receipt_path = tmp_path / "manfred-realtime-ready.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["status"] == "ready_for_realtime_conversation_review"
    assert receipt["ready_for_realtime_conversation_review"] is True
    assert receipt["realtime_conversation_claim_allowed"] is False
    assert receipt["premium_spoken_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["evidence_source"] == "receipt_aggregation"
    assert receipt["blocked_checks"] == []
    assert receipt["interaction_acceptance"]["ongoing_cinematic_narration_not_scene_bound"] is True
    assert "operator acceptance that this behaves like an ongoing spoken conversation" in receipt["required_live_proof_after_readiness"]
    assert receipt["next_action"] == "review_realtime_conversation_in_real_room"
    assert receipt["next_action_href"] == "/memorials/manfred/voice-config"
    assert receipt["next_action_label"] == "Review spoken conversation"
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_action_key"] == ""
    assert receipt["operator_action"]["status"] == "not_required"
    assert receipt["operator_action"]["user_action_required"] is False
    assert receipt["operator_action"]["delivery_policy"] == "queue_only"
    assert receipt["operator_action"]["telegram_push_allowed"] is False

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_manfred_realtime_readiness_verifier_rejects_overclaims(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["contract_name"] = "wrong.contract"
    receipt["goal_completion_claim_allowed"] = True
    receipt["generated_by"] = "wrong"
    receipt["realtime_conversation_claim_allowed"] = True
    receipt["captured_candidate_diagnostic"]["promotion_allowed"] = True
    receipt["privacy"]["candidate_raw_text_fields"] = True
    receipt["required_live_proof_after_readiness"] = []
    receipt["next_action_href"] = ""
    receipt["next_action_label"] = ""
    receipt["next_action_method"] = ""
    receipt["operator_action"]["raw_token_exposed"] = True
    receipt["operator_action"]["telegram_push_allowed"] = True
    receipt["operator_action_key"] = ""
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_contract_name_mismatch" in verification["issues"]
    assert "manfred_realtime_generated_by_mismatch" in verification["issues"]
    assert "manfred_realtime_goal_completion_overclaim" in verification["issues"]
    assert "manfred_realtime_claim_overclaim" in verification["issues"]
    assert "manfred_realtime_realtime_claim_inconsistent" in verification["issues"]
    assert "manfred_realtime_captured_diagnostic_overclaim" in verification["issues"]
    assert "manfred_realtime_privacy_flag_not_false:candidate_raw_text_fields" in verification["issues"]
    assert "manfred_realtime_required_live_proof_incomplete" in verification["issues"]
    assert "manfred_realtime_next_action_method_missing" in verification["issues"]
    assert "manfred_realtime_blocked_next_action_href_drift" in verification["issues"]
    assert "manfred_realtime_blocked_next_action_label_drift" in verification["issues"]
    assert "manfred_realtime_operator_action_raw_flag_not_false:raw_token_exposed" in verification["issues"]
    assert "manfred_realtime_operator_action_push_flag_mismatch" in verification["issues"]
    assert "manfred_realtime_operator_action_key_missing" in verification["issues"]


def test_manfred_realtime_verifier_requires_claim_booleans_to_be_exact_false(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "truthy-claim-impostors.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["realtime_conversation_claim_allowed"] = 0
    receipt["premium_spoken_claim_allowed"] = "false"
    receipt["goal_completion_claim_allowed"] = 1
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_realtime_claim_inconsistent" in verification["issues"]
    assert "manfred_realtime_premium_claim_inconsistent" in verification["issues"]
    assert "manfred_realtime_goal_completion_overclaim" in verification["issues"]


def test_manfred_realtime_generated_at_is_canonical_fresh_and_fail_closed(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "generated-at.generated.json"
    invalid_values = (
        "not-a-timestamp",
        datetime.now(UTC).replace(tzinfo=None, microsecond=0).isoformat(),
        (datetime.now(UTC) - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
        (datetime.now(UTC) + timedelta(minutes=6)).isoformat().replace("+00:00", "Z"),
    )
    for invalid in invalid_values:
        with pytest.raises(ValueError):
            materializer.materialize_manfred_realtime_conversation_readiness(
                receipt_path=receipt_path,
                generated_at=invalid,
                operator_status=_operator_status(ready=False),
            )

    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert str(receipt["generated_at"]).endswith("Z")

    for invalid in invalid_values:
        tampered = dict(receipt)
        tampered["generated_at"] = invalid
        receipt_path.write_text(
            json.dumps(tampered, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verification = verifier.verify_manfred_realtime_conversation_readiness(
            receipt_path
        )
        assert verification["status"] == "fail"
        assert "manfred_realtime_generated_at_invalid_or_stale" in verification["issues"]


def test_manfred_realtime_atomic_local_receipt_roundtrip(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "new" / "nested" / "atomic.generated.json"

    first = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=materializer._now(),
        operator_status=_operator_status(ready=False),
    )
    second = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=materializer._now(),
        operator_status=_operator_status(ready=False),
    )

    assert first["contract_name"] == second["contract_name"]
    assert stat.S_ISREG(os.lstat(receipt_path).st_mode)
    assert all(".tmp-" not in child.name for child in receipt_path.parent.iterdir())
    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)
    assert verification["status"] == "pass", verification


def test_manfred_realtime_atomic_writer_preserves_unsafe_targets_and_parents(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    victim = tmp_path / "victim.json"
    victim.write_text("do-not-clobber\n", encoding="utf-8")
    receipt_link = tmp_path / "receipt-link.json"
    receipt_link.symlink_to(victim.name)

    with pytest.raises(materializer.UnsafeLocalFileError):
        materializer.materialize_manfred_realtime_conversation_readiness(
            receipt_path=receipt_link,
            generated_at=materializer._now(),
            operator_status=_operator_status(ready=False),
        )

    assert receipt_link.is_symlink()
    assert os.readlink(receipt_link) == victim.name
    assert victim.read_text(encoding="utf-8") == "do-not-clobber\n"

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent.name, target_is_directory=True)
    with pytest.raises(materializer.UnsafeLocalFileError):
        materializer.materialize_manfred_realtime_conversation_readiness(
            receipt_path=linked_parent / "escaped.json",
            generated_at=materializer._now(),
            operator_status=_operator_status(ready=False),
        )
    assert not (real_parent / "escaped.json").exists()

    fifo_path = tmp_path / "receipt.fifo"
    os.mkfifo(fifo_path)
    with pytest.raises(materializer.UnsafeLocalFileError):
        materializer.materialize_manfred_realtime_conversation_readiness(
            receipt_path=fifo_path,
            generated_at=materializer._now(),
            operator_status=_operator_status(ready=False),
        )
    assert stat.S_ISFIFO(os.lstat(fifo_path).st_mode)

    hardlink_victim = tmp_path / "hardlink-victim.json"
    hardlink_victim.write_text("shared-inode-must-survive\n", encoding="utf-8")
    hardlink_receipt = tmp_path / "hardlink-receipt.json"
    os.link(hardlink_victim, hardlink_receipt)
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=hardlink_receipt,
        generated_at=materializer._now(),
        operator_status=_operator_status(ready=False),
    )
    assert hardlink_victim.read_text(encoding="utf-8") == "shared-inode-must-survive\n"
    assert os.lstat(hardlink_victim).st_ino != os.lstat(hardlink_receipt).st_ino

    failed_commit_target = tmp_path / "failed-commit.json"
    failed_commit_target.write_text("original-survives\n", encoding="utf-8")

    def fail_replace(*_args, **_kwargs) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(materializer.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        materializer._write(failed_commit_target, {"status": "replacement"})
    assert failed_commit_target.read_text(encoding="utf-8") == "original-survives\n"
    assert all(".tmp-" not in child.name for child in tmp_path.iterdir())


def test_manfred_realtime_atomic_writer_rejects_nonfinite_and_oversize_json(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")

    with pytest.raises(materializer.UnsafeLocalFileError):
        materializer._write(tmp_path / "nan.json", {"value": float("nan")})
    with pytest.raises(materializer.UnsafeLocalFileError):
        materializer._write(
            tmp_path / "oversize.json",
            {"value": "x" * materializer.MAX_LOCAL_JSON_BYTES},
        )

    assert not (tmp_path / "nan.json").exists()
    assert not (tmp_path / "oversize.json").exists()


def test_manfred_realtime_verifier_refuses_symlink_receipt(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    real_receipt = tmp_path / "real.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=real_receipt,
        generated_at=materializer._now(),
        operator_status=_operator_status(ready=False),
    )
    receipt_link = tmp_path / "linked.generated.json"
    receipt_link.symlink_to(real_receipt.name)

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_link)

    assert verification == {
        "contract_name": "ea.manfred_realtime_conversation_readiness.verify.v1",
        "status": "fail",
        "issues": ["manfred_realtime_receipt_unsafe"],
    }
    assert receipt_link.is_symlink()
    assert real_receipt.is_file()


def test_manfred_realtime_evidence_reader_rejects_symlink_oversize_and_short_read(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    receipt_name, expected_contract = materializer.EVIDENCE_RECEIPTS["voice_roundtrip"]
    current_head = materializer.resolve_source_state_head(materializer.REPO_ROOT)
    current_fingerprint = materializer.resolve_source_worktree_fingerprint(
        materializer.REPO_ROOT
    )
    real_receipt = tmp_path / "real-evidence.json"
    real_receipt.write_text("{}\n", encoding="utf-8")
    evidence_path = tmp_path / receipt_name
    evidence_path.symlink_to(real_receipt.name)

    payload, evidence = materializer._load_evidence_receipt(
        root=tmp_path,
        receipt_name=receipt_name,
        expected_contract=expected_contract,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
        max_age_seconds=60,
    )
    assert payload == {}
    assert evidence["status"] == "invalid"
    assert evidence_path.is_symlink()

    evidence_path.unlink()
    evidence_path.write_bytes(b"x" * (materializer.MAX_LOCAL_JSON_BYTES + 1))
    payload, evidence = materializer._load_evidence_receipt(
        root=tmp_path,
        receipt_name=receipt_name,
        expected_contract=expected_contract,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
        max_age_seconds=60,
    )
    assert payload == {}
    assert evidence["status"] == "invalid"

    evidence_path.write_bytes(b"{}\n")
    monkeypatch.setattr(materializer.os, "read", lambda _fd, _size: b"")
    with pytest.raises(materializer.UnsafeLocalFileError, match="short_read"):
        materializer._read_regular_file_snapshot(evidence_path)


def test_manfred_realtime_readiness_verifier_rejects_stale_source_state(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "stale.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_git_head"] = "old-source-head"
    receipt["source_state_fingerprint"] = "old-source-fingerprint"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_source_head_stale" in verification["issues"]
    assert "manfred_realtime_source_fingerprint_stale" in verification["issues"]


def test_manfred_realtime_readiness_verifier_rejects_missing_source_stamp(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "unstamped.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for key in (
        "source_git_head",
        "head_semantics",
        "source_state_fingerprint",
        "source_state_fingerprint_semantics",
    ):
        receipt.pop(key, None)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_source_git_head_missing" in verification["issues"]
    assert "manfred_realtime_source_fingerprint_missing" in verification["issues"]
    assert "manfred_realtime_head_semantics_missing" in verification["issues"]
    assert "manfred_realtime_source_fingerprint_semantics_missing" in verification["issues"]


def test_manfred_realtime_readiness_clis_work(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    _write_evidence_payloads(
        evidence_root,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    receipt_path = tmp_path / "cli-manfred-realtime.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_manfred_realtime_conversation_readiness.py"),
            "--receipt",
            str(receipt_path),
            "--evidence-root",
            str(evidence_root),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    assert receipt_path.is_file()
    materialized_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert materialized_receipt["evidence_source"] == "receipt_aggregation"
    assert materialized_receipt["status"] == "ready_for_realtime_conversation_review"

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_manfred_realtime_conversation_readiness.py"),
            "--receipt",
            str(receipt_path),
            "--evidence-root",
            str(evidence_root),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )

    assert verified.returncode == 0, verified.stderr + verified.stdout
    assert json.loads(verified.stdout)["status"] == "pass"
