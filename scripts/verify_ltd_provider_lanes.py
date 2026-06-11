#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA_PATH = ROOT / "ea"
for candidate in (ROOT, EA_PATH):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.services.ltd_provider_governance import (  # noqa: E402
    build_ltd_provider_governance_receipt,
    materialize_ltd_provider_governance_receipts,
)


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/verify_ltd_provider_lanes.py [--lane LANE_KEY] [--output-dir DIR] [--no-write]\n\n"
            "Verify governed LTD provider lanes and materialize proof/boundary receipts.\n"
            "With --lane, print and optionally write only the requested lane receipt."
        )
        return 0
    parser = argparse.ArgumentParser(
        description="Verify governed LTD provider lanes and materialize proof/boundary receipts."
    )
    parser.add_argument("--lane", default="", help="Optional lane key to materialize only one lane receipt.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "_completion" / "ltd_provider_lanes"),
        help="Receipt output directory.",
    )
    parser.add_argument("--no-write", action="store_true", help="Print the aggregate receipt without writing files.")
    args = parser.parse_args()

    if args.no_write:
        receipt = build_ltd_provider_governance_receipt()
    else:
        receipt = materialize_ltd_provider_governance_receipts(
            output_dir=Path(args.output_dir),
            lane_key=str(args.lane or "").strip() or None,
        )
    if str(args.lane or "").strip():
        normalized = str(args.lane or "").strip().lower().replace("-", "_")
        lane_receipts = [
            lane
            for lane in receipt.get("lanes", [])
            if str(lane.get("lane_key") or "").strip().lower() == normalized
        ]
        if not lane_receipts:
            raise SystemExit(f"ltd_provider_lane_receipt_missing:{args.lane}")
        printable: dict[str, object] = dict(lane_receipts[0])
    else:
        printable = receipt
    print(json.dumps(printable, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
