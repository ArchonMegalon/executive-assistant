from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.memorial_openvoice import unmixr_clone_request  # noqa: E402
from app.services.memorial_paths import private_profile_dir  # noqa: E402


DEFAULT_SEGMENT_RELATIVE_PATHS = (
    Path("voice_profile/curated/manfred-unmixr-xlr-1325-1355-v1.wav"),
)
UNMIXR_MIN_SAMPLE_SECONDS = 30.0
UNMIXR_MAX_SAMPLE_SECONDS = 75.0


def _safe_slug(value: object) -> str:
    slug = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", slug):
        raise ValueError("memorial_slug_invalid")
    return slug


def default_segment_paths(slug: str) -> list[Path]:
    root = private_profile_dir() / _safe_slug(slug)
    return [root / relative for relative in DEFAULT_SEGMENT_RELATIVE_PATHS]


# Compatibility and operator-injection seam. Repository defaults stay relative;
# tests and local operators may replace them with explicit absolute paths without
# committing checkout- or provider-specific asset locations.
DEFAULT_SEGMENTS = tuple(
    path.as_posix() for path in DEFAULT_SEGMENT_RELATIVE_PATHS
)


def configured_default_segment_paths(slug: str) -> list[Path]:
    normalized_slug = _safe_slug(slug)
    if normalized_slug == "manfred":
        profile_root = private_profile_dir() / normalized_slug
        configured = [Path(item).expanduser() for item in DEFAULT_SEGMENTS]
        return [
            path if path.is_absolute() else profile_root / path
            for path in configured
        ]
    return default_segment_paths(normalized_slug)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _segment_entry(path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("segment_audio_invalid")
    try:
        probe = json.loads(completed.stdout or "{}")
        stream = dict((probe.get("streams") or [])[0])
        duration_seconds = float(dict(probe.get("format") or {}).get("duration") or 0.0)
        sample_rate_hz = int(stream.get("sample_rate") or 0)
        channels = int(stream.get("channels") or 0)
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("segment_audio_invalid") from exc
    if duration_seconds <= 0:
        raise ValueError("segment_audio_invalid")
    if duration_seconds + 0.05 < UNMIXR_MIN_SAMPLE_SECONDS:
        raise ValueError("segment_audio_too_short")
    if duration_seconds > UNMIXR_MAX_SAMPLE_SECONDS + 0.05:
        raise ValueError("segment_audio_too_long")
    return {
        "path": path.as_posix(),
        "filename": path.name,
        "size_bytes": int(path.stat().st_size),
        "sha256": _sha256_file(path),
        "duration_seconds": round(duration_seconds, 3),
        "sample_rate_hz": sample_rate_hz,
        "channels": channels,
        "codec_name": str(stream.get("codec_name") or "").strip(),
    }


def _load_unmixr_key_from_live_env() -> str:
    value = str(os.environ.get("UNMIXR_API_KEY") or "").strip()
    if value:
        return value
    try:
        value = subprocess.check_output(
            ["docker", "exec", "ea-api", "sh", "-lc", 'printf %s "$UNMIXR_API_KEY"'],
            text=True,
        ).strip()
    except Exception:
        value = ""
    if value:
        os.environ["UNMIXR_API_KEY"] = value
    return value


def build_packet(*, slug: str, voice_label: str, segment_paths: list[Path], output_dir: Path) -> dict[str, object]:
    if len(segment_paths) != 1:
        raise ValueError("single_prepared_segment_required")
    output_dir.mkdir(parents=True, exist_ok=True)
    packet = {
        "generated_at": _utc_now(),
        "slug": slug,
        "voice_label": voice_label,
        "provider_key": "unmixr",
        "goal": "fresh_memorial_clone_refresh",
        "segments": [_segment_entry(path) for path in segment_paths],
        "clone_attempt": {},
    }
    return packet


def attempt_clone(*, slug: str, voice_label: str, segment_paths: list[Path]) -> dict[str, object]:
    if len(segment_paths) != 1:
        return {
            "status": "blocked",
            "code": "single_prepared_segment_required",
            "detail": "Unmixr requires one precomposed, speaker-reviewed sample.",
        }
    api_key = _load_unmixr_key_from_live_env()
    if not api_key:
        return {
            "status": "blocked",
            "code": "unmixr_api_key_missing",
            "detail": "No UNMIXR_API_KEY available in local or live runtime env.",
        }
    try:
        voice_id = unmixr_clone_request(slug=slug, voice_label=voice_label, sample_paths=segment_paths)
    except HTTPException as exc:
        return {
            "status": "blocked",
            "code": "unmixr_clone_blocked",
            "detail": str(exc.detail or ""),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "status": "blocked",
            "code": "unmixr_clone_failed",
            "detail": str(exc),
        }
    return {
        "status": "created",
        "voice_id": voice_id,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the next memorial Unmixr refresh clone packet and capture clone receipts.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--voice-label", default="Manfred Hoza Memorial Refresh")
    parser.add_argument("--segment", action="append", default=[])
    parser.add_argument("--attempt-clone", action="store_true")
    parser.add_argument("--output-dir", default="/tmp/manfred_unmixr_refresh_packet")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    slug = _safe_slug(args.slug or "manfred")
    voice_label = str(args.voice_label or "Manfred Hoza Memorial Refresh").strip() or "Manfred Hoza Memorial Refresh"
    segment_values = [str(item).strip() for item in list(args.segment or []) if str(item).strip()]
    segment_paths = (
        [Path(item).expanduser() for item in segment_values]
        if segment_values
        else configured_default_segment_paths(slug)
    )
    missing = [path.as_posix() for path in segment_paths if not path.is_file()]
    if missing:
        raise SystemExit(f"segment_missing:{missing[0]}")
    if len(segment_paths) != 1:
        raise SystemExit("single_prepared_segment_required")
    output_dir = Path(str(args.output_dir or "/tmp/manfred_unmixr_refresh_packet")).expanduser()
    payload = build_packet(slug=slug, voice_label=voice_label, segment_paths=segment_paths, output_dir=output_dir)
    if bool(args.attempt_clone):
        payload["clone_attempt"] = attempt_clone(slug=slug, voice_label=voice_label, segment_paths=segment_paths)
    output = str(args.output or "").strip()
    if output:
        output_path = Path(output).expanduser()
    else:
        output_path = output_dir / "unmixr_refresh_packet.generated.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
