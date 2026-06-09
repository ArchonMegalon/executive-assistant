from __future__ import annotations

import importlib.util
import json
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
