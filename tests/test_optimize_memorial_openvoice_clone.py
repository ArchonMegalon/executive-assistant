from __future__ import annotations

import io
import json
import math
import struct
import wave
from pathlib import Path


def _make_wav_bytes(*, frequency: int = 240, duration_seconds: float = 0.7) -> bytes:
    sample_rate = 16000
    total_frames = max(1, int(sample_rate * duration_seconds))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(total_frames):
            sample = int(14000 * math.sin(2.0 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


def test_score_transcript_self_speech_prefers_first_person_tail() -> None:
    import scripts.optimize_memorial_openvoice_clone as optimizer

    strong = optimizer._score_transcript_self_speech(
        "Ich habe damals erlebt, wie wir als Familie zusammengehalten haben."
    )
    weak = optimizer._score_transcript_self_speech(
        "Der Journalist fragt, der Reporter sagt etwas und der Beitrag kommentiert."
    )

    assert strong > weak
    assert strong > 0.45
    assert weak < 0.5


def test_candidate_sample_combinations_are_unique(tmp_path: Path) -> None:
    import scripts.optimize_memorial_openvoice_clone as optimizer

    candidates = []
    for index in range(4):
        path = tmp_path / f"cand-{index}.wav"
        path.write_bytes(_make_wav_bytes(frequency=240 + (index * 20)))
        candidates.append({"segment_path": str(path)})

    combinations = optimizer._candidate_sample_combinations(candidates, max_combinations=6)

    assert len(combinations) == 6
    assert len({tuple(str(path) for path in combo) for combo in combinations}) == len(combinations)


def test_optimize_openvoice_clone_writes_best_voice_config(monkeypatch, tmp_path: Path) -> None:
    import scripts.optimize_memorial_openvoice_clone as optimizer

    slug = "manfred"
    private_root = tmp_path / "private"
    profile_dir = private_root / slug / "voice_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))

    candidate_a = profile_dir / "a.wav"
    candidate_b = profile_dir / "b.wav"
    candidate_a.write_bytes(_make_wav_bytes(frequency=230))
    candidate_b.write_bytes(_make_wav_bytes(frequency=310))

    def _fake_collect_tail_candidates(**kwargs):
        return [
            {
                "segment_path": str(candidate_a),
                "transcript_score": 0.58,
                "score": 0.6,
                "transcript_text": "Ich bin da.",
            },
            {
                "segment_path": str(candidate_b),
                "transcript_score": 0.92,
                "score": 0.9,
                "transcript_text": "Ich habe das damals selbst erlebt.",
            },
        ]

    def _fake_clone_openvoice_candidate(*, slug: str, voice_id: str, sample_paths: list[Path]) -> str:
        assert slug == "manfred"
        assert sample_paths
        return voice_id

    def _fake_evaluate_clone(
        *,
        voice_id: str,
        sample_paths: list[Path],
        prompts: list[str],
        base_voice_variant: str,
        slug: str,
        base_url: str,
    ):
        score = 0.46 if voice_id.endswith("01") else 0.93
        return {
            "voice_id": voice_id,
            "score": score,
            "prompts": [{"prompt": prompts[0], "score": score}],
            "reference_metrics": {"duration_seconds": 0.7, "mean_rms": 1000.0, "speech_ratio": 0.9, "zero_crossing_rate": 0.03},
        }

    monkeypatch.setattr(optimizer, "_collect_tail_candidates", _fake_collect_tail_candidates)
    monkeypatch.setattr(optimizer, "_clone_openvoice_candidate", _fake_clone_openvoice_candidate)
    monkeypatch.setattr(optimizer, "_evaluate_clone", _fake_evaluate_clone)

    report = optimizer.optimize_openvoice_clone(
        slug=slug,
        max_candidates=4,
        max_combinations=3,
        max_iterations=3,
        segment_seconds=22.0,
        tail_window_seconds=240.0,
        step_seconds=18.0,
        accept_threshold=0.8,
        base_voice_variant="balanced",
        apply_best=True,
        prompts=["Ich bin da."],
        base_url="http://127.0.0.1:8090",
    )

    assert report["best_iteration"]["voice_id"] == "manfred-openvoice-opt-02"
    assert report["applied_config_path"]
    config_path = Path(str(report["applied_config_path"]))
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["tts_plugin"] == "openvoice_local"
    assert payload["tts_plugin_voice_id"] == "manfred-openvoice-opt-02"
    assert payload["synthetic_voice_clone_of_memorial_person"] is True
    assert "OpenVoice-Optimierung" in payload["notes"]
    assert Path(str(report["report_path"])).is_file()
