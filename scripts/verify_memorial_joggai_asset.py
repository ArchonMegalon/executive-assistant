#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ALLOWED_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}
ALLOWED_POSTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_PUBLIC_REVIEW_STATUSES = {"approved"}
FORBIDDEN_SCRIPT_PHRASES = (
    "i am manfred and i am here again",
    "ich bin manfred und ich bin wieder da",
    "i can see what is happening today",
    "ich sehe was heute passiert",
    "i remember everything you ask me",
    "ich erinnere mich an alles was du fragst",
    "i will tell you what happens next",
    "ich sage dir was als naechstes passiert",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json_object:{path}")
    return dict(payload)


def _validate_file(path: Path, *, suffixes: set[str], code: str) -> None:
    if not path.is_file():
        raise SystemExit(f"{code}_missing:{path}")
    if path.suffix.lower() not in suffixes:
        raise SystemExit(f"{code}_unsupported_suffix:{path.suffix.lower()}")


def _validate_relpath(value: str, *, code: str) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if raw.startswith("/") or "://" in raw:
        raise SystemExit(f"{code}_unsafe")
    normalized = raw.lstrip("/")
    if not normalized:
        raise SystemExit(f"{code}_missing")
    parts = [part for part in normalized.split("/") if part]
    if any(part == ".." for part in parts):
        raise SystemExit(f"{code}_unsafe")
    return "/".join(parts)


def _ffprobe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"ffprobe_failed:{path}")
    payload = json.loads(completed.stdout or "{}")
    if not isinstance(payload, dict):
        raise SystemExit(f"ffprobe_invalid_payload:{path}")
    return payload


def _video_metadata(path: Path) -> dict[str, Any]:
    payload = _ffprobe(path)
    streams = [dict(item) for item in payload.get("streams", []) if isinstance(item, dict)]
    fmt = dict(payload.get("format", {}) or {})
    video = next((item for item in streams if str(item.get("codec_type") or "").lower() == "video"), None)
    if not video:
        raise SystemExit("joggai_asset_no_video_stream")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise SystemExit("joggai_asset_invalid_dimensions")
    try:
        duration = float(video.get("duration") or fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0.0:
        raise SystemExit("joggai_asset_duration_missing")
    if duration > 15 * 60:
        raise SystemExit("joggai_asset_too_long")
    codec = str(video.get("codec_name") or "").strip().lower()
    if not codec:
        raise SystemExit("joggai_asset_codec_missing")
    ratio = "unknown"
    if width and height:
        value = width / height
        if abs(value - (16 / 9)) < 0.06:
            ratio = "16:9"
        elif abs(value - (9 / 16)) < 0.06:
            ratio = "9:16"
    return {
        "duration_seconds": round(duration, 3),
        "width": width,
        "height": height,
        "codec_name": codec,
        "aspect_ratio": ratio,
    }


def _consent_scope(consent: Any) -> set[str]:
    if not isinstance(consent, dict):
        return set()
    return {str(item or "").strip() for item in list(consent.get("scope") or []) if str(item or "").strip()}


def _validate_approved_consent(consent: Any, *, code: str, required_scopes: set[str]) -> None:
    if not isinstance(consent, dict):
        raise SystemExit(f"{code}_required")
    if str(consent.get("status") or "").strip().lower() != "approved" or consent.get("revoked") is True:
        raise SystemExit(f"{code}_not_approved")
    scopes = _consent_scope(consent)
    missing = sorted(required_scopes - scopes)
    if missing:
        raise SystemExit(f"{code}_scope_missing:{','.join(missing)}")


def _validate_script_packet(packet: dict[str, Any], *, public_ready: bool) -> None:
    if str(packet.get("provider") or "").strip().lower() != "joggai":
        raise SystemExit("script_provider_not_joggai")
    if str(packet.get("approved_by") or "").strip() == "":
        raise SystemExit("script_not_approved")
    if str(packet.get("approved_at") or "").strip() == "":
        raise SystemExit("script_approval_timestamp_missing")
    script = str(packet.get("script") or "").strip()
    if not script:
        raise SystemExit("script_missing")
    lowered = " ".join(script.lower().split())
    if any(phrase in lowered for phrase in FORBIDDEN_SCRIPT_PHRASES):
        raise SystemExit("script_forbidden_memorial_claim")
    if packet.get("uses_manfred_likeness") is True:
        required = {"joggai_candidate_render"}
        if public_ready:
            required.add("public_playback")
        _validate_approved_consent(packet.get("avatar_consent"), code="avatar_consent", required_scopes=required)
    if packet.get("uses_manfred_voice") is True:
        required = {"joggai_candidate_render", "clone"}
        if public_ready:
            required.add("public_playback")
        _validate_approved_consent(packet.get("voice_consent"), code="voice_consent", required_scopes=required)
    if packet.get("uses_private_memory") is True and packet.get("private_memory_review_approved") is not True:
        raise SystemExit("private_memory_review_required")


def build_receipt(
    *,
    slug: str,
    asset: Path,
    poster: Path,
    script_packet: Path,
    output: Path,
    asset_relpath: str,
    poster_relpath: str,
    review_status: str,
    public_ready: bool,
    watermark_present: bool,
) -> dict[str, Any]:
    _validate_file(asset, suffixes=ALLOWED_VIDEO_SUFFIXES, code="joggai_asset")
    _validate_file(poster, suffixes=ALLOWED_POSTER_SUFFIXES, code="joggai_poster")
    packet = _load_json(script_packet)
    normalized_review = str(review_status or "").strip().lower() or "candidate"
    if public_ready and normalized_review not in ALLOWED_PUBLIC_REVIEW_STATUSES:
        raise SystemExit("public_ready_requires_approved_review")
    _validate_script_packet(packet, public_ready=public_ready)
    asset_relpath = _validate_relpath(asset_relpath, code="asset_relpath")
    poster_relpath = _validate_relpath(poster_relpath, code="poster_relpath")
    metadata = _video_metadata(asset)
    if public_ready and watermark_present:
        raise SystemExit("public_ready_requires_no_watermark")
    asset_hash = _sha256_file(asset)
    poster_hash = _sha256_file(poster)
    script_hash = hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    receipt = {
        "contract_name": "executive_assistant.memorial_joggai_render.v1",
        "provider": "joggai",
        "provider_key": "joggai",
        "slug": slug,
        "script_id": str(packet.get("script_id") or ""),
        "rendered_at": _utc_now(),
        "account_tier": "AppSumo Tier 4",
        "speaker_type": str(packet.get("speaker_type") or "neutral_presenter"),
        "uses_manfred_likeness": bool(packet.get("uses_manfred_likeness") is True),
        "uses_manfred_voice": bool(packet.get("uses_manfred_voice") is True),
        "input_script_sha256": script_hash,
        "asset_relpath": asset_relpath,
        "poster_relpath": poster_relpath,
        "asset_sha256": asset_hash,
        "poster_sha256": poster_hash,
        "duration_seconds": metadata["duration_seconds"],
        "aspect_ratio": metadata["aspect_ratio"],
        "asset_metadata": metadata,
        "watermark_present": bool(watermark_present),
        "review_status": normalized_review,
        "public_ready": bool(public_ready),
        "mode": "manual",
        "api_used": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a manually exported JoggAI memorial video asset and write a render receipt.")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--poster", required=True)
    parser.add_argument("--script-packet", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--asset-relpath", default="")
    parser.add_argument("--poster-relpath", default="")
    parser.add_argument("--review-status", default="candidate")
    parser.add_argument("--public-ready", action="store_true")
    parser.add_argument("--watermark-present", action="store_true")
    args = parser.parse_args()
    asset = Path(args.asset)
    poster = Path(args.poster)
    receipt = build_receipt(
        slug=str(args.slug).strip(),
        asset=asset,
        poster=poster,
        script_packet=Path(args.script_packet),
        output=Path(args.output),
        asset_relpath=str(args.asset_relpath or f"video/joggai/{asset.name}"),
        poster_relpath=str(args.poster_relpath or f"video/joggai/{poster.name}"),
        review_status=str(args.review_status),
        public_ready=bool(args.public_ready),
        watermark_present=bool(args.watermark_present),
    )
    print(json.dumps({"status": "pass", "output": str(args.output), "public_ready": receipt["public_ready"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
