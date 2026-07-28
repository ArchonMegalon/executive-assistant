from __future__ import annotations

import importlib.util
import stat
import sys
import wave
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "compare_memorial_unmixr_clones.py"


def _load_module():
    name = "compare_memorial_unmixr_clones_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_wav(path: Path, *, seconds: float = 0.2) -> bytes:
    sample_rate = 16_000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * int(sample_rate * seconds))
    return path.read_bytes()


def test_transcript_metrics_require_normalized_exact_match() -> None:
    module = _load_module()

    exact = module._transcript_metrics("Klar. Worum geht es?", "klar, worum geht es")
    drift = module._transcript_metrics("Worum geht es?", "Wovon geht es?")

    assert exact["exact_match"] is True
    assert exact["f1"] == 1.0
    assert drift["exact_match"] is False
    assert drift["f1"] < 1.0
    assert drift["missing_tokens"] == ["worum"]


def test_candidate_take_uses_provider_code_pronunciation_and_private_audio(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    wav_bytes = _write_wav(tmp_path / "fixture.wav")
    requests: list[dict[str, object]] = []

    def synthesize(**kwargs):
        requests.append(dict(kwargs))
        return wav_bytes, "audio/wav"

    monkeypatch.setattr(module, "unmixr_synthesize_request", synthesize)
    monkeypatch.setattr(
        module,
        "_apply_memorial_unmixr_postprocess",
        lambda **kwargs: (kwargs["payload"], "audio/wav"),
    )
    monkeypatch.setattr(
        module._OPTIMIZER,
        "_transcribe_audio_bytes",
        lambda *args, **kwargs: {"text": "Klar. Worum geht es?"},
    )
    monkeypatch.setattr(
        module._OPTIMIZER,
        "_wav_metrics_from_bytes",
        lambda payload: {"duration_seconds": 0.2},
    )
    monkeypatch.setattr(
        module._OPTIMIZER,
        "_voice_feature_similarity",
        lambda reference, candidate: 0.8,
    )

    row = module._evaluate_candidate_prompt(
        slug="manfred",
        voice_id="private-provider-voice-id",
        prompt="Klar. Worum geht es?",
        take_index=2,
        combo={
            "speaking_rate": "medium",
            "speaking_pitch": "low",
            "speaking_volume": "high",
        },
        reference_metrics={"duration_seconds": 0.2},
        base_url="http://127.0.0.1:8090",
        timeout_seconds=2.0,
        postprocess_profile="unmixr_raw_preserve",
        feature_only=False,
        lead_in_ms=0,
        tail_silence_ms=0,
        provider_language="de",
        pronunciation_dict={"Klar": "Klaar"},
        audio_output_dir=tmp_path / "private-audio",
        account_slot="UNMIXR_API_KEY_FALLBACK_2",
    )

    assert row["exact_match"] is True
    assert row["take"] == 2
    assert Path(str(row["audio_path"])).is_file()
    assert stat.S_IMODE(Path(str(row["audio_path"])).stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(str(row["audio_path"])).parent.stat().st_mode) == 0o700
    assert "private-provider-voice-id" not in str(row["audio_path"])
    assert requests[0]["lang"] == "de"
    assert requests[0]["pronunciation_dict"] == {"Klar": "Klaar"}
    assert requests[0]["account_slot"] == "UNMIXR_API_KEY_FALLBACK_2"


def test_private_candidate_audio_refuses_symlink_target(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "outside.wav"
    target.write_bytes(b"preserve")
    candidate = tmp_path / "private" / "candidate.wav"
    candidate.parent.mkdir()
    candidate.symlink_to(target)

    with pytest.raises(RuntimeError, match="candidate_audio_path_unsafe"):
        module._write_private_candidate_audio(candidate, b"replacement")

    assert target.read_bytes() == b"preserve"


def test_two_stage_rerenders_only_shortlisted_identities(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    reference = tmp_path / "reference.wav"
    _write_wav(reference)
    monkeypatch.setattr(module, "_reference_path", lambda **kwargs: reference)
    calls: list[dict[str, object]] = []
    feature_rows = [
        {
            "voice_id": "voice-a",
            "speaking_rate": "medium",
            "speaking_pitch": "low",
            "speaking_volume": "high",
            "tts_postprocess_profile": "raw",
            "average_score": 0.9,
        },
        {
            "voice_id": "voice-b",
            "speaking_rate": "low",
            "speaking_pitch": "medium",
            "speaking_volume": "high",
            "tts_postprocess_profile": "soft",
            "average_score": 0.8,
        },
    ]

    def compare(**kwargs):
        calls.append(dict(kwargs))
        if kwargs["feature_only"]:
            return {"rows": feature_rows}
        voice_id = kwargs["voice_ids"][0]
        return {
            "rows": [
                {
                    "voice_id": voice_id,
                    **kwargs["combos"][0],
                    "tts_postprocess_profile": kwargs["postprocess_profiles"][0],
                    "average_score": 0.8,
                    "average_feature_similarity": 0.8,
                    "average_text_f1": 1.0,
                    "quality_gate": {
                        "status": "pass",
                        "exact_take_rate": 1.0,
                    },
                }
            ]
        }

    monkeypatch.setattr(module, "compare_unmixr_clones", compare)

    report = module.compare_unmixr_clones_two_stage(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_ids=["voice-a", "voice-b"],
        prompts=["Worum geht es?"],
        combos=[
            {
                "speaking_rate": "medium",
                "speaking_pitch": "low",
                "speaking_volume": "high",
            },
            {
                "speaking_rate": "low",
                "speaking_pitch": "medium",
                "speaking_volume": "high",
            },
        ],
        postprocess_profiles=["raw", "soft"],
        shortlist_top_k=2,
        takes_per_prompt=3,
        audio_output_dir=tmp_path / "audio",
    )

    assert len(calls) == 3
    assert calls[0]["prompts"] == [module.FEATURE_SCREEN_PROMPT]
    assert calls[0]["takes_per_prompt"] == 1
    for final_call in calls[1:]:
        assert len(final_call["voice_ids"]) == 1
        assert len(final_call["combos"]) == 1
        assert len(final_call["postprocess_profiles"]) == 1
        assert final_call["takes_per_prompt"] == 3
    assert report["rendered_final_candidates"] == 2
    assert report["winner"]["voice_id"] == "voice-a"


def test_comparison_fails_closed_when_one_required_take_drifts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    reference = tmp_path / "reference.wav"
    _write_wav(reference)
    monkeypatch.setattr(module, "_reference_path", lambda **kwargs: reference)
    monkeypatch.setattr(
        module._OPTIMIZER,
        "_wav_metrics_from_bytes",
        lambda payload: {"duration_seconds": 0.2},
    )

    def evaluate(**kwargs):
        exact = kwargs["take_index"] == 1
        return {
            "prompt": kwargs["prompt"],
            "take": kwargs["take_index"],
            "status": "ok",
            "score": 0.9 if exact else 0.7,
            "feature_similarity": 0.8,
            "text_f1": 1.0 if exact else 0.6,
            "duration_seconds": 0.2,
            "exact_match": exact,
        }

    monkeypatch.setattr(module, "_evaluate_candidate_prompt", evaluate)

    report = module.compare_unmixr_clones(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_ids=["voice-a"],
        prompts=["Worum geht es?"],
        combos=[
            {
                "speaking_rate": "medium",
                "speaking_pitch": "low",
                "speaking_volume": "high",
            }
        ],
        postprocess_profiles=["raw"],
        takes_per_prompt=2,
    )

    assert report["winner"]["quality_gate"]["status"] == "fail"
    assert report["recommended_config"] == {}
    assert report["blocked"]["code"] == "unstable_product_phrases"
