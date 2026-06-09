from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path


SCRIPT_PATH = Path("/docker/EA/ea/scripts/compare_memorial_unmixr_clones.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("compare_memorial_unmixr_clones", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_compare_unmixr_clones_prefers_highest_average_score(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    optimization_dir = tmp_path / "optimization"
    candidates_dir = optimization_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    (candidates_dir / "oSQ9FhFc4YI-01440s-28.wav").write_bytes(b"ref")

    monkeypatch.setattr(module, "_optimization_root", lambda *, slug: optimization_dir)
    monkeypatch.setattr(module._OPTIMIZER, "_wav_metrics_from_bytes", lambda payload: {"payload_size": len(payload)})
    monkeypatch.setattr(
        module._OPTIMIZER,
        "_voice_feature_similarity",
        lambda ref, cand: 0.82 if cand["payload_size"] == 20 else 0.61,
    )
    monkeypatch.setattr(module, "_apply_memorial_unmixr_postprocess", lambda **kwargs: (kwargs["payload"], "audio/wav"))
    monkeypatch.setattr(module, "_convert_audio_to_wav", lambda *, payload, content_type: payload)
    monkeypatch.setattr(module, "_wav_duration_seconds", lambda payload: 1.5 if len(payload) == 20 else 2.2)
    monkeypatch.setattr(
        module._OPTIMIZER,
        "_transcribe_audio_bytes",
        lambda payload, *, content_type, slug, base_url: {"text": "Ja. Ich bin da." if len(payload) == 20 else "Ja."},
    )
    monkeypatch.setattr(
        module,
        "unmixr_synthesize_request",
        lambda *, text, voice_id, lang, speaking_rate=None, speaking_pitch=None, speaking_volume=None: (
            b"x" * (20 if voice_id == "winner-voice" else 10),
            "audio/wav",
        ),
    )

    report = module.compare_unmixr_clones(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_ids=["winner-voice", "other-voice"],
        prompts=["Ja. Ich bin da."],
        combos=[{"speaking_rate": "medium", "speaking_pitch": "low", "speaking_volume": "high"}],
    )

    assert report["winner"]["voice_id"] == "winner-voice"
    assert report["recommended_config"]["tts_plugin_voice_id"] == "winner-voice"
    assert report["recommended_config"]["unmixr_speaking_rate"] == "medium"
    assert report["recommended_config"]["unmixr_speaking_pitch"] == "low"
    assert report["recommended_config"]["unmixr_speaking_volume"] == "high"
    assert report["recommended_config"]["tts_postprocess_profile"] == ""


def test_existing_candidates_reads_report(tmp_path: Path) -> None:
    module = _load_module()

    optimization_dir = tmp_path / "optimization"
    optimization_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "rows": [
            {"voice_id": "abc"},
            {"voice_id": "def"},
            {"voice_id": "abc"},
        ]
    }
    (optimization_dir / "unmixr_existing_clone_comparison_report.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    candidates = module._existing_candidates(slug="manfred") if False else None
    # patch after module load to keep test local to tmpdir
    module._optimization_root = lambda *, slug: optimization_dir
    candidates = module._existing_candidates(slug="manfred")
    assert candidates == ["abc", "def"]


def test_prosody_combos_exhaustive_covers_full_grid() -> None:
    module = _load_module()

    combos = module._prosody_combos(exhaustive=True)

    assert len(combos) == 27
    assert {"speaking_rate": "low", "speaking_pitch": "low", "speaking_volume": "low"} in combos
    assert {"speaking_rate": "high", "speaking_pitch": "high", "speaking_volume": "high"} in combos


def test_compare_unmixr_clones_supports_resume_and_max_rows(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    optimization_dir = tmp_path / "optimization"
    candidates_dir = optimization_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    (candidates_dir / "oSQ9FhFc4YI-01440s-28.wav").write_bytes(b"ref")
    monkeypatch.setattr(module, "_optimization_root", lambda *, slug: optimization_dir)
    monkeypatch.setattr(module._OPTIMIZER, "_wav_metrics_from_bytes", lambda payload: {"payload_size": len(payload)})
    monkeypatch.setattr(module._OPTIMIZER, "_voice_feature_similarity", lambda ref, cand: 0.7 if cand["payload_size"] == 20 else 0.6)
    monkeypatch.setattr(module, "_apply_memorial_unmixr_postprocess", lambda **kwargs: (kwargs["payload"], "audio/wav"))
    monkeypatch.setattr(module, "_convert_audio_to_wav", lambda *, payload, content_type: payload)
    monkeypatch.setattr(module, "_wav_duration_seconds", lambda payload: 1.0 if len(payload) == 20 else 2.0)
    monkeypatch.setattr(module._OPTIMIZER, "_transcribe_audio_bytes", lambda payload, *, content_type, slug, base_url: {"text": "Ja. Ich bin da."})
    monkeypatch.setattr(
        module,
        "unmixr_synthesize_request",
        lambda *, text, voice_id, lang, speaking_rate=None, speaking_pitch=None, speaking_volume=None: (
            b"x" * (20 if str(speaking_rate) == "medium" else 10),
            "audio/wav",
        ),
    )

    output_path = tmp_path / "report.json"
    combos = [
        {"speaking_rate": "low", "speaking_pitch": "low", "speaking_volume": "high"},
        {"speaking_rate": "medium", "speaking_pitch": "low", "speaking_volume": "high"},
    ]

    first = module.compare_unmixr_clones(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_ids=["voice-a"],
        prompts=["Ja. Ich bin da."],
        combos=combos,
        output_path=output_path,
        resume=False,
        max_rows=1,
    )

    assert first["complete"] is False
    assert first["completed_rows"] == 1
    checkpoint = json.loads(output_path.read_text(encoding="utf-8"))
    assert checkpoint["completed_rows"] == 1

    second = module.compare_unmixr_clones(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_ids=["voice-a"],
        prompts=["Ja. Ich bin da."],
        combos=combos,
        output_path=output_path,
        resume=True,
        max_rows=0,
    )

    assert second["complete"] is True
    assert second["completed_rows"] == 2
    assert second["winner"]["speaking_rate"] == "medium"


def test_compare_unmixr_clones_times_out_slow_prompt(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    optimization_dir = tmp_path / "optimization"
    candidates_dir = optimization_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    (candidates_dir / "oSQ9FhFc4YI-01440s-28.wav").write_bytes(b"ref")
    monkeypatch.setattr(module, "_optimization_root", lambda *, slug: optimization_dir)
    monkeypatch.setattr(module._OPTIMIZER, "_wav_metrics_from_bytes", lambda payload: {"payload_size": len(payload)})
    monkeypatch.setattr(module, "_apply_memorial_unmixr_postprocess", lambda **kwargs: (kwargs["payload"], "audio/wav"))

    def _slow_synthesize(**kwargs):
        time.sleep(0.05)
        return b"x" * 20, "audio/wav"

    monkeypatch.setattr(module, "unmixr_synthesize_request", _slow_synthesize)

    try:
        module.compare_unmixr_clones(
            slug="manfred",
            base_url="http://127.0.0.1:8090",
            voice_ids=["voice-a"],
            prompts=["Ja. Ich bin da."],
            combos=[{"speaking_rate": "low", "speaking_pitch": "low", "speaking_volume": "low"}],
            prompt_timeout_seconds=0.01,
        )
    except TimeoutError as exc:
        assert "candidate_prompt_timeout" in str(exc)
    else:
        raise AssertionError("expected timeout")


def test_compare_unmixr_clones_feature_only_supports_postprocess_profile(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    optimization_dir = tmp_path / "optimization"
    candidates_dir = optimization_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    (candidates_dir / "oSQ9FhFc4YI-01440s-28.wav").write_bytes(b"ref")

    monkeypatch.setattr(module, "_optimization_root", lambda *, slug: optimization_dir)
    monkeypatch.setattr(module._OPTIMIZER, "_wav_metrics_from_bytes", lambda payload: {"payload_size": len(payload)})
    monkeypatch.setattr(module._OPTIMIZER, "_voice_feature_similarity", lambda ref, cand: 0.91 if cand["payload_size"] == 30 else 0.52)

    applied_profiles: list[str] = []

    def _fake_apply(**kwargs):
        applied_profiles.append(str(kwargs["postprocess_profile"]))
        if str(kwargs["postprocess_profile"]) == "unmixr_raw_preserve":
            return b"x" * 30, "audio/wav"
        return b"x" * 10, "audio/wav"

    monkeypatch.setattr(module, "_apply_memorial_unmixr_postprocess", _fake_apply)
    monkeypatch.setattr(module, "_convert_audio_to_wav", lambda *, payload, content_type: payload)
    monkeypatch.setattr(module, "_wav_duration_seconds", lambda payload: 1.2)
    monkeypatch.setattr(
        module._OPTIMIZER,
        "_transcribe_audio_bytes",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("transcribe should not run in feature-only mode")),
    )
    monkeypatch.setattr(
        module,
        "unmixr_synthesize_request",
        lambda *, text, voice_id, lang, speaking_rate=None, speaking_pitch=None, speaking_volume=None: (b"seed", "audio/wav"),
    )

    report = module.compare_unmixr_clones(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_ids=["voice-a"],
        prompts=["Ja. Ich bin da."],
        combos=[{"speaking_rate": "medium", "speaking_pitch": "medium", "speaking_volume": "medium"}],
        postprocess_profiles=["unmixr_raw_preserve", "unmixr_natural_soft"],
        feature_only=True,
        lead_in_ms=0,
        tail_silence_ms=0,
    )

    assert applied_profiles == ["unmixr_raw_preserve", "unmixr_natural_soft"]
    assert report["feature_only"] is True
    assert report["winner"]["tts_postprocess_profile"] == "unmixr_raw_preserve"
    assert report["recommended_config"]["tts_postprocess_profile"] == "unmixr_raw_preserve"
    assert report["requested_rows"] == 2
