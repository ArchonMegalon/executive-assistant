from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_memorial_stt_providers.py"
CANDIDATE_SCRIPT = ROOT / "scripts" / "materialize_memorial_stt_fixture_candidate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("benchmark_memorial_stt_providers", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_candidate_module():
    spec = importlib.util.spec_from_file_location("materialize_memorial_stt_fixture_candidate_for_benchmark", CANDIDATE_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _external_candidate_inputs(
    bundle: Path,
    *,
    sample: str = "real_room_retry_candidate",
    expected_text: str = "Kommt da noch was oder bist du jetzt stumm?",
    required_tokens: list[str] | None = None,
    provider_upload_authorization: dict[str, bool] | None = None,
    max_audio_duration_seconds: float | None = None,
    expected_status: str = "pass",
    reviewed_at: str | None = None,
) -> tuple[Path, Path, dict[str, object]]:
    tokens = required_tokens or ["kommt", "stumm"]
    audio_sha256 = hashlib.sha256((bundle / "input.wav").read_bytes()).hexdigest()
    review_path = bundle.parent / f"{bundle.name}.ground-truth-review.json"
    review_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.memorial_stt_operator_ground_truth_review.v2",
                "status": "approved",
                "reviewed_at": reviewed_at
                or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "reviewer_authority": "memorial_operator",
                "audio_sha256": audio_sha256,
                "bundle_id": bundle.name,
                "sample": sample,
                "expected_text": expected_text,
                "required_tokens": tokens,
                "speaker_consent": "operator_attested_for_private_stt_regression",
                "allowed_purpose": "memorial_stt_regression_and_provider_bakeoff",
                "retention": "private_captured_regression_candidate",
                "language": "de",
                "accent": "Austrian German",
                "provider_upload_authorization": provider_upload_authorization
                if provider_upload_authorization is not None
                else {
                    "full_runtime": True,
                    "shadow": True,
                    "onemin_sample": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    review_path.chmod(0o600)
    candidate_module = _load_candidate_module()
    candidate = candidate_module.build_fixture_candidate(
        bundle_dir=bundle,
        ground_truth_review_path=review_path,
        origin="captured_operator_manfred_memorial_stt_error_bundle",
        fixture_file=f"{sample}_captured.wav",
        allow_external_root=True,
        max_audio_duration_seconds=max_audio_duration_seconds,
    )
    assert candidate["status"] == expected_status
    receipt_path = bundle.parent / f"{bundle.name}.candidate.json"
    receipt_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt_path, review_path, candidate


def _tracked_spec(module, *, sample: str = "tracked_sample") -> dict[str, object]:
    payload = module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000)
    quality = module._fixture_quality(
        payload=payload,
        expected_text="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        synthetic=True,
    )
    return {
        "sample": sample,
        "file": f"{sample}.wav",
        "payload": payload,
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "language": "de",
        "min_token_f1": 0.65,
        "max_wer": 0.45,
        "fixture_sha256": hashlib.sha256(payload).hexdigest(),
        "fixture_quality": quality,
        "provider_upload_authorization": {
            "full_runtime": True,
            "shadow": True,
            "onemin_sample": True,
        },
        "provenance": {
            "origin": "test",
            "speaker_consent": "synthetic",
            "allowed_purpose": "test",
            "retention": "test",
            "synthetic": True,
            "accent": "",
            "provider_upload_authorization": {
                "full_runtime": True,
                "shadow": True,
                "onemin_sample": True,
            },
        },
    }


def _stub_runtime_probes(module, monkeypatch) -> None:
    monkeypatch.setattr(module, "_cartesia_credential_probe", lambda: {"configured": False})
    monkeypatch.setattr(module, "_cartesia_default_credential_file_present", lambda: False)
    monkeypatch.setattr(module.product_service, "_pocket_onemin_api_keys", lambda: ())
    monkeypatch.setattr(module.public_memorials, "_memorial_onemin_max_key_attempts", lambda: 3)
    monkeypatch.setattr(module.public_memorials, "_text", lambda value, default="": str(value or default))


def test_stt_benchmark_scores_expected_transcript_as_pass() -> None:
    module = _load_module()
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    score = module._score_text("Hallo Manfred, kannst du jetzt mit mir sprechen?", spec)

    assert score["passed"] is True
    assert score["intent_correct"] is True
    assert score["token_f1"] == 1.0
    assert score["wer"] == 0.0


def test_stt_benchmark_rejects_non_empty_generic_transcript() -> None:
    module = _load_module()
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    score = module._score_text("Was ist das?", spec)

    assert score["usable"] is True
    assert score["passed"] is False
    assert score["intent_correct"] is False
    assert score["token_f1"] < 0.65
    assert score["wer"] > 0.45


def test_stt_benchmark_scores_raw_json_transcript_without_semantic_repair() -> None:
    module = _load_module()
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    score = module._score_text(
        '{"task":"transcribe","text":"Untertitel der Amara.org-Community","segments":[]}',
        spec,
        text_mode="full",
    )

    assert score["actual_text"] == '{"task":"transcribe","text":"Untertitel der Amara.org-Community","segments":[]}'
    assert score["usable"] is False
    assert score["passed"] is False


def test_stt_benchmark_redacts_transcript_text_by_default() -> None:
    module = _load_module()
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    scored = module._attach_score({"status": "ok", "text": "Hallo Manfred, kannst du jetzt mit mir sprechen?"}, spec)

    assert scored["passed"] is True
    assert scored["text_mode"] == "redacted"
    assert scored["text_redacted"] is True
    assert "text" not in scored
    assert "actual_text" not in scored
    assert "expected_text" not in scored
    assert "required_tokens" not in scored
    assert scored["actual_text_chars"] > 0
    assert scored["expected_text_chars"] > 0
    assert len(scored["actual_text_sha256"]) == 64
    assert len(scored["expected_text_sha256"]) == 64
    assert scored["required_token_count"] == 3
    assert len(scored["required_token_sha256"]) == 3


def test_stt_benchmark_full_text_requires_explicit_mode() -> None:
    module = _load_module()
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    scored = module._attach_score(
        {"status": "ok", "text": "Hallo Manfred, kannst du jetzt mit mir sprechen?"},
        spec,
        text_mode="full",
    )

    assert scored["text_mode"] == "full"
    assert scored["text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert scored["actual_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert scored["expected_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert scored["required_tokens"] == ["hallo", "manfred", "sprechen"]
    assert "text_redacted" not in scored


def test_stt_benchmark_loads_provider_env_files_without_overriding(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ONEMIN_AI_API_KEY=file-key",
                "EA_CARTESIA_CREDENTIALS_JSON={\"api_key\":\"cartesia-file-key\"}",
                "export EA_MEMORIAL_ONEMIN_MAX_KEY_ATTEMPTS=2",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "existing-key")
    monkeypatch.delenv("EA_CARTESIA_CREDENTIALS_JSON", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_ONEMIN_MAX_KEY_ATTEMPTS", raising=False)

    report = module._load_provider_env_files((env_file,))

    assert os.environ["ONEMIN_AI_API_KEY"] == "existing-key"
    assert os.environ["EA_CARTESIA_CREDENTIALS_JSON"] == '{"api_key":"cartesia-file-key"}'
    assert os.environ["EA_MEMORIAL_ONEMIN_MAX_KEY_ATTEMPTS"] == "2"
    assert "ONEMIN_AI_API_KEY" not in report["loaded_names"]
    assert "EA_CARTESIA_CREDENTIALS_JSON" in report["loaded_names"]
    assert "EA_MEMORIAL_ONEMIN_MAX_KEY_ATTEMPTS" in report["loaded_names"]
    assert "cartesia-file-key" not in str(report)
    assert report["file_count"] == 1
    assert "files" not in report


def test_stt_benchmark_defaults_load_local_env_and_detect_default_cartesia_file(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    credential_path = tmp_path / "cartesia.local.json"
    credential_path.write_text('{"api_key":"cartesia-default-key"}', encoding="utf-8")
    monkeypatch.setattr(module.public_memorials, "_CARTESIA_DEFAULT_CREDENTIAL_FILES", (str(credential_path),))

    assert any(path.name == ".env.local" for path in module.DEFAULT_PROVIDER_ENV_FILES)
    assert module._cartesia_default_credential_file_present() is True
    probe = module._cartesia_credential_probe()
    assert probe["configured"] is True
    assert probe["credential_source"] == "default_credential_file"
    assert probe["default_credential_files"][0]["present"] is True
    assert probe["default_credential_files"][0]["contains_key"] is True
    assert "cartesia-default-key" not in str(probe)
    assert str(credential_path) not in str(probe)


def test_stt_benchmark_provider_env_receipt_summary_does_not_list_secret_names() -> None:
    module = _load_module()

    summary = module._provider_env_receipt_summary(
        {
            "files": [".env"],
            "loaded_count": 4,
            "loaded_names": [
                "ONEMIN_AI_API_KEY",
                "EA_CARTESIA_CREDENTIALS_JSON",
                "BLIPAI_APP_API_TOKEN",
                "UNRELATED_PASSWORD",
            ],
        }
    )

    assert summary == {
        "file_count": 1,
        "loaded_count": 4,
        "provider_families": {
            "cartesia": True,
            "onemin": True,
            "blipai_shadow": True,
        },
    }
    assert "ONEMIN_AI_API_KEY" not in str(summary)
    assert "PASSWORD" not in str(summary)


def test_stt_benchmark_provider_env_summary_uses_cartesia_credential_probe() -> None:
    module = _load_module()

    summary = module._provider_env_receipt_summary(
        {
            "files": [],
            "loaded_count": 0,
            "loaded_names": [],
        },
        cartesia_probe={
            "configured": True,
            "credential_source": "default_credential_file",
        },
    )

    assert summary["provider_families"]["cartesia"] is True
    assert "default_credential_file" not in str(summary)


def test_stt_benchmark_sanitizes_provider_credit_errors() -> None:
    module = _load_module()

    detail = module._sanitize_provider_error_detail(
        'onemin_transcribe_http_406:{"errorCode":"INSUFFICIENT_CREDITS","message":"The feature requires 105 credits, but the Girschele Family team only has 35 credits"}'
    )

    assert detail["contract_name"] == "ea.memorial_stt_provider_error_detail.v1"
    assert detail["category"] == "insufficient_credits"
    assert detail["code"] == "onemin_transcribe_http_406"
    assert len(detail["detail_sha256"]) == 64
    assert "Girschele" not in detail
    assert "Family" not in detail


def test_stt_benchmark_sanitizes_provider_error_urls() -> None:
    module = _load_module()

    detail = module._sanitize_provider_error_detail(
        'onemin_transcribe_http_400:{"message":"Failed to analyze media file: https://s3.us-east-1.amazonaws.com/asset.1min.ai/audios/private.wav"}'
    )

    assert "https://" not in detail
    assert "asset.1min.ai" not in detail
    assert detail["category"] == "http_error"
    assert len(detail["detail_sha256"]) == 64


def test_stt_benchmark_onemin_sample_uses_runtime_spread_selection(monkeypatch) -> None:
    module = _load_module()
    keys = tuple(f"key-{index}" for index in range(1, 8))
    uploaded_keys: list[str] = []
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    monkeypatch.setattr(module.product_service, "_pocket_onemin_api_keys", lambda: keys)
    monkeypatch.setattr(
        module.public_memorials,
        "_memorial_onemin_available_keys",
        lambda candidate_keys: ("key-1", "key-4", "key-7"),
    )
    monkeypatch.setattr(
        module.product_service,
        "_onemin_asset_upload",
        lambda **kwargs: (
            uploaded_keys.append(str(kwargs.get("api_key") or "")),
            {"asset": {"key": "audio"}, "fileContent": {"path": "audio-path"}},
        )[1],
    )
    monkeypatch.setattr(
        module.product_service,
        "_onemin_speech_to_text",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError('onemin_transcribe_http_406:{"errorCode":"INSUFFICIENT_CREDITS"}')
        ),
    )

    result = module._run_onemin_sample(b"audio", spec)

    assert uploaded_keys == ["key-1", "key-4", "key-7"]
    assert result["sampled_keys"] == 3
    assert result["candidate_key_count"] == 7
    assert result["sample_strategy"] == "primary_plus_spread_fallbacks"


def test_stt_fixture_manifest_carries_consent_hash_and_expected_text() -> None:
    module = _load_module()

    specs = module._fixture_specs()

    assert {spec["sample"] for spec in specs} >= {"contact_opening", "stt_retry", "technical_retry"}
    assert any(spec["provenance"]["synthetic"] is True for spec in specs)
    for spec in specs:
        assert spec["fixture_sha256"]
        assert spec["expected_text"]
        assert spec["required_tokens"]
        assert spec["fixture_quality"]["audio_duration_seconds"] > 0
        assert spec["fixture_quality"]["expected_min_duration_seconds"] > 0
        assert spec["provenance"]["speaker_consent"]
        assert spec["provenance"]["allowed_purpose"]
        assert spec["provenance"]["retention"]


def test_stt_fixture_quality_blocks_audio_too_short_for_expected_text() -> None:
    module = _load_module()

    quality = module._fixture_quality(
        payload=module._wav_from_samples([1200] * 1600, sample_rate=16_000),
        expected_text="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        synthetic=False,
    )

    assert quality["status"] == "blocked"
    assert "audio_too_short_for_expected_text" in quality["failed_codes"]
    assert "captured_audio_too_short" in quality["failed_codes"]


def test_stt_fixture_quality_accepts_plausible_synthetic_duration() -> None:
    module = _load_module()

    quality = module._fixture_quality(
        payload=module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000),
        expected_text="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        synthetic=True,
    )

    assert quality["status"] == "pass"
    assert quality["failed_codes"] == []


def test_stt_fixture_quality_accepts_open_ended_streaming_wav_header() -> None:
    module = _load_module()
    payload = bytearray(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    payload[4:8] = (0xFFFFFFFF).to_bytes(4, "little")
    data_offset = bytes(payload).find(b"data")
    assert data_offset > 0
    payload[data_offset + 4:data_offset + 8] = (0xFFFFFFFF).to_bytes(4, "little")

    quality = module._fixture_quality(
        payload=bytes(payload),
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        synthetic=False,
    )
    sample_rate, samples = module._wav_pcm16_samples(bytes(payload))

    assert quality["status"] == "pass"
    assert quality["audio_duration_seconds"] == 3.0
    assert sample_rate == 16_000
    assert len(samples) == 16_000 * 3


def test_stt_external_captured_candidate_spec_uses_private_bundle_without_repo_copy(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "082347_realtime_audio_turn_generic_fallback_answer"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, candidate = _external_candidate_inputs(bundle)

    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        candidate_receipt_path=receipt_path,
        ground_truth_review_path=review_path,
        allow_external_root=True,
    )

    assert spec["sample"] == "real_room_retry_candidate"
    assert spec["file"] == "input.wav"
    assert spec["fixture_quality"]["status"] == "pass"
    assert spec["provenance"]["external_bundle"] is True
    assert spec["provenance"]["synthetic"] is False
    assert spec["payload"]
    assert spec["captured_candidate_binding"] == {
        "candidate_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "candidate_binding_contract_name": "ea.memorial_stt_fixture_candidate_binding.v2",
        "candidate_binding_sha256": candidate["candidate_binding"]["sha256"],
        "operator_ground_truth_review_binding_sha256": candidate["operator_ground_truth_review"]["sha256"],
        "source_audio_sha256": candidate["audio"]["sha256"],
        "bundle_id": bundle.name,
        "sample": "real_room_retry_candidate",
        "provider_upload_authorization": {
            "full_runtime": True,
            "shadow": True,
            "onemin_sample": True,
        },
    }
    assert spec["provenance"]["candidate_receipt_sha256"] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    scored = module._attach_score({"status": "ok", "text": spec["expected_text"]}, spec)
    assert scored["expected_text_sha256"] == candidate["candidate_binding"]["payload"]["expected_text_sha256"]
    assert scored["required_token_sha256"] == candidate["candidate_binding"]["payload"]["required_token_sha256"]


def test_stt_external_captured_candidate_report_stays_redacted(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "candidate"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, _candidate = _external_candidate_inputs(bundle)
    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        candidate_receipt_path=receipt_path,
        ground_truth_review_path=review_path,
        allow_external_root=True,
    )
    row = {
        "sample": spec["sample"],
        "variant": "captured",
        "fixture": spec["file"],
        "fixture_sha256": spec["fixture_sha256"],
        "source_fixture_sha256": spec["fixture_sha256"],
        "fixture_quality": spec["fixture_quality"],
        "provenance": spec["provenance"],
        "full_runtime": module._attach_score(
            {"status": "transcribed", "text": spec["expected_text"], "ms": 1.0},
            spec,
        ),
        "shadow": module._attach_score({"status": "empty", "text": "", "ms": 0.0}, spec),
        "onemin_sample": {"status": "unavailable", "detail": "no_keys"},
    }

    report = module._build_report(rows=[row], availability={"cartesia_configured": True})

    rendered = str(report)
    assert report["rows"][0]["provenance"]["external_bundle"] is True
    assert report["rows"][0]["full_runtime"]["text_redacted"] is True
    assert "Kommt da noch was" not in rendered


def test_stt_benchmark_report_surfaces_fixture_quality_blocker() -> None:
    module = _load_module()
    rows = [
        {
            "fixture_quality": {
                "status": "blocked",
                "failed_codes": ["audio_too_short_for_expected_text"],
            },
            "full_runtime": {"passed": False, "intent_correct": False, "token_f1": 0.0, "wer": 1.0, "ms": 0},
            "shadow": {"passed": False, "intent_correct": False, "token_f1": 0.0, "wer": 1.0, "ms": 0},
            "onemin_sample": {"passed": False, "intent_correct": False, "token_f1": 0.0, "wer": 1.0, "ms": 0},
        }
    ]

    report = module._build_report(rows=rows, availability={"cartesia_configured": True})

    assert report["status"] == "blocked"
    assert report["fixture_quality_status"] == "blocked"
    assert report["fixture_quality_failed_codes"] == ["audio_too_short_for_expected_text"]


def test_stt_benchmark_report_has_current_source_stamp(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "resolve_source_state_head", lambda _root: "HEAD")
    monkeypatch.setattr(
        module,
        "resolve_source_worktree_fingerprint",
        lambda _root: "worktree-fingerprint",
    )

    captured_binding = {"candidate_receipt_sha256": "a" * 64}
    report = module._build_report(
        rows=[],
        availability={"cartesia_configured": False},
        captured_candidate_binding=captured_binding,
    )

    assert report["generated_by"] == "scripts/benchmark_memorial_stt_providers.py"
    assert report["generated_at"]
    assert report["source_git_head"] == "HEAD"
    assert report["head_semantics"] == "source_state"
    assert report["source_state_fingerprint"] == "worktree-fingerprint"
    assert (
        report["source_state_fingerprint_semantics"]
        == "worktree_source_files_sha256_excluding_generated_only_paths"
    )
    assert report["captured_candidate_binding"]["candidate_receipt_sha256"] == "a" * 64
    assert set(report["captured_candidate_binding"]) == {
        "candidate_receipt_sha256",
        "candidate_binding_contract_name",
        "candidate_binding_sha256",
        "operator_ground_truth_review_binding_sha256",
        "source_audio_sha256",
        "bundle_id",
        "sample",
        "provider_upload_authorization",
    }
    assert report["scoring"]["raw_provider_transcript_scored"] is True
    assert report["scoring"]["semantic_repair_applied"] is False


def test_stt_provider_ranking_uses_accuracy_before_latency() -> None:
    module = _load_module()
    rows = [
        {
            "full_runtime": {"passed": True, "intent_correct": True, "token_f1": 0.91, "wer": 0.1, "ms": 1200},
            "shadow": {"passed": False, "intent_correct": False, "token_f1": 0.2, "wer": 0.9, "ms": 100},
            "onemin_sample": {"passed": True, "intent_correct": True, "token_f1": 0.8, "wer": 0.2, "ms": 900},
        },
        {
            "full_runtime": {"passed": True, "intent_correct": True, "token_f1": 0.95, "wer": 0.05, "ms": 1300},
            "shadow": {"passed": False, "intent_correct": False, "token_f1": 0.3, "wer": 0.8, "ms": 90},
            "onemin_sample": {"passed": False, "intent_correct": True, "token_f1": 0.7, "wer": 0.4, "ms": 800},
        },
    ]

    ranking = module._rank_providers(rows)

    assert ranking[0]["provider"] == "full_runtime"
    assert ranking[0]["production_eligible"] is True
    assert ranking[-1]["provider"] == "shadow"


def test_stt_provider_summary_preserves_zero_wer() -> None:
    module = _load_module()

    summary = module._provider_summary(
        [
            {
                "full_runtime": {
                    "passed": True,
                    "intent_correct": True,
                    "token_f1": 1.0,
                    "wer": 0.0,
                    "ms": 320,
                }
            }
        ],
        "full_runtime",
    )

    assert summary["avg_wer"] == 0.0
    assert summary["production_eligible"] is True


def test_stt_benchmark_report_blocks_when_no_provider_is_production_eligible() -> None:
    module = _load_module()
    rows = [
        {
            "full_runtime": {"passed": False, "intent_correct": False, "token_f1": 0.0, "wer": 1.0, "ms": 100},
            "shadow": {"passed": False, "intent_correct": False, "token_f1": 0.0, "wer": 1.0, "ms": 90},
            "onemin_sample": {"status": "unavailable", "detail": "no_keys"},
        }
    ]

    report = module._build_report(rows=rows, availability={"cartesia_configured": False})

    assert report["status"] == "blocked"
    assert all(row["production_eligible"] is False for row in report["provider_ranking"])
    assert report["provider_ranking"][0]["provider"] in {"full_runtime", "shadow"}
    assert report["provider_ranking"][0]["scored_samples"] == 1
    assert report["provider_ranking"][-1]["provider"] == "onemin_sample"
    assert module._exit_code_for_report(report, require_production_eligible=False) == 0
    assert module._exit_code_for_report(report, require_production_eligible=True) == 2
    assert report["scoring"]["production_eligible_rule"] == "provider must pass every ground-truth benchmark sample and hostile variant"


def test_stt_benchmark_never_calls_public_semantic_repair_for_raw_score(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.public_memorials,
        "_repair_memorial_transcript_text",
        lambda _value: (_ for _ in ()).throw(AssertionError("semantic repair must not run")),
    )
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    score = module._score_text("Hallo Manfred, kannst du jetzt mit mir sprechen?", spec)

    assert score["passed"] is True


def test_stt_benchmark_full_runtime_scores_primary_text_before_effective_repair(monkeypatch) -> None:
    module = _load_module()
    spec = {
        "expected_text": "Kommt da noch was oder bist du jetzt stumm?",
        "required_tokens": ["kommt", "stumm"],
        "min_token_f1": 0.95,
        "max_wer": 0.05,
    }
    monkeypatch.setattr(
        module.public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **_kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Kommt da noch was oder bist du jetzt stumm?",
            "primary_transcript_text": "Kommt da noch was oder bist du jetzt dumm?",
            "transcriber": "provider/raw",
        },
    )

    result = module._run_full_runtime(b"audio", spec)

    assert result["scored_text_source"] == "primary_transcript_text"
    assert result["passed"] is False
    assert result["intent_correct"] is False


def test_stt_benchmark_onemin_unavailable_still_binds_ground_truth_hashes(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.product_service, "_pocket_onemin_api_keys", lambda: ())
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }

    result = module._run_onemin_sample(b"audio", spec)

    assert result["status"] == "unavailable"
    assert result["expected_text_sha256"] == hashlib.sha256(spec["expected_text"].encode()).hexdigest()
    assert len(result["required_token_sha256"]) == 3
    assert result["text_redacted"] is True


def test_stt_benchmark_recomputes_variant_sha_duration_quality_and_transformation_receipt(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "variants"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, _candidate = _external_candidate_inputs(bundle)
    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        candidate_receipt_path=receipt_path,
        ground_truth_review_path=review_path,
        allow_external_root=True,
    )

    captured, hostile = module._sample_variants(spec)

    assert captured["sample"] == "real_room_retry_candidate"
    assert captured["variant"] == "captured"
    assert hostile["sample"] == "real_room_retry_candidate_hostile"
    assert hostile["variant"] == "hostile"
    assert captured["source_fixture_sha256"] == spec["fixture_sha256"]
    assert hostile["source_fixture_sha256"] == spec["fixture_sha256"]
    assert captured["fixture_sha256"] == hashlib.sha256(captured["payload"]).hexdigest()
    assert hostile["fixture_sha256"] == hashlib.sha256(hostile["payload"]).hexdigest()
    assert hostile["fixture_sha256"] != hostile["source_fixture_sha256"]
    assert hostile["fixture_quality"]["audio_duration_seconds"] == 3.0
    assert hostile["fixture_quality"]["status"] == "pass"
    receipt = hostile["transformation"]
    assert receipt["contract_name"] == "ea.memorial_stt_audio_transformation_receipt.v1"
    assert receipt["payload"]["duration_preserved"] is True
    assert receipt["payload"]["source_duration_seconds"] == 3.0
    assert receipt["payload"]["output_duration_seconds"] == 3.0
    assert receipt["sha256"] == module._canonical_sha256(receipt["payload"])


def test_stt_benchmark_tampered_candidate_blocks_before_any_provider_call(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    bundle = tmp_path / "tampered"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, candidate = _external_candidate_inputs(bundle)
    candidate["candidate_binding"]["payload"]["sample"] = "swapped_sample"
    receipt_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "benchmark.json"
    monkeypatch.setattr(module, "_fixture_specs", lambda: [_tracked_spec(module)])
    _stub_runtime_probes(module, monkeypatch)
    for name in ("_run_shadow", "_run_onemin_sample", "_run_full_runtime"):
        monkeypatch.setattr(
            module,
            name,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider call forbidden")),
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--output",
            str(output),
            "--no-local-env",
            "--require-production-eligible",
            "--captured-candidate-bundle-dir",
            str(bundle),
            "--captured-candidate-receipt",
            str(receipt_path),
            "--captured-candidate-ground-truth-review",
            str(review_path),
            "--captured-candidate-allow-external-root",
        ],
    )

    exit_code = module.main()

    assert exit_code == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "blocked"
    assert "candidate_binding_sha256_mismatch" in report["fixture_quality_failed_codes"]
    assert report["availability"]["governance_preflight"]["blocked"] is True
    stdout = capsys.readouterr().out
    assert "Kommt da noch was" not in stdout
    assert '"stdout_redacted": true' in stdout


def test_stt_benchmark_malformed_candidate_shapes_fail_closed_without_exception(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "malformed"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, candidate = _external_candidate_inputs(bundle)
    candidate["contract_version"] = "not-a-version"
    candidate["candidate_binding"] = "not-an-object"
    candidate["operator_ground_truth_review"] = ["not-an-object"]
    candidate["candidate_manifest_entry"] = "not-an-object"
    receipt_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")

    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        candidate_receipt_path=receipt_path,
        ground_truth_review_path=review_path,
        allow_external_root=True,
    )

    assert spec["fixture_quality"]["status"] == "blocked"
    assert "candidate_receipt_version_invalid" in spec["fixture_quality"]["failed_codes"]
    assert "candidate_binding_contract_invalid" in spec["fixture_quality"]["failed_codes"]


def test_stt_benchmark_full_text_repo_output_refuses_before_fixture_or_provider(
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()
    forbidden_output = ROOT / ".benchmark-full-output-test.json"
    monkeypatch.setattr(
        module,
        "_fixture_specs",
        lambda: (_ for _ in ()).throw(AssertionError("fixture loading must not run")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--text-mode", "full", "--output", str(forbidden_output)],
    )

    exit_code = module.main()

    assert exit_code == 2
    assert not forbidden_output.exists()
    stdout = capsys.readouterr().out
    assert "full_text_repo_output_forbidden" in stdout
    assert '"stdout_redacted": true' in stdout


def test_stt_benchmark_full_runtime_never_falls_back_to_effective_repaired_text(monkeypatch) -> None:
    module = _load_module()
    spec = {
        "expected_text": "Kommt da noch was oder bist du jetzt stumm?",
        "required_tokens": ["kommt", "stumm"],
        "min_token_f1": 0.95,
        "max_wer": 0.05,
    }
    monkeypatch.setattr(
        module.public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **_kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Kommt da noch was oder bist du jetzt stumm?",
            "transcriber": "provider/effective",
        },
    )

    result = module._run_full_runtime(b"audio", spec)

    assert result["passed"] is False
    assert result["scored_text_source"] == "none"
    assert result["actual_text_chars"] == 0
    assert "primary_raw_transcript_missing" in result["provider_evidence_failed_codes"]


def test_stt_benchmark_matching_raw_text_cannot_pass_with_error_status(monkeypatch) -> None:
    module = _load_module()
    expected = "Kommt da noch was oder bist du jetzt stumm?"
    spec = {
        "expected_text": expected,
        "required_tokens": ["kommt", "stumm"],
        "min_token_f1": 0.95,
        "max_wer": 0.05,
    }
    monkeypatch.setattr(
        module.public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **_kwargs: {
            "transcription_status": "error",
            "primary_transcript_text": expected,
            "transcript_text": expected,
        },
    )

    result = module._run_full_runtime(b"audio", spec)

    assert result["token_f1"] == 1.0
    assert result["passed"] is False
    assert "provider_status_not_successful" in result["provider_evidence_failed_codes"]

    direct = module._attach_score({"status": "unavailable", "text": expected}, spec)
    assert direct["passed"] is False
    assert "provider_status_not_successful" in direct["provider_evidence_failed_codes"]


def test_stt_benchmark_rejects_status_flip_over_bound_blocked_quality(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "status-flip"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, candidate = _external_candidate_inputs(
        bundle,
        max_audio_duration_seconds=1.0,
        expected_status="blocked",
    )
    assert candidate["candidate_binding"]["payload"]["fixture_quality"]["status"] == "blocked"
    candidate["status"] = "pass"
    candidate["failed_codes"] = []
    receipt_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")

    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        candidate_receipt_path=receipt_path,
        ground_truth_review_path=review_path,
        allow_external_root=True,
    )

    assert spec["fixture_quality"]["status"] == "blocked"
    assert "candidate_binding_payload_projection_mismatch" in spec["fixture_quality"]["failed_codes"]
    assert "candidate_bound_status_not_passed" in spec["fixture_quality"]["failed_codes"]
    assert "candidate_bound_fixture_quality_not_passed" in spec["fixture_quality"]["failed_codes"]


def test_stt_benchmark_explicit_upload_authorization_suppresses_unapproved_provider_calls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    bundle = tmp_path / "authorized-primary-only"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, _candidate = _external_candidate_inputs(
        bundle,
        provider_upload_authorization={
            "full_runtime": True,
            "shadow": False,
            "onemin_sample": False,
        },
    )
    output = tmp_path / "authorized-primary-only.json"
    calls: list[str] = []
    monkeypatch.setattr(module, "_fixture_specs", lambda: [])
    _stub_runtime_probes(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "_run_shadow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("shadow upload forbidden")),
    )
    monkeypatch.setattr(
        module,
        "_run_onemin_sample",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("OneMin upload forbidden")),
    )

    def _full_runtime(_payload, spec, **_kwargs):
        calls.append(str(spec["variant"]))
        return module._attach_score(
            {"status": "transcribed", "text": spec["expected_text"]},
            spec,
            evidence_eligible=True,
        )

    monkeypatch.setattr(module, "_run_full_runtime", _full_runtime)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--output",
            str(output),
            "--no-local-env",
            "--require-production-eligible",
            "--captured-candidate-bundle-dir",
            str(bundle),
            "--captured-candidate-receipt",
            str(receipt_path),
            "--captured-candidate-ground-truth-review",
            str(review_path),
            "--captured-candidate-allow-external-root",
        ],
    )

    exit_code = module.main()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert calls == ["captured", "hostile"]
    assert report["availability"]["governance_preflight"]["captured_candidate_pair_count"] == 1
    assert all(row["shadow"]["status"] == "not_authorized" for row in report["rows"])
    assert all(row["onemin_sample"]["status"] == "not_authorized" for row in report["rows"])


def test_stt_benchmark_rejects_external_sample_collision_before_provider_calls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    bundle = tmp_path / "collision"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, _candidate = _external_candidate_inputs(bundle, sample="tracked_sample")
    output = tmp_path / "collision.json"
    monkeypatch.setattr(module, "_fixture_specs", lambda: [_tracked_spec(module, sample="tracked_sample")])
    _stub_runtime_probes(module, monkeypatch)
    for name in ("_run_shadow", "_run_onemin_sample", "_run_full_runtime"):
        monkeypatch.setattr(
            module,
            name,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider call forbidden")),
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--output",
            str(output),
            "--no-local-env",
            "--captured-candidate-bundle-dir",
            str(bundle),
            "--captured-candidate-receipt",
            str(receipt_path),
            "--captured-candidate-ground-truth-review",
            str(review_path),
            "--captured-candidate-allow-external-root",
        ],
    )

    module.main()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert report["status"] == "blocked"
    assert "candidate_sample_collision" in report["fixture_quality_failed_codes"]
    assert report["availability"]["governance_preflight"]["blocked"] is True


def test_stt_benchmark_candidate_pair_validator_rejects_missing_or_duplicate_rows(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "pair-validator"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, _candidate = _external_candidate_inputs(bundle)
    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        candidate_receipt_path=receipt_path,
        ground_truth_review_path=review_path,
        allow_external_root=True,
    )
    variants = module._sample_variants(spec)
    binding = spec["captured_candidate_binding"]

    assert module._candidate_pair_failures(variants, binding=binding) == []
    assert "captured_candidate_pair_invalid" in module._candidate_pair_failures(variants[:1], binding=binding)
    assert "captured_candidate_pair_invalid" in module._candidate_pair_failures(
        [variants[0], variants[0]],
        binding=binding,
    )


def test_stt_benchmark_redacted_receipt_hashes_arbitrary_provider_detail() -> None:
    module = _load_module()
    sentinel = "Kommt da noch was PRIVATE PROVIDER DETAIL"
    spec = {
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "min_token_f1": 0.65,
        "max_wer": 0.45,
    }
    result = module._attach_score(
        {"status": "error", "text": "", "detail": sentinel, "reason": sentinel},
        spec,
        evidence_eligible=False,
    )
    report = module._build_report(
        rows=[{"fixture_quality": {"status": "pass", "failed_codes": []}, "full_runtime": result}],
        availability={},
    )

    assert sentinel not in str(report)
    assert report["rows"][0]["full_runtime"]["detail"]["contract_name"] == "ea.memorial_stt_provider_error_detail.v1"
    assert len(report["rows"][0]["full_runtime"]["detail"]["detail_sha256"]) == 64


def test_stt_benchmark_blocks_hostile_transform_when_duration_is_not_preserved(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "duration-transform"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, _candidate = _external_candidate_inputs(bundle)
    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        candidate_receipt_path=receipt_path,
        ground_truth_review_path=review_path,
        allow_external_root=True,
    )
    monkeypatch.setattr(
        module,
        "_hostile",
        lambda _payload: module._wav_from_samples([1200] * 16_000, sample_rate=16_000),
    )

    _captured, hostile = module._sample_variants(spec)

    assert hostile["fixture_quality"]["status"] == "blocked"
    assert "hostile_transform_duration_not_preserved" in hostile["fixture_quality"]["failed_codes"]
    assert hostile["transformation"]["payload"]["duration_preserved"] is False


def test_stt_benchmark_rejects_symlinked_candidate_receipt_and_tracked_fixture(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "candidate-receipt-link"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, _candidate = _external_candidate_inputs(bundle)
    linked_receipt = tmp_path / "linked-candidate.json"
    linked_receipt.symlink_to(receipt_path)

    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        candidate_receipt_path=linked_receipt,
        ground_truth_review_path=review_path,
        allow_external_root=True,
    )
    assert "candidate_receipt_symlink_forbidden" in spec["fixture_quality"]["failed_codes"]

    fixture_root = tmp_path / "fixtures"
    fixture_root.mkdir()
    private_target = fixture_root / "private.wav"
    private_target.write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    (fixture_root / "linked.wav").symlink_to(private_target)
    entry = {
        "sample": "linked_fixture",
        "file": "linked.wav",
        "origin": "synthetic",
        "speaker_consent": "synthetic",
        "allowed_purpose": "test",
        "retention": "test",
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "sha256": hashlib.sha256(private_target.read_bytes()).hexdigest(),
        "synthetic": True,
    }
    with pytest.raises(RuntimeError, match="input_wav_symlink_forbidden"):
        module._validate_fixture_entry(entry, fixture_root=fixture_root)


def test_stt_benchmark_rejects_fixture_path_escape_and_nonfinite_numbers(tmp_path: Path) -> None:
    module = _load_module()
    fixture_root = tmp_path / "fixtures"
    fixture_root.mkdir()
    outside = tmp_path / "outside.wav"
    payload = module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000)
    outside.write_bytes(payload)
    entry = {
        "sample": "escape",
        "file": "../outside.wav",
        "origin": "synthetic",
        "speaker_consent": "synthetic",
        "allowed_purpose": "test",
        "retention": "test",
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo", "manfred", "sprechen"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "synthetic": True,
    }
    with pytest.raises(RuntimeError, match="stt_fixture_path_invalid"):
        module._validate_fixture_entry(entry, fixture_root=fixture_root)

    quality = module._fixture_quality(
        payload=payload,
        expected_text=entry["expected_text"],
        synthetic=False,
        max_duration_seconds=float("nan"),
    )
    assert quality["status"] == "blocked"
    assert "max_audio_duration_invalid" in quality["failed_codes"]
    assert json.dumps(quality, allow_nan=False)


def test_stt_benchmark_required_token_phrases_require_every_lexical_component() -> None:
    module = _load_module()
    spec = {
        "expected_text": "Kommt da noch was oder bist du jetzt stumm?",
        "required_tokens": ["kommt jetzt", "bist du", "stumm"],
        "min_token_f1": 0.1,
        "max_wer": 1.0,
    }

    missing_component = module._score_text("Kommt da noch was oder bist du stumm?", spec)
    complete = module._score_text("Kommt da noch was oder bist du jetzt stumm?", spec)
    empty_contract = module._score_text(spec["expected_text"], {**spec, "required_tokens": []})

    assert missing_component["intent_correct"] is False
    assert missing_component["passed"] is False
    assert complete["intent_correct"] is True
    assert empty_contract["intent_correct"] is False


def test_stt_benchmark_rechecks_review_freshness_immediately_before_any_upload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    bundle = tmp_path / "freshness-recheck"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    receipt_path, review_path, _candidate = _external_candidate_inputs(bundle)
    output = tmp_path / "freshness-recheck.json"
    calls: list[str] = []
    monkeypatch.setattr(module, "_fixture_specs", lambda: [])
    _stub_runtime_probes(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "_review_freshness_failures",
        lambda *_args, **_kwargs: ["ground_truth_review_reviewed_at_stale"],
    )
    for name in ("_run_shadow", "_run_onemin_sample", "_run_full_runtime"):
        monkeypatch.setattr(
            module,
            name,
            lambda *_args, _name=name, **_kwargs: calls.append(_name) or {},
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--output",
            str(output),
            "--no-local-env",
            "--require-production-eligible",
            "--captured-candidate-bundle-dir",
            str(bundle),
            "--captured-candidate-receipt",
            str(receipt_path),
            "--captured-candidate-ground-truth-review",
            str(review_path),
            "--captured-candidate-allow-external-root",
        ],
    )

    exit_code = module.main()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 2
    assert calls == []
    assert report["availability"]["governance_preflight"]["blocked"] is True
    assert "ground_truth_review_reviewed_at_stale" in report["availability"]["governance_preflight"]["failed_codes"]


def test_stt_tracked_fixture_contract_requires_exact_synthetic_and_governed_captured_auth(tmp_path: Path) -> None:
    module = _load_module()
    fixture_root = tmp_path / "fixtures"
    fixture_root.mkdir()
    payload = module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000)
    (fixture_root / "tracked.wav").write_bytes(payload)
    base = {
        "sample": "tracked_contract",
        "file": "tracked.wav",
        "origin": "ignored_by_public_receipt",
        "speaker_consent": "synthetic",
        "allowed_purpose": "test",
        "retention": "test",
        "expected_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "required_tokens": ["hallo manfred", "sprechen"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "language": "de",
        "accent": "Austrian German",
    }

    malformed_synthetic = module._validate_fixture_entry(
        {**base, "synthetic": "true"},
        fixture_root=fixture_root,
    )
    governed_captured = module._validate_fixture_entry(
        {
            **base,
            "synthetic": False,
            "speaker_consent": "operator_attested_for_private_stt_regression",
            "allowed_purpose": "memorial_stt_regression_and_provider_bakeoff",
            "retention": "private_captured_regression_candidate",
            "provider_upload_authorization": {
                "full_runtime": True,
                "shadow": False,
                "onemin_sample": False,
            },
        },
        fixture_root=fixture_root,
    )

    assert "tracked_synthetic_type_invalid" in malformed_synthetic["fixture_quality"]["failed_codes"]
    assert "tracked_provider_upload_authorization_invalid" in malformed_synthetic["fixture_quality"]["failed_codes"]
    assert governed_captured["fixture_quality"]["status"] == "pass"
    assert governed_captured["provider_upload_authorization"] == {
        "full_runtime": True,
        "shadow": False,
        "onemin_sample": False,
    }
    assert "ignored_by_public_receipt" not in str(governed_captured["provenance"])


def test_stt_malformed_tracked_authorization_globally_blocks_provider_calls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    spec = _tracked_spec(module)
    spec["_governance_preflight_failed_codes"] = ["tracked_provider_upload_authorization_invalid"]
    spec["fixture_quality"] = {
        **spec["fixture_quality"],
        "status": "blocked",
        "failed_codes": ["tracked_provider_upload_authorization_invalid"],
    }
    output = tmp_path / "tracked-auth-block.json"
    calls: list[str] = []
    monkeypatch.setattr(module, "_fixture_specs", lambda: [spec])
    _stub_runtime_probes(module, monkeypatch)
    for name in ("_run_shadow", "_run_onemin_sample", "_run_full_runtime"):
        monkeypatch.setattr(
            module,
            name,
            lambda *_args, _name=name, **_kwargs: calls.append(_name) or {},
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--output", str(output), "--no-local-env", "--require-production-eligible"],
    )

    exit_code = module.main()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 2
    assert calls == []
    assert report["availability"]["governance_preflight"]["tracked_fixture_failed_codes"] == [
        "tracked_provider_upload_authorization_invalid"
    ]


def test_stt_benchmark_output_preflight_rejects_unsafe_parent_before_runtime(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    monkeypatch.setattr(
        module,
        "_fixture_specs",
        lambda: (_ for _ in ()).throw(AssertionError("runtime must not start")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--output", str(linked_parent / "report.json"), "--no-local-env"],
    )

    exit_code = module.main()

    assert exit_code == 2
    assert not (real_parent / "report.json").exists()
    stdout = capsys.readouterr().out
    assert "output_parent_unsafe" in stdout


def test_stt_benchmark_provider_exceptions_commit_redacted_blocked_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    output = tmp_path / "provider-exception.json"
    sentinel = "PRIVATE TRANSCRIPT PROVIDER EXCEPTION"
    monkeypatch.setattr(module, "_fixture_specs", lambda: [_tracked_spec(module)])
    _stub_runtime_probes(module, monkeypatch)
    for name in ("_run_shadow", "_run_onemin_sample", "_run_full_runtime"):
        monkeypatch.setattr(
            module,
            name,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(sentinel)),
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--output", str(output), "--no-local-env", "--require-production-eligible"],
    )

    exit_code = module.main()
    rendered = output.read_text(encoding="utf-8")
    report = json.loads(rendered)

    assert exit_code == 2
    assert report["status"] == "blocked"
    assert sentinel not in rendered
    assert all(
        row[provider]["status"] == "error"
        and row[provider]["detail"]["contract_name"] == "ea.memorial_stt_provider_error_detail.v1"
        and "reason" not in row[provider]
        for row in report["rows"]
        for provider in ("shadow", "onemin_sample", "full_runtime")
    )


def test_stt_benchmark_atomic_report_replaces_hardlink_and_availability_drops_carriers(tmp_path: Path) -> None:
    module = _load_module()
    peer = tmp_path / "peer.json"
    peer.write_text('{"peer":"unchanged"}\n', encoding="utf-8")
    output = tmp_path / "benchmark.json"
    output.hardlink_to(peer)
    sentinel = "/home/private/PRIVATE_TRANSCRIPT.env"
    report = module._build_report(
        rows=[],
        availability={
            "shadow_provider": sentinel,
            "provider_env": {"files": [sentinel], "loaded_count": 2},
            "extra_metadata": sentinel,
        },
    )

    module._write_report(output, report, contains_full_text=False)

    rendered = output.read_text(encoding="utf-8")
    assert peer.read_text(encoding="utf-8") == '{"peer":"unchanged"}\n'
    assert sentinel not in rendered
    assert set(report["availability"]) == {"providers", "credential_environment", "governance_preflight"}
    assert all(
        set(row) == {
            "provider",
            "passed_samples",
            "sample_count",
            "scored_samples",
            "intent_correct_samples",
            "avg_token_f1",
            "avg_wer",
            "avg_latency_ms",
            "production_eligible",
        }
        for row in report["provider_ranking"]
    )
    assert not any(".tmp-" in child.name for child in tmp_path.iterdir())


def test_stt_benchmark_precommit_exception_commits_fixed_redacted_receipt(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    output = tmp_path / "precommit-failure.json"
    sentinel = "PRIVATE PRECOMMIT EXCEPTION SENTINEL"
    monkeypatch.setattr(
        module,
        "_fixture_specs",
        lambda: (_ for _ in ()).throw(RuntimeError(sentinel)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--output", str(output), "--no-local-env"],
    )

    exit_code = module.main()
    stdout = capsys.readouterr().out
    rendered = output.read_text(encoding="utf-8")
    report = json.loads(rendered)

    assert exit_code == 2
    assert report == {
        "contract_name": "ea.memorial_stt_provider_benchmark",
        "status": "blocked",
        "failed_codes": ["benchmark_precommit_failed"],
        "stdout_redacted": True,
    }
    assert sentinel not in rendered
    assert sentinel not in stdout
    assert not any(".tmp-" in child.name for child in tmp_path.iterdir())


def test_stt_benchmark_precommit_and_fallback_commit_failure_leave_no_temp_or_exception_text(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    output = tmp_path / "fallback-commit-failure.json"
    sentinel = "PRIVATE FALLBACK COMMIT EXCEPTION SENTINEL"
    monkeypatch.setattr(
        module,
        "_fixture_specs",
        lambda: (_ for _ in ()).throw(RuntimeError(sentinel)),
    )
    monkeypatch.setattr(
        module,
        "_commit_atomic_json_output",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(sentinel)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--output", str(output), "--no-local-env"],
    )

    exit_code = module.main()
    stdout = capsys.readouterr().out

    assert exit_code == 2
    assert not output.exists()
    assert sentinel not in stdout
    assert json.loads(stdout)["failed_codes"] == ["output_commit_failed"]
    assert not any(".tmp-" in child.name for child in tmp_path.iterdir())
