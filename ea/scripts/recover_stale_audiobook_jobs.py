from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"

if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply safe local recovery to stale audiobook jobs without external sends.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of job manifests to inspect.")
    parser.add_argument(
        "--oldest-first",
        action="store_true",
        help="Inspect oldest manifests first. Default is newest-first.",
    )
    args = parser.parse_args()

    from app.services import audiobook_epub_pipeline

    result = audiobook_epub_pipeline.recover_stale_audiobook_jobs_without_external_side_effects(
        newest_first=not bool(args.oldest_first),
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
