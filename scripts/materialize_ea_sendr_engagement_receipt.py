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

from app.services.ea_outreach_receipts import build_sendr_engagement_receipt  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize an EA Sendr engagement receipt.")
    parser.add_argument("--campaign-id", required=True, help="EA/Sendr campaign id.")
    parser.add_argument("--events", required=True, help="Events JSON path.")
    parser.add_argument("--event-batch-id", default="", help="Optional batch id.")
    parser.add_argument(
        "--output",
        default=str(ROOT / ".codex-studio" / "published" / "ea_sendr_engagement_batch.generated.json"),
        help="Output receipt JSON path.",
    )
    args = parser.parse_args()
    loaded = json.loads(Path(args.events).read_text(encoding="utf-8"))
    events = loaded if isinstance(loaded, list) else loaded.get("events", [])
    receipt = build_sendr_engagement_receipt(
        campaign_id=args.campaign_id,
        events=events,
        event_batch_id=args.event_batch_id or None,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
