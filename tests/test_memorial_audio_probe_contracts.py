from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def write_tone(
    path: Path,
    *,
    sample_rate: int = 16000,
    lead_seconds: float = 0.2,
    tone_seconds: float = 1.0,
    tail_seconds: float = 0.3,
) -> None:
    lead = [0.0] * int(sample_rate * lead_seconds)
    tone = [0.18 * math.sin(2 * math.pi * 220 * i / sample_rate) for i in range(int(sample_rate * tone_seconds))]
    tail = [0.0] * int(sample_rate * tail_seconds)
    samples = lead + tone + tail
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, value)) * 32767)) for value in samples))


def test_audio_probe_passes_clean_tone(tmp_path: Path) -> None:
    import scripts.memorial_audio_probe as probe

    path = tmp_path / "demo.wav"
    write_tone(path)

    report = probe.analyze_audio(
        path,
        threshold=0.012,
        min_duration=1.2,
        min_lead_silence=0.12,
        min_tail_silence=0.20,
        min_rms=0.004,
        max_clip_ratio=0.004,
    )

    assert report.status == "pass"
    assert report.metrics["duration_seconds"] >= 1.4
    assert report.metrics["lead_silence_seconds"] >= 0.19
    assert report.metrics["tail_silence_seconds"] >= 0.29


def test_audio_probe_warns_on_short_lead_silence(tmp_path: Path) -> None:
    import scripts.memorial_audio_probe as probe

    path = tmp_path / "tight.wav"
    write_tone(path, lead_seconds=0.02, tail_seconds=0.3)

    report = probe.analyze_audio(
        path,
        threshold=0.012,
        min_duration=1.2,
        min_lead_silence=0.12,
        min_tail_silence=0.20,
        min_rms=0.004,
        max_clip_ratio=0.004,
    )

    assert report.status == "warn"
    assert any(item.code == "lead_silence_short" for item in report.findings)


def test_audio_probe_fails_missing_file(tmp_path: Path) -> None:
    import scripts.memorial_audio_probe as probe

    report = probe.analyze_audio(
        tmp_path / "missing.wav",
        threshold=0.012,
        min_duration=1.2,
        min_lead_silence=0.12,
        min_tail_silence=0.20,
        min_rms=0.004,
        max_clip_ratio=0.004,
    )

    assert report.status == "fail"
    assert any(item.code == "audio_missing" for item in report.findings)
