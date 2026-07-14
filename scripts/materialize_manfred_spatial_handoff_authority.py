#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_manfred_memorial_candidate import (  # noqa: E402
    SPATIAL_AUTHORITY_SCHEMA,
    materialize_spatial_handoff_authority,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a candidate-scoped Manfred spatial authority receipt and "
            "an exact sanitized six-file generated-viewer bundle."
        )
    )
    parser.add_argument("--source-bundle-dir", required=True)
    parser.add_argument("--sanitized-bundle-dir", required=True)
    parser.add_argument("--authority-receipt", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--target-origin", required=True)
    parser.add_argument("--user-instruction-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = materialize_spatial_handoff_authority(
            source_bundle_dir=Path(args.source_bundle_dir),
            sanitized_bundle_dir=Path(args.sanitized_bundle_dir),
            authority_receipt_path=Path(args.authority_receipt),
            slug=args.slug,
            source_commit=args.source_commit,
            target_origin=args.target_origin,
            user_instruction_sha256=args.user_instruction_sha256,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": SPATIAL_AUTHORITY_SCHEMA,
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
