#!/usr/bin/env python3
"""Verify a vexp root-maintenance request without granting authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.vexp_root_maintenance_recovery_request import (  # noqa: E402
    REQUEST_CONTRACT,
    RecoveryRequestError,
    load_and_validate_request,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _payload, result = load_and_validate_request(
            args.request,
            repo_root=args.repo_root,
        )
    except RecoveryRequestError as exc:
        print(
            json.dumps(
                {
                    "authority": False,
                    "contract_name": REQUEST_CONTRACT,
                    "reason": str(exc),
                    "status": "blocked",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
