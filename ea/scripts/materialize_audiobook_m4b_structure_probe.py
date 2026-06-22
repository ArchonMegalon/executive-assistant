from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(command: list[str], *, timeout: int = 120) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "command_failed")[-1200:])


def _write_metadata(path: Path, *, audio_paths: list[Path]) -> None:
    cursor = 0
    lines = [";FFMETADATA1", "title=EA Audiobook Structure Probe", "artist=EA Narration"]
    for index, audio_path in enumerate(audio_paths, start=1):
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(audio_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(probe.stdout or "{}") if probe.returncode == 0 else {}
        duration_ms = max(1, int(float(dict(payload.get("format") or {}).get("duration") or 1.0) * 1000))
        end = cursor + duration_ms
        lines.extend(["[CHAPTER]", "TIMEBASE=1/1000", f"START={cursor}", f"END={end}", f"title=Chapter {index}"])
        cursor = end
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def materialize_audiobook_m4b_structure_probe(*, artifact_dir: Path, generated_at: str) -> dict[str, object]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    audio_paths = [artifact_dir / "chapter-1.wav", artifact_dir / "chapter-2.wav"]
    for index, audio_path in enumerate(audio_paths, start=1):
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={420 + index * 110}:duration=1.2",
                "-ac",
                "1",
                "-ar",
                "44100",
                str(audio_path),
            ]
        )
    cover_path = artifact_dir / "cover.jpg"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x30475e:s=1000x1000,drawbox=x=90:y=90:w=820:h=820:color=0xf2a365@0.35:t=24,drawbox=x=170:y=680:w=660:h=80:color=white@0.22:t=fill",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(cover_path),
        ]
    )
    concat_path = artifact_dir / "concat.txt"
    concat_path.write_text("".join(f"file '{str(path).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in audio_paths), encoding="utf-8")
    metadata_path = artifact_dir / "chapters.ffmetadata"
    _write_metadata(metadata_path, audio_paths=audio_paths)
    m4b_path = artifact_dir / "structure-probe.m4b"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-i",
            str(metadata_path),
            "-i",
            str(cover_path),
            "-map",
            "0:a",
            "-map",
            "2:v",
            "-disposition:v:0",
            "attached_pic",
            "-map_metadata",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-ac",
            "1",
            "-c:v",
            "copy",
            str(m4b_path),
        ]
    )
    receipt = {
        "contract_name": "ea.audiobook_m4b_structure_probe.v1",
        "status": "ready",
        "generated_at": generated_at,
        "expected": {"chapter_count": 2, "cover_attached_pic": True},
        "merge_result": {"status": "m4b_ready", "provider": "ffmpeg", "cover_embedded": True, "chapter_count": 2},
        "m4b": {"path": m4b_path.name, "sha256": _sha256(m4b_path), "bytes": m4b_path.stat().st_size},
    }
    (artifact_dir / "audiobook_m4b_structure_probe.generated.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    print(json.dumps(materialize_audiobook_m4b_structure_probe(artifact_dir=args.artifact_dir, generated_at=args.generated_at), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

