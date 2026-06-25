from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_chatlab_external_evidence.generated.json"

if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.memorial_chatlab_integration import write_chatlab_external_evidence_receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--provider-key", default="chatlab")
    parser.add_argument("--account-capability-evidence", default="")
    parser.add_argument("--runtime-probe-evidence", default="")
    parser.add_argument("--no-private-context-evidence", default="")
    parser.add_argument("--guardrail-preservation-evidence", default="")
    parser.add_argument("--observed-at", default=None)
    args = parser.parse_args()
    receipt = write_chatlab_external_evidence_receipt(
        output_path=args.out,
        slug=args.slug,
        provider_key=args.provider_key,
        account_capability_evidence=args.account_capability_evidence,
        runtime_probe_evidence=args.runtime_probe_evidence,
        no_private_context_evidence=args.no_private_context_evidence,
        guardrail_preservation_evidence=args.guardrail_preservation_evidence,
        observed_at=args.observed_at,
    )
    print(json.dumps({**receipt, "receipt_path": args.out.as_posix()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
