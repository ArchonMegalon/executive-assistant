from __future__ import annotations

import importlib.util
import io
import json
import math
import struct
import wave
from pathlib import Path


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


def _open_ended_wav_bytes(*, duration_seconds: float = 3.0) -> bytes:
    payload = bytearray(_wav_bytes(duration_seconds=duration_seconds))
    payload[4:8] = (0xFFFFFFFF).to_bytes(4, "little")
    data_offset = bytes(payload).find(b"data")
    assert data_offset > 0
    payload[data_offset + 4:data_offset + 8] = (0xFFFFFFFF).to_bytes(4, "little")
    return bytes(payload)


def test_memorial_stt_fixture_candidate_redacts_text_and_passes_valid_audio(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "082347_realtime_audio_turn_generic_fallback_answer"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.2))
    (bundle / "error.json").write_text(json.dumps({"event_type": "realtime_audio_turn", "reason": "generic"}), encoding="utf-8")

    payload = module.build_fixture_candidate(
        bundle_dir=bundle,
        sample="real_room_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        speaker_consent="operator_attested_for_private_stt_regression",
        origin="Captured operator Manfred test audio with operator-supplied transcript.",
        allowed_purpose="memorial_stt_regression_and_provider_bakeoff",
        retention="private_repo_captured_regression_fixture",
        accent="Austrian German",
        fixture_file="real_room_retry_captured.wav",
        allow_external_root=True,
    )

    assert payload["status"] == "pass"
    assert payload["candidate_scope"] == "audio_quality_and_provenance_only"
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


def test_memorial_stt_fixture_candidate_requires_consent_and_plausible_duration(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "short"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=0.2))

    payload = module.build_fixture_candidate(
        bundle_dir=bundle,
        sample="short_retry",
        expected_text="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        required_tokens=["hallo", "manfred", "sprechen"],
        speaker_consent="",
        origin="Captured operator Manfred test audio with operator-supplied transcript.",
        allowed_purpose="memorial_stt_regression_and_provider_bakeoff",
        retention="private_repo_captured_regression_fixture",
        accent="Austrian German",
        fixture_file="short_retry_captured.wav",
        allow_external_root=True,
    )

    assert payload["status"] == "blocked"
    assert "speaker_consent_missing" in payload["failed_codes"]
    assert "audio_too_short_for_expected_text" in payload["failed_codes"]


def test_memorial_stt_fixture_candidate_blocks_audio_over_size_cap(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "oversized"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))

    payload = module.build_fixture_candidate(
        bundle_dir=bundle,
        sample="oversized_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        speaker_consent="operator_attested_for_private_stt_regression",
        origin="Captured operator Manfred test audio with operator-supplied transcript.",
        allowed_purpose="memorial_stt_regression_and_provider_bakeoff",
        retention="private_repo_captured_regression_fixture",
        accent="Austrian German",
        fixture_file="oversized_retry_captured.wav",
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

    payload = module.build_fixture_candidate(
        bundle_dir=bundle,
        sample="not_wav_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        speaker_consent="operator_attested_for_private_stt_regression",
        origin="Captured operator Manfred test audio with operator-supplied transcript.",
        allowed_purpose="memorial_stt_regression_and_provider_bakeoff",
        retention="private_repo_captured_regression_fixture",
        accent="Austrian German",
        fixture_file="not_wav_retry_captured.wav",
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

    payload = module.build_fixture_candidate(
        bundle_dir=bundle,
        sample="streaming_wav_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        speaker_consent="operator_attested_for_private_stt_regression",
        origin="Captured operator Manfred test audio with operator-supplied transcript.",
        allowed_purpose="memorial_stt_regression_and_provider_bakeoff",
        retention="private_repo_captured_regression_fixture",
        accent="Austrian German",
        fixture_file="streaming_wav_retry_captured.wav",
        allow_external_root=True,
    )

    assert payload["status"] == "pass"
    assert payload["audio"]["duration_seconds"] == 3.0


def test_memorial_stt_fixture_candidate_rejects_external_bundle_by_default(tmp_path: Path) -> None:
    module = _load_module()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))

    payload = module.build_fixture_candidate(
        bundle_dir=bundle,
        sample="real_room_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        speaker_consent="operator_attested_for_private_stt_regression",
        origin="Captured operator Manfred test audio with operator-supplied transcript.",
        allowed_purpose="memorial_stt_regression_and_provider_bakeoff",
        retention="private_repo_captured_regression_fixture",
        accent="Austrian German",
        fixture_file="real_room_retry_captured.wav",
    )

    assert payload["status"] == "blocked"
    assert "bundle_not_under_memorial_stt_error_root" in payload["failed_codes"]


def test_memorial_stt_fixture_candidate_accepts_configured_bundle_root(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "private-stt-errors"
    bundle = root / "manfred" / "2026" / "06" / "19" / "captured"
    bundle.mkdir(parents=True)
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=3.0))

    payload = module.build_fixture_candidate(
        bundle_dir=bundle,
        bundle_root=root,
        sample="real_room_retry",
        expected_text="Kommt da noch was oder bist du jetzt stumm?",
        required_tokens=["kommt", "stumm"],
        speaker_consent="operator_attested_for_private_stt_regression",
        origin="Captured operator Manfred test audio with operator-supplied transcript.",
        allowed_purpose="memorial_stt_regression_and_provider_bakeoff",
        retention="private_repo_captured_regression_fixture",
        accent="Austrian German",
        fixture_file="real_room_retry_captured.wav",
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
