from __future__ import annotations

import audioop
import html
import json
import math
import subprocess
import wave
from array import array
from pathlib import Path


ROOT = Path("/docker/EA/memorial_data/private_memorial_profiles/manfred/voice_profile")
MANIFEST_PATH = ROOT / "generated_candidates" / "manifest.json"
GENERATED_DIR = ROOT / "generated_candidates"
LOUPE_DIR = ROOT / "loupe"
BESTOF_PATH = ROOT / "curated" / "youtube-loupe-bestof.wav"
FRAME_MS = 40


def _read_wav_metrics(path: Path) -> dict[str, float]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        raw = wav_file.readframes(frame_count)
    if channels > 1:
        raw = audioop.tomono(raw, sample_width, 0.5, 0.5)
    duration = frame_count / float(sample_rate or 1)
    frame_size = max(sample_width, int(sample_rate * (FRAME_MS / 1000.0)) * sample_width)
    rms_values: list[float] = []
    silent_frames = 0
    total_frames = 0
    for start in range(0, len(raw), frame_size):
        chunk = raw[start:start + frame_size]
        if not chunk:
            continue
        rms = float(audioop.rms(chunk, sample_width))
        rms_values.append(rms)
        total_frames += 1
        if rms < 500:
            silent_frames += 1
    sample_type = "h"
    peak_max = float((1 << (8 * sample_width - 1)) - 1)
    samples = array(sample_type)
    samples.frombytes(raw[: len(raw) - (len(raw) % sample_width)])
    if sample_width != 2:
        raise RuntimeError("expected 16-bit wav candidates")
    abs_samples = [abs(int(value)) for value in samples]
    clipping_ratio = (
        sum(1 for value in abs_samples if value >= peak_max * 0.98) / float(len(abs_samples) or 1)
    )
    zero_crossings = 0
    for prev, cur in zip(samples, samples[1:]):
        if (prev < 0 <= cur) or (prev > 0 >= cur):
            zero_crossings += 1
    zcr = zero_crossings / float(len(samples) or 1)
    mean_rms = sum(rms_values) / float(len(rms_values) or 1)
    rms_std = math.sqrt(sum((value - mean_rms) ** 2 for value in rms_values) / float(len(rms_values) or 1))
    speech_ratio = 1.0 - (silent_frames / float(total_frames or 1))
    stability = 1.0 / (1.0 + (rms_std / float(mean_rms or 1.0)))
    score = (speech_ratio * 60.0) + (stability * 25.0) + ((1.0 - clipping_ratio) * 15.0)
    return {
        "duration_seconds": duration,
        "speech_ratio": speech_ratio,
        "mean_rms": mean_rms,
        "rms_stability": stability,
        "clipping_ratio": clipping_ratio,
        "zero_crossing_rate": zcr,
        "score": score,
    }


def _render_waveform(source: Path, out_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-lavfi",
            "showwavespic=s=1800x280:colors=0x7d4851",
            "-frames:v",
            "1",
            str(out_path),
        ],
        capture_output=True,
        check=True,
    )


def _render_spectrogram(source: Path, out_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-lavfi",
            "showspectrumpic=s=1800x640:legend=disabled:mode=combined:color=channel",
            "-frames:v",
            "1",
            str(out_path),
        ],
        capture_output=True,
        check=True,
    )


def _build_bestof(shortlist: list[Path], out_path: Path) -> None:
    concat_file = LOUPE_DIR / "concat.txt"
    concat_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in shortlist), encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(out_path),
        ],
        capture_output=True,
        check=True,
    )


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    LOUPE_DIR.mkdir(parents=True, exist_ok=True)
    candidates: list[dict[str, object]] = []
    for item in manifest:
        candidate_path = GENERATED_DIR / str(item["candidate_file"])
        metrics = _read_wav_metrics(candidate_path)
        row = dict(item)
        row.update(metrics)
        candidates.append(row)
    ranked = sorted(candidates, key=lambda item: float(item["score"]), reverse=True)
    shortlist = ranked[:8]
    shortlist_paths = [GENERATED_DIR / str(item["candidate_file"]) for item in shortlist]
    _build_bestof(shortlist_paths[:6], BESTOF_PATH)
    rows_html: list[str] = []
    for item in shortlist:
        path = GENERATED_DIR / str(item["candidate_file"])
        wave_png = LOUPE_DIR / f"{path.stem}-wave.png"
        spec_png = LOUPE_DIR / f"{path.stem}-spec.png"
        _render_waveform(path, wave_png)
        _render_spectrogram(path, spec_png)
        rows_html.append(
            "<tr>"
            f"<td>{html.escape(path.name)}</td>"
            f"<td>{html.escape(str(item['source']))}</td>"
            f"<td>{int(item['start_seconds'])}s</td>"
            f"<td>{item['score']:.2f}</td>"
            f"<td>{item['speech_ratio']:.3f}</td>"
            f"<td>{item['rms_stability']:.3f}</td>"
            f"<td>{item['clipping_ratio']:.5f}</td>"
            f"<td><img src='{html.escape(wave_png.name)}' width='480'></td>"
            f"<td><img src='{html.escape(spec_png.name)}' width='480'></td>"
            "</tr>"
        )
    report = {
        "ranked_candidates": ranked,
        "shortlist": shortlist,
        "bestof_path": str(BESTOF_PATH),
    }
    (LOUPE_DIR / "score_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (LOUPE_DIR / "index.html").write_text(
        (
            "<!doctype html><html><head><meta charset='utf-8'><title>Manfred Voice Loupe</title>"
            "<style>body{font-family:Georgia,serif;background:#f5efe6;color:#2b2622;padding:24px}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #cdbba5;padding:8px;vertical-align:top}"
            "th{background:#e7dbc9}img{display:block;background:#fff}</style></head><body>"
            "<h1>Manfred Voice Loupe</h1>"
            f"<p>Automatisch erzeugtes Best-of-Clone-Sourcefile: <code>{html.escape(str(BESTOF_PATH))}</code></p>"
            "<table><thead><tr><th>Datei</th><th>Quelle</th><th>Start</th><th>Score</th><th>Speech</th><th>Stability</th><th>Clip</th><th>Wave</th><th>Spectrogram</th></tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody></table></body></html>"
        ),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "shortlist": len(shortlist), "bestof": str(BESTOF_PATH), "loupe_dir": str(LOUPE_DIR)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
