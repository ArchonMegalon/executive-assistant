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

from app.services.memorial_openvoice import (  # noqa: E402
    unmixr_api_key_slot_names,
    unmixr_clone_request,
)
from app.services.memorial_paths import private_profile_dir  # noqa: E402


DEFAULT_SEGMENT_RELATIVE_PATHS = (
    Path("voice_profile/curated/manfred-unmixr-osq-1438-1478-v2.wav"),
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


def _validated_provenance_entry(
    *,
    segment_path: Path,
    segment: dict[str, object],
) -> dict[str, object]:
    provenance_path = segment_path.with_suffix(".provenance.json")
    if not provenance_path.is_file():
        raise ValueError("segment_source_provenance_missing")
    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("segment_source_provenance_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("segment_source_provenance_invalid")
    prepared = payload.get("prepared_sample")
    speaker_review = payload.get("speaker_review")
    exclusions = {
        str(item or "").strip()
        for item in list(payload.get("exclusions") or [])
        if str(item or "").strip()
    }
    if (
        payload.get("schema") != "ea.memorial.voice_clone_source_provenance.v1"
        or payload.get("status") != "reviewed"
        or payload.get("provider") != "unmixr"
        or not isinstance(prepared, dict)
        or not isinstance(speaker_review, dict)
        or speaker_review.get("single_speaker") is not True
        or str(prepared.get("sha256") or "") != str(segment.get("sha256") or "")
        or Path(str(prepared.get("path") or "")).name != segment_path.name
        or abs(
            float(prepared.get("duration_seconds") or 0.0)
            - float(segment.get("duration_seconds") or 0.0)
        )
        > 0.05
        or "other speakers" not in exclusions
        or "cross-recording concatenation" not in exclusions
    ):
        raise ValueError("segment_source_provenance_invalid")
    return {
        "path": provenance_path.as_posix(),
        "sha256": _sha256_file(provenance_path),
        "schema": str(payload.get("schema") or ""),
        "status": str(payload.get("status") or ""),
        "single_speaker": True,
        "cross_recording_concatenation": False,
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


def _load_unmixr_slots_from_live_env(
    requested_slot: str = "",
) -> tuple[str, ...]:
    requested = str(requested_slot or "").strip()
    existing = unmixr_api_key_slot_names()
    if existing and (not requested or requested in existing):
        return existing
    try:
        rendered_env = subprocess.check_output(
            ["docker", "exec", "ea-api", "env"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        rendered_env = ""
    for raw_line in rendered_env.splitlines():
        if "=" not in raw_line:
            continue
        name, value = raw_line.split("=", 1)
        if (
            name in {"UNMIXR_API_KEY", "UNMIXR_API_KEYS"}
            or re.fullmatch(r"UNMIXR_API_KEY_FALLBACK_[1-9][0-9]*", name)
        ):
            if value.strip() and name not in os.environ:
                os.environ[name] = value.strip()
    return unmixr_api_key_slot_names()


def build_packet(*, slug: str, voice_label: str, segment_paths: list[Path], output_dir: Path) -> dict[str, object]:
    if len(segment_paths) != 1:
        raise ValueError("single_prepared_segment_required")
    output_dir.mkdir(parents=True, exist_ok=True)
    segment = _segment_entry(segment_paths[0])
    provenance = _validated_provenance_entry(
        segment_path=segment_paths[0],
        segment=segment,
    )
    packet = {
        "generated_at": _utc_now(),
        "slug": slug,
        "voice_label": voice_label,
        "provider_key": "unmixr",
        "goal": "fresh_memorial_clone_refresh",
        "segments": [segment],
        "source_provenance": provenance,
        "clone_attempt": {},
    }
    return packet


def attempt_clone(
    *,
    slug: str,
    voice_label: str,
    segment_paths: list[Path],
    account_slot: str = "",
) -> dict[str, object]:
    if len(segment_paths) != 1:
        return {
            "status": "blocked",
            "code": "single_prepared_segment_required",
            "detail": "Unmixr requires one precomposed, speaker-reviewed sample.",
        }
    requested_slot = str(account_slot or "").strip()
    available_slots = _load_unmixr_slots_from_live_env(requested_slot)
    if not available_slots:
        return {
            "status": "blocked",
            "code": "unmixr_api_key_missing",
            "detail": "No Unmixr account slot available in local or live runtime env.",
        }
    if requested_slot and requested_slot not in available_slots:
        return {
            "status": "blocked",
            "code": "unmixr_account_slot_missing",
            "account_slot": requested_slot,
        }
    if not requested_slot and len(available_slots) > 1:
        return {
            "status": "blocked",
            "code": "unmixr_account_slot_required",
            "detail": (
                "Multiple Unmixr account slots are available; select one "
                "explicitly so the clone and all comparison renders remain "
                "bound to the same account."
            ),
        }
    selected_slot = requested_slot or available_slots[0]
    try:
        voice_id = unmixr_clone_request(
            slug=slug,
            voice_label=voice_label,
            sample_paths=segment_paths,
            account_slot=selected_slot,
        )
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
        "account_slot": selected_slot,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the next memorial Unmixr refresh clone packet and capture clone receipts.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--voice-label", default="Manfred Hoza Memorial Refresh")
    parser.add_argument("--segment", action="append", default=[])
    parser.add_argument("--attempt-clone", action="store_true")
    parser.add_argument("--account-slot", default="")
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
        payload["clone_attempt"] = attempt_clone(
            slug=slug,
            voice_label=voice_label,
            segment_paths=segment_paths,
            account_slot=str(args.account_slot or "").strip(),
        )
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
