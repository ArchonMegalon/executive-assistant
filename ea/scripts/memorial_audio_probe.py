#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AudioFinding:
    status: str
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioReport:
    path: str
    findings: list[AudioFinding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def add(self, status: str, code: str, message: str, **detail: Any) -> None:
        self.findings.append(AudioFinding(status=status, code=code, message=message, detail=detail))

    @property
    def failed(self) -> bool:
        return any(item.status == "fail" for item in self.findings)

    @property
    def warned(self) -> bool:
        return any(item.status == "warn" for item in self.findings)

    @property
    def status(self) -> str:
        if self.failed:
            return "fail"
        if self.warned:
            return "warn"
        return "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "metrics": self.metrics,
            "findings": [
                {"status": item.status, "code": item.code, "message": item.message, "detail": item.detail}
                for item in self.findings
            ],
        }

    def markdown(self) -> str:
        lines = [
            "# Memorial Audio Probe",
            "",
            f"File: `{self.path}`",
            f"Status: **{self.status.upper()}**",
            "",
            "## Metrics",
            "",
        ]
        for key, value in self.metrics.items():
            lines.append(f"- `{key}`: `{value}`")
        lines.extend(["", "## Findings", ""])
        for item in self.findings:
            label = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(item.status, "INFO")
            lines.append(f"- `{label}` `{item.code}` {item.message}")
            if item.detail:
                lines.append(f"  `{json.dumps(item.detail, ensure_ascii=False, sort_keys=True)}`")
        return "\n".join(lines)


def ffmpeg_decode_to_wav(path: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg_missing_for_non_wav_audio")
    tmp = tempfile.NamedTemporaryFile(prefix="memorial-audio-probe-", suffix=".wav", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(tmp_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=45,
        check=False,
    )
    if proc.returncode != 0 or not tmp_path.is_file():
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg_decode_failed:{proc.stderr[-300:]}")
    return tmp_path


def wav_samples(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as wav:
        channels = int(wav.getnchannels())
        sample_rate = int(wav.getframerate())
        sample_width = int(wav.getsampwidth())
        frames = int(wav.getnframes())
        if sample_width != 2:
            raise RuntimeError(f"unsupported_sample_width:{sample_width}")
        raw = wav.readframes(frames)
    unpacked = struct.iter_unpack("<h", raw)
    if channels <= 1:
        return sample_rate, [sample[0] / 32768.0 for sample in unpacked]
    values: list[float] = []
    frame: list[int] = []
    for sample in unpacked:
        frame.append(sample[0])
        if len(frame) == channels:
            values.append((sum(frame) / channels) / 32768.0)
            frame = []
    return sample_rate, values


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
    original = path.resolve()
    report = AudioReport(path=str(original))
    if not original.is_file():
        report.add("fail", "audio_missing", "Audio file does not exist.")
        return report
    if original.stat().st_size <= 0:
        report.add("fail", "audio_empty", "Audio file is empty.")
        return report

    decode_path: Path | None = None
    try:
        wav_path = original if original.suffix.lower() == ".wav" else ffmpeg_decode_to_wav(original)
        if wav_path != original:
            decode_path = wav_path
        sample_rate, samples = wav_samples(wav_path)
    except Exception as exc:
        report.add("fail", "audio_decode_failed", "Audio could not be decoded for analysis.", error=f"{type(exc).__name__}: {exc}")
        return report
    finally:
        if decode_path:
            decode_path.unlink(missing_ok=True)

    if not samples:
        report.add("fail", "audio_no_samples", "Audio decoded but contains no samples.")
        return report

    abs_samples = [abs(value) for value in samples]
    duration = len(samples) / float(sample_rate)
    peak = max(abs_samples)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    clipping_count = sum(1 for value in abs_samples if value >= 0.985)
    clipping_ratio = clipping_count / len(samples)

    loud_indices = [index for index, value in enumerate(abs_samples) if value >= threshold]
    if loud_indices:
        first_loud = loud_indices[0]
        last_loud = loud_indices[-1]
        lead_silence = first_loud / float(sample_rate)
        tail_silence = (len(samples) - 1 - last_loud) / float(sample_rate)
    else:
        lead_silence = duration
        tail_silence = duration

    report.metrics.update(
        {
            "sample_rate": sample_rate,
            "samples": len(samples),
            "duration_seconds": round(duration, 3),
            "lead_silence_seconds": round(lead_silence, 3),
            "tail_silence_seconds": round(tail_silence, 3),
            "peak": round(peak, 5),
            "rms": round(rms, 5),
            "clipping_ratio": round(clipping_ratio, 6),
            "size_bytes": original.stat().st_size,
        }
    )

    if duration < min_duration:
        report.add("fail", "duration_too_short", "Audio is too short for a reliable demo sample.", duration=duration, minimum=min_duration)
    else:
        report.add("pass", "duration_ok", "Audio duration is sufficient.", duration=round(duration, 3))

    if rms < min_rms:
        report.add("fail", "audio_too_quiet", "Audio RMS is too low; likely silence or failed synthesis.", rms=rms, minimum=min_rms)
    else:
        report.add("pass", "rms_ok", "Audio level is non-silent.", rms=round(rms, 5))

    if lead_silence < min_lead_silence:
        report.add("warn", "lead_silence_short", "Audio may start too abruptly for room playback.", lead_silence=round(lead_silence, 3), minimum=min_lead_silence)
    else:
        report.add("pass", "lead_silence_ok", "Audio has enough lead-in silence.", lead_silence=round(lead_silence, 3))

    if tail_silence < min_tail_silence:
        report.add("warn", "tail_silence_short", "Audio may cut off too quickly at the end.", tail_silence=round(tail_silence, 3), minimum=min_tail_silence)
    else:
        report.add("pass", "tail_silence_ok", "Audio has enough trailing silence.", tail_silence=round(tail_silence, 3))

    if clipping_ratio > max_clip_ratio:
        report.add("warn", "possible_clipping", "Audio may be clipped or limited too aggressively.", clipping_ratio=round(clipping_ratio, 6), maximum=max_clip_ratio)
    else:
        report.add("pass", "clipping_ok", "No significant clipping detected.", clipping_ratio=round(clipping_ratio, 6))

    return report


def _write_optional(path: str, content: str) -> None:
    if path:
        Path(path).write_text(content + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe memorial demo audio for room-readiness.")
    parser.add_argument("audio_path")
    parser.add_argument("--threshold", type=float, default=0.012)
    parser.add_argument("--min-duration", type=float, default=1.2)
    parser.add_argument("--min-lead-silence", type=float, default=0.12)
    parser.add_argument("--min-tail-silence", type=float, default=0.20)
    parser.add_argument("--min-rms", type=float, default=0.004)
    parser.add_argument("--max-clip-ratio", type=float, default=0.004)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--json-output", default="")
    parser.add_argument("--markdown-output", default="")
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

    payload = json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
    markdown = report.markdown()
    _write_optional(args.json_output, payload)
    _write_optional(args.markdown_output, markdown)
    if args.output:
        rendered = payload if args.json else markdown
        _write_optional(args.output, rendered)
    print(payload if args.json else markdown)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
