#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Iterator


EA_APP = Path(__file__).resolve().parents[1] / "ea"
if str(EA_APP) not in sys.path:
    sys.path.insert(0, str(EA_APP))

from app.services import voice_runtime  # noqa: E402


UNMIXR_ENV_PREFIXES = ("UNMIXR_API_KEY", "UNMIXR_API_KEY_FALLBACK_", "UNMIXR_API_KEYS")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _slot_names() -> list[str]:
    return [name for name, _key in voice_runtime._unmixr_api_key_slots()]


def _is_unmixr_key_env(name: str) -> bool:
    return name == "UNMIXR_API_KEY" or name == "UNMIXR_API_KEYS" or name.startswith("UNMIXR_API_KEY_FALLBACK_")


def load_env_file(path: Path) -> list[str]:
    loaded: list[str] = []
    if not path.is_file():
        return loaded
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")
        loaded.append(key)
    return loaded


@contextmanager
def _single_slot_environment(slot_name: str) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in list(os.environ) if _is_unmixr_key_env(key)}
    try:
        selected = os.environ.get(slot_name)
        for key in list(original):
            os.environ.pop(key, None)
        if selected:
            os.environ[slot_name] = selected
        yield
    finally:
        for key in list(os.environ):
            if _is_unmixr_key_env(key):
                os.environ.pop(key, None)
        for key, value in original.items():
            if value is not None:
                os.environ[key] = value


def smoke_slots(
    *,
    live: bool,
    text: str,
    voice_id: str,
    language: str,
    only_slot: str = "",
) -> dict[str, object]:
    slots = _slot_names()
    if only_slot:
        slots = [slot for slot in slots if slot == only_slot]
    rows: list[dict[str, object]] = []
    for slot_name in slots:
        if not live:
            rows.append(
                {
                    "slotName": slot_name,
                    "status": "not_run_dry_run",
                    "wouldUseProvider": "Unmixr AI",
                    "audioProduced": False,
                }
            )
            continue
        try:
            with _single_slot_environment(slot_name):
                audio, content_type = voice_runtime.unmixr_synthesize_request(
                    text=text,
                    voice_id=voice_id,
                    lang=language,
                )
            rows.append(
                {
                    "slotName": slot_name,
                    "status": "pass" if audio else "failed_empty_audio",
                    "contentType": content_type,
                    "audioProduced": bool(audio),
                    "audioByteCount": len(audio),
                    "audioSha256": _sha256_bytes(audio) if audio else "",
                }
            )
        except Exception as exc:  # noqa: BLE001 - receipt should capture provider blocker class
            detail = str(getattr(exc, "detail", "") or exc)
            rows.append(
                {
                    "slotName": slot_name,
                    "status": "blocked",
                    "audioProduced": False,
                    "errorType": type(exc).__name__,
                    "errorDetail": detail[:240],
                    "errorDetailSha256": _sha256_bytes(detail.encode("utf-8")) if detail else "",
                }
            )
    return {
        "contractName": "ea.unmixr_slot_smoke_render_matrix.v1",
        "observedAtUtc": _now_iso(),
        "provider": "Unmixr AI",
        "mode": "live" if live else "dry_run",
        "slotCount": len(slots),
        "passedSlotCount": sum(1 for row in rows if row.get("status") == "pass"),
        "liveProviderCalled": live,
        "textSha256": _sha256_bytes(text.encode("utf-8")),
        "voiceIdPresent": bool(voice_id),
        "rawVoiceIdExposed": False,
        "slots": rows,
        "secretsExposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test configured Unmixr slots without exposing secrets.")
    parser.add_argument("--env-file", default="/docker/EA/.env", help="Load runtime env values before slot discovery; values are never printed.")
    parser.add_argument("--live", action="store_true", help="Actually call Unmixr. Omit for safe dry-run.")
    parser.add_argument("--text", default="Smoke test. One short sentence for account verification.")
    parser.add_argument("--voice-id", default=os.environ.get("UNMIXR_VOICE_ID", ""))
    parser.add_argument("--language", default=os.environ.get("UNMIXR_LANGUAGE", "en-US"))
    parser.add_argument("--only-slot", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    loaded_env_keys = load_env_file(Path(args.env_file)) if args.env_file else []
    voice_id = args.voice_id or os.environ.get("UNMIXR_VOICE_ID", "")
    language = args.language or os.environ.get("UNMIXR_LANGUAGE", "en-US")
    result = smoke_slots(
        live=args.live,
        text=args.text,
        voice_id=voice_id,
        language=language,
        only_slot=args.only_slot,
    )
    result["envFileLoaded"] = bool(loaded_env_keys)
    result["envFileLoadedKeyCount"] = len(loaded_env_keys)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["passedSlotCount"] or not args.live else 2


if __name__ == "__main__":
    raise SystemExit(main())
