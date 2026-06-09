from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from app.services.memorial_openvoice import unmixr_clone_request


DEFAULT_SEGMENTS = (
    "/docker/EA/memorial_data/private_memorial_profiles/manfred/voice_profile/optimization/candidates/oSQ9FhFc4YI-01440s-28.wav",
    "/docker/EA/memorial_data/private_memorial_profiles/manfred/voice_profile/optimization/candidates/xlrEDbQDTFA-01354s.wav",
    "/docker/EA/memorial_data/private_memorial_profiles/manfred/voice_profile/optimization/beno_candidates2/_oXBWKa3A5M-01180s.wav",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _segment_entry(path: Path) -> dict[str, object]:
    return {
        "path": path.as_posix(),
        "filename": path.name,
        "size_bytes": int(path.stat().st_size),
        "sha256": _sha256_file(path),
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
    slug = str(args.slug or "manfred").strip() or "manfred"
    voice_label = str(args.voice_label or "Manfred Hoza Memorial Refresh").strip() or "Manfred Hoza Memorial Refresh"
    segment_values = [str(item).strip() for item in list(args.segment or []) if str(item).strip()] or list(DEFAULT_SEGMENTS)
    segment_paths = [Path(item).expanduser() for item in segment_values]
    missing = [path.as_posix() for path in segment_paths if not path.is_file()]
    if missing:
        raise SystemExit(f"segment_missing:{missing[0]}")
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
