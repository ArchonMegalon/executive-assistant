from __future__ import annotations

import json
import subprocess
from pathlib import Path


PROFILE_ROOT = Path("/docker/EA/memorial_data/private_memorial_profiles/manfred/voice_profile")
SOURCE_FILES = [
    PROFILE_ROOT / "m6QosScYyP8.mp3",
    PROFILE_ROOT / "xlrEDbQDTFA.mp3",
]
OUTPUT_DIR = PROFILE_ROOT / "generated_candidates"
SEGMENT_SECONDS = 26
STEP_SECONDS = 35
START_OFFSET_SECONDS = 20
END_GUARD_SECONDS = 25


def _duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float((result.stdout or "0").strip() or "0")


def _cut_segment(source: Path, start_seconds: int, out_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_seconds),
            "-i",
            str(source),
            "-t",
            str(SEGMENT_SECONDS),
            "-ac",
            "1",
            "-ar",
            "24000",
            str(out_path),
        ],
        capture_output=True,
        check=True,
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for source in SOURCE_FILES:
        if not source.is_file():
            continue
        duration = _duration_seconds(source)
        start = START_OFFSET_SECONDS
        clip_index = 1
        while start + SEGMENT_SECONDS <= max(0, int(duration) - END_GUARD_SECONDS):
            out_name = f"{source.stem}-cand-{clip_index:02d}-{start:04d}s.wav"
            out_path = OUTPUT_DIR / out_name
            _cut_segment(source, start, out_path)
            manifest.append(
                {
                    "source": source.name,
                    "candidate_file": out_name,
                    "start_seconds": start,
                    "duration_seconds": SEGMENT_SECONDS,
                }
            )
            clip_index += 1
            start += STEP_SECONDS
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "candidates": len(manifest), "output_dir": str(OUTPUT_DIR)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
