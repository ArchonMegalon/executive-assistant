#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

if __package__:
    from scripts.memorial_spatial_public_origin_contract import (
        validate_memorial_spatial_public_origin_receipt,
    )
    from scripts.source_state_head import (
        resolve_source_state_head,
        resolve_source_worktree_fingerprint,
    )
else:  # pragma: no cover - direct script execution
    from memorial_spatial_public_origin_contract import (
        validate_memorial_spatial_public_origin_receipt,
    )
    from source_state_head import (
        resolve_source_state_head,
        resolve_source_worktree_fingerprint,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = (
    ROOT
    / ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json"
)


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def verify(path: Path = DEFAULT_RECEIPT) -> list[str]:
    return validate_memorial_spatial_public_origin_receipt(
        _load(path),
        current_head=resolve_source_state_head(ROOT),
        current_fingerprint=resolve_source_worktree_fingerprint(ROOT),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the strict Manfred public-origin spatial-tour receipt."
    )
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args(argv)
    issues = verify(args.receipt)
    if issues:
        print(json.dumps({"status": "blocked", "issues": issues}, indent=2))
        return 1
    print(json.dumps({"status": "pass", "receipt": args.receipt.as_posix()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
