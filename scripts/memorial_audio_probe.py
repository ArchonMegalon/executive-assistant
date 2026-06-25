#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Finding:
    status: str
    code: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass
class AudioReport:
    path: str
    status: str
    metrics: dict[str, float | int]
    findings: list[Finding]

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "status": self.status,
            "metrics": self.metrics,
            "findings": [asdict(item) for item in self.findings],
        }


def analyze_audio(
    path: Path,
    *,
    threshold: float,
    min_duration: float,
    min_lead_silence: float,
    min_tail_silence: float,
    min_rms: float,
    max_clip_ratio: float,
) -> AudioReport:
    findings: list[Finding] = []
    if not path.is_file():
        return AudioReport(str(path), "fail", {}, [Finding("fail", "audio_missing")])
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        sample_rate = int(handle.getframerate() or 16000)
        sample_width = int(handle.getsampwidth() or 2)
        if sample_width != 2:
            return AudioReport(str(path), "fail", {}, [Finding("fail", "audio_unsupported_sample_width")])
    samples = [int.from_bytes(frames[idx : idx + 2], "little", signed=True) / 32767.0 for idx in range(0, len(frames), 2)]
    duration = len(samples) / float(sample_rate or 1)
    abs_samples = [abs(value) for value in samples]
    active = [index for index, value in enumerate(abs_samples) if value >= threshold]
    lead_silence = (active[0] / sample_rate) if active else duration
    tail_silence = ((len(samples) - 1 - active[-1]) / sample_rate) if active else duration
    rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples)))
    clip_ratio = sum(1 for value in abs_samples if value >= 0.999) / max(1, len(samples))
    metrics = {
        "duration_seconds": round(duration, 3),
        "lead_silence_seconds": round(lead_silence, 3),
        "tail_silence_seconds": round(tail_silence, 3),
        "rms": round(rms, 6),
        "clip_ratio": round(clip_ratio, 6),
    }
    if duration < min_duration:
        findings.append(Finding("fail", "duration_short", {"duration_seconds": metrics["duration_seconds"]}))
    if lead_silence < min_lead_silence:
        findings.append(Finding("warn", "lead_silence_short", {"lead_silence_seconds": metrics["lead_silence_seconds"]}))
    if tail_silence < min_tail_silence:
        findings.append(Finding("warn", "tail_silence_short", {"tail_silence_seconds": metrics["tail_silence_seconds"]}))
    if rms < min_rms:
        findings.append(Finding("fail", "rms_too_low", {"rms": metrics["rms"]}))
    if clip_ratio > max_clip_ratio:
        findings.append(Finding("warn", "clip_ratio_high", {"clip_ratio": metrics["clip_ratio"]}))
    status = "pass"
    if any(item.status == "fail" for item in findings):
        status = "fail"
    elif any(item.status == "warn" for item in findings):
        status = "warn"
    return AudioReport(str(path), status, metrics, findings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    parser.add_argument("--threshold", type=float, default=0.012)
    parser.add_argument("--min-duration", type=float, default=1.2)
    parser.add_argument("--min-lead-silence", type=float, default=0.12)
    parser.add_argument("--min-tail-silence", type=float, default=0.20)
    parser.add_argument("--min-rms", type=float, default=0.004)
    parser.add_argument("--max-clip-ratio", type=float, default=0.004)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = analyze_audio(
        Path(args.audio_path),
        threshold=args.threshold,
        min_duration=args.min_duration,
        min_lead_silence=args.min_lead_silence,
        min_tail_silence=args.min_tail_silence,
        min_rms=args.min_rms,
        max_clip_ratio=args.max_clip_ratio,
    )
    payload = report.as_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=None if args.json else 2))
    return 0 if report.status in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
