from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.assistant_property_boundary_cleanup import cleanup_hidden_property_runtime_state


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive lingering PropertyQuarry proactive OODA artifacts out of the EA assistant state."
    )
    parser.add_argument(
        "--state-path",
        default="state/proactive_ooda_notified.json",
        help="State path used to resolve proactive OODA artifact directories.",
    )
    parser.add_argument(
        "--archive-label",
        default="",
        help="Optional archive label for deterministic runs.",
    )
    args = parser.parse_args()
    result = cleanup_hidden_property_runtime_state(
        state_path=args.state_path,
        archive_label=args.archive_label,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
