from __future__ import annotations

import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_memorial_stt_providers.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("benchmark_memorial_stt_providers", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def test_stt_benchmark_extracts_json_transcript_and_rejects_known_bad_subtitles() -> None:
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

    assert score["actual_text"] == "Untertitel der Amara.org-Community"
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
        "files": [".env"],
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

    assert detail == "onemin_transcribe_http_406:INSUFFICIENT_CREDITS:required_105:available_35"
    assert "Girschele" not in detail
    assert "Family" not in detail


def test_stt_benchmark_sanitizes_provider_error_urls() -> None:
    module = _load_module()

    detail = module._sanitize_provider_error_detail(
        'onemin_transcribe_http_400:{"message":"Failed to analyze media file: https://s3.us-east-1.amazonaws.com/asset.1min.ai/audios/private.wav"}'
    )

    assert "https://" not in detail
    assert "asset.1min.ai" not in detail
    assert "[url]" in detail


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

    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        sample="real_room_retry_candidate",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        speaker_consent="operator_attested_for_private_stt_regression",
        origin="Captured operator Manfred test audio with operator-supplied transcript.",
        allow_external_root=True,
    )

    assert spec["sample"] == "real_room_retry_candidate"
    assert spec["file"] == "[private_bundle]/082347_realtime_audio_turn_generic_fallback_answer/input.wav"
    assert spec["fixture_quality"]["status"] == "pass"
    assert spec["provenance"]["external_bundle"] is True
    assert spec["provenance"]["synthetic"] is False
    assert spec["payload"]


def test_stt_external_captured_candidate_report_stays_redacted(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "candidate"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(module._wav_from_samples([1200] * (16_000 * 3), sample_rate=16_000))
    spec = module._external_captured_candidate_spec(
        bundle_dir=bundle,
        sample="real_room_retry_candidate",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        speaker_consent="operator_attested_for_private_stt_regression",
        origin="Captured operator Manfred test audio with operator-supplied transcript.",
        allow_external_root=True,
    )
    row = {
        "sample": spec["sample"],
        "variant": "captured",
        "fixture": spec["file"],
        "fixture_sha256": spec["fixture_sha256"],
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

    report = module._build_report(rows=[], availability={"cartesia_configured": False})

    assert report["generated_by"] == "scripts/benchmark_memorial_stt_providers.py"
    assert report["generated_at"]
    assert report["source_git_head"] == "HEAD"
    assert report["head_semantics"] == "source_state"
    assert report["source_state_fingerprint"] == "worktree-fingerprint"
    assert (
        report["source_state_fingerprint_semantics"]
        == "worktree_source_files_sha256_excluding_generated_only_paths"
    )


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
