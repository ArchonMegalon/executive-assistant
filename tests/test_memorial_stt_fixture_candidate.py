from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import math
import struct
import sys
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "materialize_memorial_stt_fixture_candidate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("materialize_memorial_stt_fixture_candidate", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _wav_bytes(*, duration_seconds: float = 3.0) -> bytes:
    sample_rate = 16_000
    total_frames = max(1, int(sample_rate * duration_seconds))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for index in range(total_frames):
            sample = int(9000 * math.sin(2.0 * math.pi * 260 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def _stereo_wav_bytes(*, duration_seconds: float = 3.0) -> bytes:
    sample_rate = 16_000
    total_frames = max(1, int(sample_rate * duration_seconds))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<hh", 1200, 1200) for _ in range(total_frames)))
    return buffer.getvalue()


def _open_ended_wav_bytes(*, duration_seconds: float = 3.0) -> bytes:
    payload = bytearray(_wav_bytes(duration_seconds=duration_seconds))
    payload[4:8] = (0xFFFFFFFF).to_bytes(4, "little")
    data_offset = bytes(payload).find(b"data")
    assert data_offset > 0
    payload[data_offset + 4:data_offset + 8] = (0xFFFFFFFF).to_bytes(4, "little")
    return bytes(payload)


def _ground_truth_review(
    bundle: Path,
    *,
    sample: str,
    expected_text: str,
    required_tokens: list[str],
    speaker_consent: str = "operator_attested_for_private_stt_regression",
    allowed_purpose: str = "memorial_stt_regression_and_provider_bakeoff",
    retention: str = "private_repo_captured_regression_fixture",
    provider_upload_authorization: dict[str, bool] | None = None,
    language: str = "de",
    accent: str = "Austrian German",
    reviewed_at: str | None = None,
) -> Path:
    audio_path = bundle / "input.wav"
    audio_sha256 = hashlib.sha256(audio_path.read_bytes()).hexdigest() if audio_path.is_file() else ""
    path = bundle.parent / f"{bundle.name}.{sample}.ground-truth-review.json"
    path.write_text(
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
                "required_tokens": required_tokens,
                "speaker_consent": speaker_consent,
                "allowed_purpose": allowed_purpose,
                "retention": retention,
                "language": language,
                "accent": accent,
                "provider_upload_authorization": provider_upload_authorization
                if provider_upload_authorization is not None
                else {
                    "full_runtime": True,
                    "shadow": False,
                    "onemin_sample": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _build_candidate(
    module,
    bundle: Path,
    *,
    sample: str,
    expected_text: str,
    required_tokens: list[str],
    speaker_consent: str = "operator_attested_for_private_stt_regression",
    allowed_purpose: str = "memorial_stt_regression_and_provider_bakeoff",
    retention: str = "private_repo_captured_regression_fixture",
    provider_upload_authorization: dict[str, bool] | None = None,
    language: str = "de",
    accent: str = "Austrian German",
    origin: str = "captured_operator_manfred_memorial_stt_error_bundle",
    fixture_file: str | None = None,
    reviewed_at: str | None = None,
    **kwargs,
):
    review = _ground_truth_review(
        bundle,
        sample=sample,
        expected_text=expected_text,
        required_tokens=required_tokens,
        speaker_consent=speaker_consent,
        allowed_purpose=allowed_purpose,
        retention=retention,
        provider_upload_authorization=provider_upload_authorization,
        language=language,
        accent=accent,
        reviewed_at=reviewed_at,
    )
    return module.build_fixture_candidate(
        bundle_dir=bundle,
        ground_truth_review_path=review,
        origin=origin,
        fixture_file=fixture_file if fixture_file is not None else f"{sample}_captured.wav",
        **kwargs,
    )


def test_memorial_stt_fixture_candidate_redacts_text_and_passes_valid_audio(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "082347_realtime_audio_turn_generic_fallback_answer"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.2))
    (bundle / "error.json").write_text(json.dumps({"event_type": "realtime_audio_turn", "reason": "generic"}), encoding="utf-8")

    payload = _build_candidate(
        module,
        bundle,
        sample="real_room_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
    )

    assert payload["status"] == "pass"
    assert payload["candidate_scope"] == "audio_quality_provenance_and_bound_ground_truth"
    assert payload["promotion_gate"] == {
        "status": "pending_captured_candidate_benchmark",
        "required_receipt": ".codex-studio/published/memorial_stt_provider_benchmark_captured_candidate.generated.json",
        "required_rule": "captured candidate must pass full-runtime STT scoring against operator-confirmed ground truth before fixture-manifest promotion",
        "may_update_fixture_manifest": False,
        "next_action": "run_captured_candidate_benchmark_before_fixture_manifest",
    }
    assert payload["audio"]["duration_seconds"] == 3.2
    entry = payload["candidate_manifest_entry"]
    assert entry["synthetic"] is False
    assert entry["expected_text"]["text_redacted"] is True
    assert "text" not in entry["expected_text"]
    assert entry["required_tokens"][0]["text_sha256"]
    assert payload["contract_version"] == 3
    assert payload["generated_at"]
    assert payload["generated_by"] == "scripts/materialize_memorial_stt_fixture_candidate.py"
    assert payload["source_git_head"]
    assert payload["source_state_fingerprint"]
    binding = payload["candidate_binding"]
    assert binding["contract_name"] == "ea.memorial_stt_fixture_candidate_binding.v2"
    assert binding["sha256"] == module._canonical_sha256(binding["payload"])
    assert binding["payload"]["audio_sha256"] == payload["audio"]["sha256"]
    assert binding["payload"]["expected_text_sha256"] == entry["expected_text"]["text_sha256"]
    assert binding["payload"]["status"] == "pass"
    assert binding["payload"]["failed_codes"] == []
    assert binding["payload"]["provider_upload_authorization"] == {
        "full_runtime": True,
        "shadow": False,
        "onemin_sample": False,
    }


def test_memorial_stt_fixture_candidate_requires_consent_and_plausible_duration(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "short"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=0.2))

    payload = _build_candidate(
        module,
        bundle,
        sample="short_retry",
        expected_text="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        required_tokens=["hallo", "manfred", "sprechen"],
        speaker_consent="",
        allow_external_root=True,
    )

    assert payload["status"] == "blocked"
    assert "ground_truth_review_speaker_consent_missing" in payload["failed_codes"]
    assert "audio_too_short_for_expected_text" in payload["failed_codes"]


def test_memorial_stt_fixture_candidate_blocks_audio_over_size_cap(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "oversized"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))

    payload = _build_candidate(
        module,
        bundle,
        sample="oversized_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
        max_audio_bytes=64,
    )

    assert payload["status"] == "blocked"
    assert "input_wav_too_large" in payload["failed_codes"]
    assert payload["audio"]["bytes"] == 0
    assert payload["audio"]["max_bytes"] == 64


def test_memorial_stt_fixture_candidate_blocks_non_wav_payload(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "not-wav"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(b"not actually a wav file")

    payload = _build_candidate(
        module,
        bundle,
        sample="not_wav_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
    )

    assert payload["status"] == "blocked"
    assert "audio_not_wav" in payload["failed_codes"]
    assert "audio_duration_missing" in payload["failed_codes"]


def test_memorial_stt_fixture_candidate_blocks_implausible_duration() -> None:
    module = _load_module()

    quality = module._fixture_quality(
        payload=_wav_bytes(duration_seconds=3.0),
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        max_duration_seconds=1.0,
    )

    assert quality["status"] == "blocked"
    assert "audio_duration_implausible" in quality["failed_codes"]


def test_memorial_stt_fixture_candidate_accepts_finite_streaming_wav_header(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "streaming-wav"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_open_ended_wav_bytes(duration_seconds=3.0))

    payload = _build_candidate(
        module,
        bundle,
        sample="streaming_wav_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
    )

    assert payload["status"] == "pass"
    assert payload["audio"]["duration_seconds"] == 3.0


def test_memorial_stt_fixture_candidate_rejects_external_bundle_by_default(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))

    payload = _build_candidate(
        module,
        bundle,
        sample="real_room_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
    )

    assert payload["status"] == "blocked"
    assert "bundle_not_under_memorial_stt_error_root" in payload["failed_codes"]


def test_memorial_stt_fixture_candidate_accepts_configured_bundle_root(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "private-stt-errors"
    bundle = root / "manfred" / "2026" / "06" / "19" / "captured"
    bundle.mkdir(parents=True)
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))

    payload = _build_candidate(
        module,
        bundle,
        bundle_root=root,
        sample="real_room_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
    )

    assert payload["status"] == "pass"
    assert payload["bundle"]["root"] == "[memorial_stt_error_root]"


def test_memorial_stt_fixture_candidate_defaults_can_be_env_configured(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    configured_root = tmp_path / "configured-stt-errors"
    configured_output = tmp_path / "candidate.json"
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(configured_root))
    monkeypatch.setenv("EA_MEMORIAL_STT_FIXTURE_CANDIDATE_OUTPUT", str(configured_output))
    monkeypatch.setenv("EA_MEMORIAL_STT_FIXTURE_CANDIDATE_MAX_AUDIO_BYTES", "12345")
    monkeypatch.setenv("EA_MEMORIAL_STT_FIXTURE_CANDIDATE_MAX_AUDIO_SECONDS", "67.5")

    assert module._default_bundle_root() == configured_root
    assert module._default_output() == configured_output
    assert module._default_max_audio_bytes() == 12345
    assert module._default_max_audio_duration_seconds() == 67.5


def test_memorial_stt_fixture_candidate_requires_private_0600_non_symlink_review(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "private-review"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))
    review = _ground_truth_review(
        bundle,
        sample="private_review",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
    )
    review.chmod(0o644)

    mode_blocked = module.build_fixture_candidate(
        bundle_dir=bundle,
        ground_truth_review_path=review,
        origin="captured_operator_manfred_memorial_stt_error_bundle",
        fixture_file="private_review.wav",
        allow_external_root=True,
    )

    assert mode_blocked["status"] == "blocked"
    assert "ground_truth_review_mode_must_be_0600" in mode_blocked["failed_codes"]

    review.chmod(0o600)
    linked_review = tmp_path / "linked-review.json"
    linked_review.symlink_to(review)
    symlink_blocked = module.build_fixture_candidate(
        bundle_dir=bundle,
        ground_truth_review_path=linked_review,
        origin="captured_operator_manfred_memorial_stt_error_bundle",
        fixture_file="private_review.wav",
        allow_external_root=True,
    )

    assert symlink_blocked["status"] == "blocked"
    assert "ground_truth_review_symlink_forbidden" in symlink_blocked["failed_codes"]


def test_memorial_stt_fixture_candidate_binds_review_to_exact_audio(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "audio-binding"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))
    review = _ground_truth_review(
        bundle,
        sample="audio_binding",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
    )
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.2))

    payload = module.build_fixture_candidate(
        bundle_dir=bundle,
        ground_truth_review_path=review,
        origin="captured_operator_manfred_memorial_stt_error_bundle",
        fixture_file="audio_binding.wav",
        allow_external_root=True,
    )

    assert payload["status"] == "blocked"
    assert "ground_truth_review_audio_sha256_mismatch" in payload["failed_codes"]


def test_memorial_stt_fixture_candidate_full_text_refuses_repo_and_stdout_is_redacted(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "full-text"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))
    payload = _build_candidate(
        module,
        bundle,
        sample="full_text",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
        text_mode="full",
    )

    assert payload["candidate_manifest_entry"]["expected_text"]["text"].startswith("Kommt")
    stdout_payload = module._redacted_candidate_for_stdout(payload)
    assert stdout_payload["stdout_redacted"] is True
    assert "text" not in stdout_payload["candidate_manifest_entry"]["expected_text"]
    with pytest.raises(RuntimeError, match="full_text_repo_output_forbidden"):
        module._write_receipt(ROOT / ".candidate-full-output-test.json", payload, contains_full_text=True)

    external_output = tmp_path / "private-candidate.json"
    module._write_receipt(external_output, payload, contains_full_text=True)
    assert external_output.stat().st_mode & 0o777 == 0o600
    assert "Kommt da noch was" in external_output.read_text(encoding="utf-8")


def test_memorial_stt_fixture_candidate_cli_full_text_stdout_remains_redacted(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    bundle = tmp_path / "cli-full"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))
    review = _ground_truth_review(
        bundle,
        sample="cli_full",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
    )
    output = tmp_path / "cli-full-candidate.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--bundle-dir",
            str(bundle),
            "--ground-truth-review",
            str(review),
            "--allow-external-root",
            "--text-mode",
            "full",
            "--output",
            str(output),
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    assert "Kommt da noch was" in output.read_text(encoding="utf-8")
    stdout = capsys.readouterr().out
    assert "Kommt da noch was" not in stdout
    assert '"stdout_redacted": true' in stdout


def test_memorial_stt_fixture_candidate_requires_exact_consent_purpose_retention_and_upload_authorization(
    tmp_path: Path,
) -> None:
    module = _load_module()
    bundle = tmp_path / "governed-review"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))
    common = {
        "sample": "governed_review",
        "expected_text": "Kommt da noch was oder bist du jetzt stumm?",
        "required_tokens": ["kommt", "stumm"],
        "allow_external_root": True,
    }

    denied = _build_candidate(module, bundle, speaker_consent="denied", **common)
    local_only = _build_candidate(module, bundle, allowed_purpose="local_only", **common)
    ungoverned_retention = _build_candidate(module, bundle, retention="forever", **common)
    missing_lane = _build_candidate(
        module,
        bundle,
        provider_upload_authorization={"full_runtime": True, "shadow": False},
        **common,
    )
    no_primary_upload = _build_candidate(
        module,
        bundle,
        provider_upload_authorization={
            "full_runtime": False,
            "shadow": False,
            "onemin_sample": False,
        },
        **common,
    )

    assert "ground_truth_review_speaker_consent_invalid" in denied["failed_codes"]
    assert "ground_truth_review_allowed_purpose_invalid" in local_only["failed_codes"]
    assert "ground_truth_review_retention_invalid" in ungoverned_retention["failed_codes"]
    assert "ground_truth_review_provider_upload_authorization_invalid" in missing_lane["failed_codes"]
    assert "ground_truth_review_full_runtime_upload_not_authorized" in no_primary_upload["failed_codes"]
    assert all(
        payload["status"] == "blocked"
        for payload in (denied, local_only, ungoverned_retention, missing_lane, no_primary_upload)
    )


def test_memorial_stt_fixture_candidate_rejects_reserved_and_unsafe_sample_names(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "sample-policy"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))

    reserved = _build_candidate(
        module,
        bundle,
        sample="technical_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
    )
    unsafe = _build_candidate(
        module,
        bundle,
        sample="Transcript text with spaces",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
    )

    assert "candidate_sample_reserved" in reserved["failed_codes"]
    assert "candidate_sample_invalid" in unsafe["failed_codes"]


def test_memorial_stt_fixture_candidate_redacts_arbitrary_private_error_metadata(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "private-error-metadata"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))
    sentinel = "Kommt da noch was oder bist du jetzt stumm PRIVATE_SENTINEL"
    (bundle / "error.json").write_text(
        json.dumps({"event_type": sentinel, "reason": sentinel}),
        encoding="utf-8",
    )

    payload = _build_candidate(
        module,
        bundle,
        sample="metadata_redaction",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
    )

    assert sentinel not in str(payload)
    assert payload["bundle"]["event_type_code"] == "other"
    assert payload["bundle"]["reason_code"] == "other"
    assert len(payload["bundle"]["reason_sha256"]) == 64


def test_memorial_stt_fixture_candidate_requires_pcm16_mono_audio(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "stereo"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_stereo_wav_bytes(duration_seconds=3.0))

    payload = _build_candidate(
        module,
        bundle,
        sample="stereo_candidate",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
    )

    assert payload["status"] == "blocked"
    assert "audio_channels_not_mono" in payload["failed_codes"]


def test_memorial_stt_fixture_candidate_rejects_symlinked_audio_snapshot(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "symlinked-audio"
    bundle.mkdir()
    target = tmp_path / "private-target.wav"
    target.write_bytes(_wav_bytes(duration_seconds=3.0))
    (bundle / "input.wav").symlink_to(target)

    payload = _build_candidate(
        module,
        bundle,
        sample="symlinked_audio",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
    )

    assert payload["status"] == "blocked"
    assert "input_wav_symlink_forbidden" in payload["failed_codes"]
    assert payload["audio"]["bytes"] == 0


def test_memorial_stt_fixture_candidate_never_copies_unapproved_public_field_sentinels(tmp_path: Path) -> None:
    module = _load_module()
    sentinel = "PRIVATE TRANSCRIPT SENTINEL"
    bundle = tmp_path / sentinel
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))

    payload = _build_candidate(
        module,
        bundle,
        sample=sentinel,
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        language=sentinel,
        accent=sentinel,
        origin=sentinel,
        fixture_file=f"{sentinel}.wav",
        allow_external_root=True,
    )

    assert payload["status"] == "blocked"
    assert sentinel not in str(payload)
    assert {
        "bundle_id_invalid",
        "candidate_sample_invalid",
        "fixture_file_invalid",
        "candidate_origin_invalid",
        "ground_truth_review_language_invalid",
        "ground_truth_review_accent_invalid",
    } <= set(payload["failed_codes"])


@pytest.mark.parametrize("invalid_max", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0])
def test_memorial_stt_fixture_candidate_rejects_nonfinite_or_nonpositive_duration_ceiling(
    tmp_path: Path,
    invalid_max: float,
) -> None:
    module = _load_module()
    bundle = tmp_path / "invalid-max"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))

    payload = _build_candidate(
        module,
        bundle,
        sample="invalid_max",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        allow_external_root=True,
        max_audio_duration_seconds=invalid_max,
    )

    assert payload["status"] == "blocked"
    assert "max_audio_duration_invalid" in payload["failed_codes"]
    assert "NaN" not in json.dumps(payload, allow_nan=False)


def test_memorial_stt_fixture_candidate_rejects_raw_schema_coercion_and_invalid_token_phrases(
    tmp_path: Path,
) -> None:
    module = _load_module()
    bundle = tmp_path / "strict-review-schema"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))
    review = _ground_truth_review(
        bundle,
        sample="strict_review_schema",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
    )
    raw = json.loads(review.read_text(encoding="utf-8"))
    raw["status"] = 1
    raw["required_tokens"] = ["kommt niemals", "!!!", 7]
    raw["provider_upload_authorization"]["shadow"] = 1
    raw["unexpected"] = "PRIVATE TRANSCRIPT SENTINEL"
    review.write_text(json.dumps(raw), encoding="utf-8")
    review.chmod(0o600)

    payload = module.build_fixture_candidate(
        bundle_dir=bundle,
        ground_truth_review_path=review,
        origin="captured_operator_manfred_memorial_stt_error_bundle",
        fixture_file="strict_review_schema_captured.wav",
        allow_external_root=True,
    )

    assert payload["status"] == "blocked"
    assert {
        "ground_truth_review_status_type_invalid",
        "ground_truth_review_required_token_not_in_expected_text:0",
        "ground_truth_review_required_token_lexical_tokens_missing:1",
        "ground_truth_review_required_token_type_invalid:2",
        "ground_truth_review_provider_upload_authorization_type_invalid",
        "ground_truth_review_unknown_fields",
    } <= set(payload["failed_codes"])
    assert "PRIVATE TRANSCRIPT SENTINEL" not in str(payload)


def test_memorial_stt_fixture_candidate_enforces_deterministic_review_freshness(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "review-freshness"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))
    reference = datetime(2026, 7, 12, 3, 0, tzinfo=UTC)

    stale = _build_candidate(
        module,
        bundle,
        sample="review_freshness",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        reviewed_at=(reference - timedelta(hours=72, seconds=1)).isoformat().replace("+00:00", "Z"),
        review_now=reference,
        allow_external_root=True,
    )
    future = _build_candidate(
        module,
        bundle,
        sample="review_freshness",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        reviewed_at=(reference + timedelta(minutes=5, seconds=1)).isoformat().replace("+00:00", "Z"),
        review_now=reference,
        allow_external_root=True,
    )
    boundary = _build_candidate(
        module,
        bundle,
        sample="review_freshness",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        reviewed_at=(reference - timedelta(hours=72)).isoformat().replace("+00:00", "Z"),
        review_now=reference,
        allow_external_root=True,
    )

    assert "ground_truth_review_reviewed_at_stale" in stale["failed_codes"]
    assert "ground_truth_review_reviewed_at_future" in future["failed_codes"]
    assert boundary["status"] == "pass"


def test_memorial_stt_fixture_candidate_atomic_writer_replaces_hardlink_without_touching_peer(
    tmp_path: Path,
) -> None:
    module = _load_module()
    peer = tmp_path / "peer.json"
    peer.write_text('{"peer":"unchanged"}\n', encoding="utf-8")
    output = tmp_path / "candidate.json"
    output.hardlink_to(peer)
    original_inode = peer.stat().st_ino

    module._write_receipt(output, {"status": "pass"}, contains_full_text=False)

    assert peer.read_text(encoding="utf-8") == '{"peer":"unchanged"}\n'
    assert output.stat().st_ino != original_inode
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "pass"}
    assert not any(".tmp-" in child.name for child in tmp_path.iterdir())


def test_memorial_stt_fixture_candidate_atomic_writer_rejects_symlinked_parent_and_target(
    tmp_path: Path,
) -> None:
    module = _load_module()
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(RuntimeError, match="output_parent_unsafe"):
        module._write_receipt(linked_parent / "candidate.json", {"status": "pass"}, contains_full_text=False)

    peer = tmp_path / "peer.json"
    peer.write_text("unchanged", encoding="utf-8")
    linked_target = tmp_path / "linked-target.json"
    linked_target.symlink_to(peer)
    with pytest.raises(RuntimeError, match="output_target_unsafe"):
        module._write_receipt(linked_target, {"status": "pass"}, contains_full_text=False)
    assert peer.read_text(encoding="utf-8") == "unchanged"


def test_memorial_stt_private_review_rejects_hardlink_and_owner_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    in_repo_review = repo_root / "private-review.json"
    in_repo_review.write_text("{}", encoding="utf-8")
    in_repo_review.chmod(0o600)
    outside_hardlink = tmp_path / "outside-review.json"
    outside_hardlink.hardlink_to(in_repo_review)
    monkeypatch.setattr(module, "ROOT", repo_root)

    _review, hardlink_failures = module._load_private_ground_truth_review(outside_hardlink)

    assert hardlink_failures == ["ground_truth_review_link_count_must_be_one"]

    owner_review = tmp_path / "owner-review.json"
    owner_review.write_text("{}", encoding="utf-8")
    owner_review.chmod(0o600)
    actual_owner = owner_review.stat().st_uid
    monkeypatch.setattr(module.os, "geteuid", lambda: actual_owner + 1)

    _review, owner_failures = module._load_private_ground_truth_review(owner_review)

    assert owner_failures == ["ground_truth_review_owner_must_match_euid"]


def test_memorial_stt_private_review_rejects_intermediate_symlink(
    tmp_path: Path,
) -> None:
    module = _load_module()
    real_parent = tmp_path / "real-parent"
    nested_parent = real_parent / "nested"
    nested_parent.mkdir(parents=True)
    review = nested_parent / "review.json"
    review.write_text("{}", encoding="utf-8")
    review.chmod(0o600)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    _review, failures = module._load_private_ground_truth_review(
        linked_parent / "nested" / "review.json"
    )

    assert failures == ["ground_truth_review_symlink_forbidden"]


def test_memorial_stt_atomic_writer_holds_opened_parent_across_intermediate_symlink_race(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    safe_root = tmp_path / "safe-root"
    intermediate = safe_root / "intermediate"
    original_leaf = intermediate / "leaf"
    original_leaf.mkdir(parents=True)
    moved_intermediate = safe_root / "moved-intermediate"
    repo_root = tmp_path / "repo"
    redirected_leaf = repo_root / "leaf"
    redirected_leaf.mkdir(parents=True)
    output = original_leaf / "candidate.json"
    original_open = module.os.open
    raced = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal raced
        descriptor = original_open(path, flags, *args, **kwargs)
        if path == "intermediate" and kwargs.get("dir_fd") is not None and not raced:
            raced = True
            intermediate.rename(moved_intermediate)
            intermediate.symlink_to(repo_root, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(module.os, "open", racing_open)
    reservation = module._prepare_atomic_json_output(
        output,
        contains_full_text=True,
        repo_root=repo_root,
    )
    try:
        module._commit_atomic_json_output(reservation, {"private": "full text"})
    finally:
        module._abort_atomic_json_output(reservation)

    assert raced is True
    assert not (redirected_leaf / "candidate.json").exists()
    assert json.loads((moved_intermediate / "leaf" / "candidate.json").read_text(encoding="utf-8")) == {
        "private": "full text"
    }


def test_memorial_stt_full_text_commit_rejects_opened_parent_moved_into_repo(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    external_parent = tmp_path / "external-parent"
    external_parent.mkdir()
    reservation = module._prepare_atomic_json_output(
        external_parent / "candidate.json",
        contains_full_text=True,
        repo_root=repo_root,
    )
    redirected_parent = repo_root / "redirected-parent"
    external_parent.rename(redirected_parent)

    try:
        with pytest.raises(RuntimeError, match="full_text_repo_output_forbidden"):
            module._commit_atomic_json_output(reservation, {"private": "PRIVATE TRANSCRIPT SENTINEL"})
    finally:
        module._abort_atomic_json_output(reservation)

    assert not (redirected_parent / "candidate.json").exists()
    assert not any(".tmp-" in child.name for child in redirected_parent.iterdir())


def test_memorial_stt_fixture_candidate_cli_redacts_commit_exception(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    bundle = tmp_path / "cli-commit-failure"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))
    review = _ground_truth_review(
        bundle,
        sample="cli_commit_failure",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
    )
    output = tmp_path / "candidate.json"
    sentinel = "PRIVATE COMMIT EXCEPTION SENTINEL"
    monkeypatch.setattr(
        module,
        "_commit_atomic_json_output",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(sentinel)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--bundle-dir",
            str(bundle),
            "--ground-truth-review",
            str(review),
            "--allow-external-root",
            "--output",
            str(output),
        ],
    )

    exit_code = module.main()
    stdout = capsys.readouterr().out

    assert exit_code == 2
    assert not output.exists()
    assert sentinel not in stdout
    assert json.loads(stdout)["failed_codes"] == ["output_commit_failed"]
    assert not any(".tmp-" in child.name for child in tmp_path.iterdir())
