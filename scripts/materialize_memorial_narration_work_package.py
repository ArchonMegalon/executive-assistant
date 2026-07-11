#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.memorial_narration_work_package import (  # noqa: E402
    materialize_memorial_narration_work_package,
    provider_safe_receipt,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize an offline, consent-gated memorial narration plan and a "
            "provider-safe receipt. This command never synthesizes audio."
        )
    )
    parser.add_argument("--slug", default="manfred")
    parser.add_argument(
        "--memorial-manifest",
        type=Path,
        default=ROOT / "memorial_data/public_memorials/manfred/memorial.json",
    )
    parser.add_argument(
        "--voice-profile",
        type=Path,
        default=ROOT / "memorial_data/private_memorial_profiles/manfred/tts_voice.json",
    )
    parser.add_argument(
        "--archive-registry",
        type=Path,
        default=ROOT / "memorial_data/public_memorials/manfred/archive_registry.json",
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=ROOT / "memorial_archive/manfred",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path)
    parser.add_argument("--max-chars", type=int, default=1200)
    return parser


def main() -> int:
    args = _parser().parse_args()
    package = materialize_memorial_narration_work_package(
        slug=args.slug,
        memorial_manifest_path=args.memorial_manifest,
        voice_profile_path=args.voice_profile,
        archive_registry_path=args.archive_registry,
        archive_root=args.archive_root,
        output_path=args.output,
        receipt_output_path=args.receipt_output,
        max_chars=args.max_chars,
    )
    print(
        json.dumps(provider_safe_receipt(package), ensure_ascii=False, sort_keys=True)
    )
    return 0 if package.get("render_authorized") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
