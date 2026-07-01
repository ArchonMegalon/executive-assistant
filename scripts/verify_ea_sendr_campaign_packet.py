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

from app.services.ea_outreach_policy import validate_sendr_campaign_packet  # noqa: E402


def verify(path: Path) -> dict[str, object]:
    packet = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise ValueError("sendr_campaign_packet_must_be_json_object")
    return validate_sendr_campaign_packet(packet)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a governed EA Sendr campaign packet.")
    parser.add_argument(
        "--packet",
        default=str(ROOT / ".codex-studio" / "published" / "ea_sendr_campaign_packet.generated.json"),
        help="Campaign packet JSON path.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print validation receipt.")
    args = parser.parse_args()
    receipt = verify(Path(args.packet))
    print(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
