#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


EA_APP_ROOT = Path(__file__).resolve().parents[1]
if str(EA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_APP_ROOT))

from app.services import memorial_archive_registry  # noqa: E402
from app.services.memorial_share_packet import (  # noqa: E402
    MemorialSharePacketError,
    SUPPORTED_CHANNELS,
    build_memorial_share_packet,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build recipient-free, unsent WhatsApp/Telegram drafts for an approved public memorial."
    )
    parser.add_argument("slug", help="public memorial slug")
    parser.add_argument(
        "--public-origin",
        required=True,
        help="explicit HTTPS origin used for all public links",
    )
    parser.add_argument(
        "--memorial-file",
        type=Path,
        help="raw memorial JSON; defaults to the configured public root",
    )
    parser.add_argument(
        "--archive-registry-file", type=Path, help="public archive registry JSON"
    )
    parser.add_argument(
        "--channel", action="append", choices=SUPPORTED_CHANNELS, dest="channels"
    )
    parser.add_argument(
        "--include-archive",
        action="store_true",
        help="include all approved public archive documents",
    )
    parser.add_argument(
        "--include-audio", action="store_true", help="include all approved public audio"
    )
    parser.add_argument(
        "--archive-id",
        action="append",
        default=[],
        help="include one approved public document ID",
    )
    parser.add_argument(
        "--audio-relpath",
        action="append",
        default=[],
        help="include one approved public audio path",
    )
    parser.add_argument(
        "--output", type=Path, help="write the packet locally instead of printing it"
    )
    return parser.parse_args(argv)


def _load_json_object(
    path: Path, *, missing_code: str, invalid_code: str
) -> dict[str, object]:
    if not path.is_file():
        raise MemorialSharePacketError(missing_code)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemorialSharePacketError(invalid_code) from exc
    if not isinstance(payload, dict):
        raise MemorialSharePacketError(invalid_code)
    return payload


def build_from_args(args: argparse.Namespace) -> dict[str, object]:
    memorial_path = args.memorial_file or (
        memorial_archive_registry.PUBLIC_MEMORIAL_ROOT
        / str(args.slug)
        / "memorial.json"
    )
    memorial = _load_json_object(
        memorial_path,
        missing_code="memorial_share_manifest_not_found",
        invalid_code="memorial_share_manifest_invalid",
    )
    archive_path = (
        args.archive_registry_file
        or memorial_archive_registry.public_registry_path(str(args.slug))
    )
    archive_requested = bool(args.include_archive or args.archive_id)
    if archive_path.is_file():
        archive_registry = _load_json_object(
            archive_path,
            missing_code="memorial_share_archive_registry_not_found",
            invalid_code="memorial_share_archive_registry_invalid",
        )
    elif archive_requested:
        raise MemorialSharePacketError("memorial_share_archive_registry_not_found")
    else:
        archive_registry = {}
    return build_memorial_share_packet(
        slug=str(args.slug),
        public_origin=str(args.public_origin),
        memorial=memorial,
        archive_registry=archive_registry,
        channels=args.channels,
        include_archive=bool(args.include_archive),
        include_audio=bool(args.include_audio),
        archive_ids=list(args.archive_id or []),
        audio_relpaths=list(args.audio_relpath or []),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        packet = build_from_args(args)
        serialized = (
            json.dumps(packet, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        )
        if args.output is None:
            sys.stdout.write(serialized)
        else:
            args.output.write_text(serialized, encoding="utf-8")
        return 0
    except (MemorialSharePacketError, OSError) as exc:
        code = (
            exc.code
            if isinstance(exc, MemorialSharePacketError)
            else "memorial_share_output_write_failed"
        )
        sys.stderr.write(
            json.dumps({"ok": False, "error": code}, sort_keys=True) + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
