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

from app.domain.outreach.sendr_campaign import build_sendr_campaign_packet  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a governed EA Sendr campaign packet.")
    parser.add_argument("--type", required=True, dest="campaign_type", help="EA Sendr campaign type.")
    parser.add_argument("--packet", required=True, dest="packet_id", help="Packet id.")
    parser.add_argument("--target-audience", default="", help="Optional target audience override.")
    parser.add_argument("--expires-at", default="", help="Optional ISO expiry timestamp.")
    parser.add_argument(
        "--output",
        default=str(ROOT / ".codex-studio" / "published" / "ea_sendr_campaign_packet.generated.json"),
        help="Output packet JSON path.",
    )
    args = parser.parse_args()
    packet = build_sendr_campaign_packet(
        campaign_type=args.campaign_type,
        packet_id=args.packet_id,
        target_audience=args.target_audience or None,
        expires_at=args.expires_at or None,
        root=ROOT,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
