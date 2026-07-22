#!/usr/bin/env python3
"""Validate and transport a Property-owned spatial publication package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_manfred_memorial_candidate import (  # noqa: E402
    SPATIAL_HANDOFF_SCHEMA,
    materialize_spatial_handoff,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the pinned PropertyQuarry publication package, copy its "
            "six public files byte-for-byte, and emit a separate non-authoritative "
            "EA candidate handoff receipt."
        )
    )
    parser.add_argument("--source-bundle-dir", required=True)
    parser.add_argument("--upstream-authority-receipt", required=True)
    parser.add_argument("--handoff-bundle-dir", required=True)
    parser.add_argument("--handoff-receipt", required=True)
    parser.add_argument("--target-origin", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = materialize_spatial_handoff(
            source_bundle_dir=Path(args.source_bundle_dir),
            upstream_authority_receipt_path=Path(
                args.upstream_authority_receipt
            ),
            handoff_bundle_dir=Path(args.handoff_bundle_dir),
            handoff_receipt_path=Path(args.handoff_receipt),
            target_origin=args.target_origin,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": SPATIAL_HANDOFF_SCHEMA,
                    "status": "fail",
                    "error": str(exc)[:200],
                    "candidate_handoff_authorized": False,
                    "public_activation_authority": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
