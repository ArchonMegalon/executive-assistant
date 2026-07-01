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

from app.services.ea_outreach_receipts import build_sendr_campaign_receipt  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a governed EA Sendr campaign receipt.")
    parser.add_argument(
        "--packet",
        default=str(ROOT / ".codex-studio" / "published" / "ea_sendr_campaign_packet.generated.json"),
        help="Campaign packet JSON path.",
    )
    parser.add_argument("--recipients", default="", help="Optional recipients JSON path.")
    parser.add_argument("--dry-run", action="store_true", help="Keep the receipt in non-send review mode.")
    parser.add_argument("--output", default="", help="Optional output path.")
    args = parser.parse_args()
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    recipients = []
    if args.recipients:
        loaded = json.loads(Path(args.recipients).read_text(encoding="utf-8"))
        recipients = loaded if isinstance(loaded, list) else loaded.get("recipients", [])
    receipt = build_sendr_campaign_receipt(packet, recipients=recipients, dry_run=bool(args.dry_run))
    packet_id = str(packet.get("packet_id") or "unknown").replace("/", "_")
    output_path = Path(args.output) if args.output else ROOT / ".codex-studio" / "published" / f"ea_sendr_campaign_{packet_id}.generated.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["validation_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
