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

from app.services.memorial_chatlab_integration import verify_chatlab_runtime_preflight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", "--receipt", dest="preflight", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    result = verify_chatlab_runtime_preflight(args.preflight)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
