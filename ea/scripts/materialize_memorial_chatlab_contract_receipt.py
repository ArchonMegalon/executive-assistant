from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_chatlab_contract.generated.json"

if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.memorial_chatlab_integration import materialize_chatlab_contract_receipt


def materialize_memorial_chatlab_contract_receipt(
    *,
    receipt_path: Path = DEFAULT_RECEIPT,
    slug: str = "manfred",
    generated_at: str | None = None,
) -> dict[str, object]:
    return materialize_chatlab_contract_receipt(
        receipt_path=receipt_path,
        slug=slug,
        generated_at=generated_at,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args()
    receipt = materialize_memorial_chatlab_contract_receipt(
        receipt_path=args.receipt,
        slug=args.slug,
        generated_at=args.generated_at,
    )
    print(json.dumps({"status": receipt["status"], "receipt": args.receipt.as_posix()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
