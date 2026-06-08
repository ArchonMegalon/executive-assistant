#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_ROOT = ROOT / "memorial_data" / "public_memorials"
DEFAULT_PACKET_ROOT = Path("/docker/fleet/state/chummer6/avatar_presenter_provider")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json_object:{path}")
    return dict(payload)


def _safe_name(label: str) -> str:
    lowered = "".join(ch.lower() if ch.isalnum() else "-" for ch in label.strip())
    compact = "-".join(part for part in lowered.split("-") if part)
    return compact or "asset"


def _bundle_paths(slug: str, bundle_root: Path) -> tuple[Path, dict[str, object]]:
    bundle_dir = bundle_root / slug
    memorial_path = bundle_dir / "memorial.json"
    if not memorial_path.is_file():
        raise SystemExit(f"memorial_bundle_missing:{memorial_path}")
    payload = _load_json(memorial_path)
    if str(payload.get("slug") or "").strip() != slug:
        raise SystemExit("memorial_slug_mismatch")
    return bundle_dir, payload


def _first_audio_clip(memorial: dict[str, object]) -> dict[str, object]:
    clips = memorial.get("audio_clips")
    if not isinstance(clips, list):
        raise SystemExit("memorial_audio_clips_missing")
    for item in clips:
        if isinstance(item, dict) and str(item.get("asset_relpath") or "").strip():
            return dict(item)
    raise SystemExit("memorial_audio_clip_missing")


def _portrait_source(bundle_dir: Path, memorial: dict[str, object]) -> Path:
    icons = memorial.get("pwa_icon")
    if not isinstance(icons, dict):
        branding = memorial.get("branding")
        if isinstance(branding, dict):
            icons = branding.get("icons")
    if not isinstance(icons, dict):
        raise SystemExit("memorial_portrait_icon_missing")
    rel = ""
    for key in ("src_512", "src_192", "src_180"):
        candidate = str(icons.get(key) or "").strip()
        if candidate:
            rel = candidate
            break
    if not rel:
        raise SystemExit("memorial_portrait_icon_missing")
    source = bundle_dir / rel
    if not source.is_file():
        raise SystemExit(f"memorial_portrait_icon_not_found:{source}")
    return source


def _audio_source(bundle_dir: Path, clip: dict[str, object]) -> Path:
    rel = str(clip.get("asset_relpath") or "").strip()
    if not rel:
        raise SystemExit("memorial_audio_asset_relpath_missing")
    source = bundle_dir / rel
    if not source.is_file():
        raise SystemExit(f"memorial_audio_asset_not_found:{source}")
    return source


def _extract_audio_segment(source: Path, target: Path, *, start_seconds: float, duration_seconds: float) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-ss",
            str(start_seconds),
            "-t",
            str(duration_seconds),
            "-ar",
            "44100",
            "-ac",
            "1",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not target.is_file():
        raise SystemExit("audio_segment_extract_failed")
    return target


def _transcribe_audio(base_url: str, slug: str, audio_path: Path) -> dict[str, object]:
    if not base_url.strip():
        return {}
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/memorials/{slug}/speech-transcribe",
        data=audio_path.read_bytes(),
        headers={"Content-Type": "audio/wav"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return {"status": "failed", "detail": detail[:400]}
    except Exception as exc:
        return {"status": "failed", "detail": str(exc)[:400]}
    if not isinstance(payload, dict):
        return {"status": "failed", "detail": "invalid_transcription_payload"}
    result = dict(payload)
    result["status"] = "ok"
    return result


def _write_markdown(path: Path, *, payload: dict[str, object]) -> None:
    lines = [
        f"# {payload['title']}",
        "",
        "## Purpose",
        "",
        "Prepare a real VidBoard talking-photo render from the public memorial bundle without inventing new Manfred copy.",
        "",
        "## Assets",
        "",
        f"- Portrait: `{payload['portrait']['path']}`",
        f"- Audio segment: `{payload['audio_segment']['path']}`",
        f"- Source clip: `{payload['source_audio']['path']}`",
        "",
        "## Provider instruction",
        "",
        payload["provider_instruction"],
        "",
        "## Transcript",
        "",
        payload["transcript_text"] or "_No transcript captured yet._",
        "",
        "## Public-safety note",
        "",
        payload["safety_note"],
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a VidBoard avatar render packet from a public memorial bundle.")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_PACKET_ROOT))
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--duration-seconds", type=float, default=14.0)
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()

    slug = str(args.slug).strip()
    if not slug:
        raise SystemExit("slug_missing")
    duration_seconds = float(args.duration_seconds)
    if duration_seconds <= 0:
        raise SystemExit("duration_seconds_invalid")
    start_seconds = max(0.0, float(args.start_seconds))

    bundle_dir, memorial = _bundle_paths(slug, Path(args.bundle_root))
    clip = _first_audio_clip(memorial)
    portrait_source = _portrait_source(bundle_dir, memorial)
    audio_source = _audio_source(bundle_dir, clip)
    person_name = str(memorial.get("person_name") or slug).strip() or slug

    packet_dir = Path(args.output_root) / f"{slug}_vidboard_avatar_packet"
    packet_dir.mkdir(parents=True, exist_ok=True)
    portrait_target = packet_dir / f"{_safe_name(slug)}-portrait{portrait_source.suffix.lower()}"
    portrait_target.write_bytes(portrait_source.read_bytes())
    audio_target = packet_dir / f"{_safe_name(slug)}-public-audio-segment.wav"
    _extract_audio_segment(audio_source, audio_target, start_seconds=start_seconds, duration_seconds=duration_seconds)
    transcript = _transcribe_audio(str(args.base_url), slug, audio_target)
    transcript_text = str(transcript.get("transcript_text") or "").strip()

    payload = {
        "generated_at": _utc_now(),
        "contract_name": "executive_assistant.memorial_vidboard_avatar_packet.v1",
        "slug": slug,
        "title": f"{person_name} VidBoard Avatar Packet",
        "person_name": person_name,
        "provider": "VidBoard",
        "provider_key": "vidboard",
        "source_audio": {
            "title": str(clip.get("title") or ""),
            "description": str(clip.get("description") or ""),
            "path": audio_source.as_posix(),
            "sha256": _sha256_file(audio_source),
        },
        "portrait": {
            "path": portrait_target.as_posix(),
            "sha256": _sha256_file(portrait_target),
        },
        "audio_segment": {
            "path": audio_target.as_posix(),
            "sha256": _sha256_file(audio_target),
            "start_seconds": round(start_seconds, 3),
            "duration_seconds": round(duration_seconds, 3),
        },
        "transcription": transcript,
        "transcript_text": transcript_text,
        "provider_instruction": (
            "Render a talking-photo clip from the supplied portrait plus the supplied original archive audio segment. "
            "Do not rewrite, paraphrase, or synthesize new Manfred copy. Keep the output to the supplied audio only."
        ),
        "safety_note": (
            "This packet is based on a public memorial portrait and a public original archive recording. "
            "The intended render is an animated presentation of existing source audio, not a newly scripted impersonation."
        ),
        "publish_next_step": (
            "After exporting a real VidBoard clip, run "
            "`python3 scripts/publish_memorial_video_call_avatar.py --slug "
            f"{slug} --provider vidboard --asset /path/to/export.mp4`."
        ),
    }
    payload_path = packet_dir / "packet.generated.json"
    payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_markdown(packet_dir / "README.md", payload=payload)
    print(payload_path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
