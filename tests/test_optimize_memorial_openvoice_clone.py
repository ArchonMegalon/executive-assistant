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


def test_score_transcript_self_speech_penalizes_reportage_over_direct_speech() -> None:
    import scripts.optimize_memorial_openvoice_clone as optimizer

    direct = optimizer._score_transcript_self_speech(
        "Das ist sehr schwierig. Hier bin ich der Meinung, es müsste versucht werden, dass eine Glaubhaftmachung reicht."
    )
    reportage = optimizer._score_transcript_self_speech(
        "Unternehmen und ich habe da manchmal über die Stränge geschlagen. Anita Mohr hat mehrfach im Betriebsrat um eine Vermittlung gebeten."
    )

    assert direct > reportage
    assert direct > 0.75
    assert reportage < 0.8


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


def test_list_source_audio_paths_skips_derived_voice_artifacts(monkeypatch, tmp_path: Path) -> None:
    import scripts.optimize_memorial_openvoice_clone as optimizer

    slug = "manfred"
    profile_dir = tmp_path / slug / "voice_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "xlrEDbQDTFA.mp3").write_bytes(b"raw")
    (profile_dir / "manfredbestof-openvoice-00000s.wav").write_bytes(b"derived")
    (profile_dir / "unmixr-challenger-youtube-v5.wav").write_bytes(b"derived")
    (profile_dir / "top3-balanced.wav").write_bytes(b"derived")
    monkeypatch.setattr(optimizer, "_voice_profile_dir", lambda *, slug: profile_dir)

    paths = optimizer._list_source_audio_paths(slug=slug)

    assert [path.name for path in paths] == ["xlrEDbQDTFA.mp3"]


def test_collect_tail_candidates_reuses_cached_transcripts(monkeypatch, tmp_path: Path) -> None:
    import scripts.optimize_memorial_openvoice_clone as optimizer

    slug = "manfred"
    private_root = tmp_path / "private"
    profile_dir = private_root / slug / "voice_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))

    source_path = profile_dir / "source.mp3"
    source_path.write_bytes(b"fake")
    segment_payload = _make_wav_bytes(frequency=250)

    monkeypatch.setattr(optimizer, "_list_source_audio_paths", lambda *, slug: [source_path])
    monkeypatch.setattr(optimizer, "_ffprobe_duration_seconds", lambda path: 120.0)
    monkeypatch.setattr(optimizer, "_tail_start_points", lambda **kwargs: [100.0])

    def _fake_extract_segment_to_wav(*, source, start_seconds, duration_seconds, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(segment_payload)

    transcribe_calls = {"count": 0}

    def _fake_transcribe_audio_bytes(payload: bytes, *, content_type: str, slug: str, base_url: str):
        transcribe_calls["count"] += 1
        return {"transcript_text": "Ich habe das selbst erlebt."}

    monkeypatch.setattr(optimizer, "_extract_segment_to_wav", _fake_extract_segment_to_wav)
    monkeypatch.setattr(optimizer, "_transcribe_audio_bytes", _fake_transcribe_audio_bytes)

    first = optimizer._collect_tail_candidates(
        slug=slug,
        segment_seconds=20.0,
        tail_window_seconds=30.0,
        step_seconds=10.0,
        max_candidates=3,
        base_url="http://127.0.0.1:8090",
    )
    second = optimizer._collect_tail_candidates(
        slug=slug,
        segment_seconds=20.0,
        tail_window_seconds=30.0,
        step_seconds=10.0,
        max_candidates=3,
        base_url="http://127.0.0.1:8090",
    )

    assert first[0]["transcript_text"] == "Ich habe das selbst erlebt."
    assert second[0]["transcript_text"] == "Ich habe das selbst erlebt."
    assert transcribe_calls["count"] == 1


def test_voice_feature_similarity_prefers_same_signal() -> None:
    import scripts.optimize_memorial_openvoice_clone as optimizer

    same = optimizer._voice_feature_similarity(
        optimizer._wav_metrics_from_bytes(_make_wav_bytes(frequency=240)),
        optimizer._wav_metrics_from_bytes(_make_wav_bytes(frequency=240)),
    )
    different = optimizer._voice_feature_similarity(
        optimizer._wav_metrics_from_bytes(_make_wav_bytes(frequency=240)),
        optimizer._wav_metrics_from_bytes(_make_wav_bytes(frequency=480)),
    )

    assert same > different
    assert same > 0.9


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
        selected_candidates: list[dict[str, object]],
        prompts: list[str],
        base_voice_variant: str,
        slug: str,
        base_url: str,
        iteration_index: int,
        reference_mimic_count: int,
    ):
        score = 0.46 if voice_id.endswith("01") else 0.93
        preview_dir = private_root / slug / "voice_profile" / "optimization" / "previews" / f"iteration-{iteration_index:02d}-{voice_id}"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / "preview.wav"
        preview_path.write_bytes(_make_wav_bytes(frequency=260))
        return {
            "voice_id": voice_id,
            "score": score,
            "prompt_average_score": score,
            "mimic_average_score": score,
            "prompts": [{"prompt": prompts[0], "score": score, "preview_path": str(preview_path), "roundtrip_score": score, "feature_score": score, "transcript_text": prompts[0]}],
            "reference_mimics": [],
            "reference_metrics": {"duration_seconds": 0.7, "mean_rms": 1000.0, "speech_ratio": 0.9, "zero_crossing_rate": 0.03},
            "preview_dir": str(preview_dir),
            "reference_sample_paths": [str(candidate_a)],
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
        base_voice_variants=["balanced"],
        apply_best=True,
        prompts=["Ich bin da."],
        base_url="http://127.0.0.1:8090",
        reference_mimic_count=2,
    )

    assert report["best_iteration"]["voice_id"] == "manfred-openvoice-opt-02"
    assert report["applied_config_path"]
    config_path = Path(str(report["applied_config_path"]))
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["tts_plugin"] == "openvoice_local"
    assert payload["tts_plugin_voice_id"] == "manfred-openvoice-opt-02"
    assert payload["tts_base_voice_variant"] == "balanced"
    assert payload["synthetic_voice_clone_of_memorial_person"] is True
    assert "OpenVoice-Optimierung" in payload["notes"]
    assert Path(str(report["report_path"])).is_file()
    assert Path(str(report["preview_index_path"])).is_file()
    preview_index = Path(str(report["preview_index_path"])).read_text(encoding="utf-8")
    assert "manfred-openvoice-opt-02" in preview_index
    assert "preview.wav" in preview_index
