#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path("/docker/EA")
COMPLETION_ROOT = Path("/docker/chummercomplete/_completion/ltd_inventory")
LTD_PATH = ROOT / "LTDs.md"
ARTIFACT_PATH = COMPLETION_ROOT / "MAGICFIT_TIER5_LTDS_ENTRY.generated.json"


REQUIRED_TOKENS = [
    "| `MagicFit` | `License Tier 5` | `3 accounts` | `Owned` |",
    "`tibor.girschele@gmail.com`; `the.girscheles@gmail.com`; `archon.megalon@gmail.com`",
    "- `48` total LTD products tracked",
    "`MagicFit` now has three tracked License Tier 5 accounts",
    "Account secrets must stay in local EA runtime config and must not be committed.",
]


def main() -> int:
    text = LTD_PATH.read_text(encoding="utf-8")
    missing = [token for token in REQUIRED_TOKENS if token not in text]
    COMPLETION_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "pass" if not missing else "fail",
        "service": "MagicFit",
        "plan": "License Tier 5",
        "account_count": 3,
        "accounts": ["tibor.girschele@gmail.com", "the.girscheles@gmail.com", "archon.megalon@gmail.com"],
        "workspace_integration_tier": "Tier 4",
        "verification_status": "pending_provider_verification",
        "missing_tokens": missing,
        "source_path": str(LTD_PATH),
    }
    ARTIFACT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if missing:
        raise SystemExit("Missing MagicFit LTD inventory tokens.")
    print(ARTIFACT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
