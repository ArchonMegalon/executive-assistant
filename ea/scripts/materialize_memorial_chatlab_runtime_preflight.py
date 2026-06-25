from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_chatlab_runtime_preflight.generated.json"

if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.memorial_chatlab_integration import write_chatlab_runtime_preflight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--external-evidence", type=Path, default=None)
    args = parser.parse_args()
    receipt = write_chatlab_runtime_preflight(
        output_path=args.out,
        slug=args.slug,
        generated_at=args.generated_at,
        external_evidence_path=args.external_evidence,
    )
    print(json.dumps({"status": receipt["status"], "receipt_path": args.out.as_posix()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
