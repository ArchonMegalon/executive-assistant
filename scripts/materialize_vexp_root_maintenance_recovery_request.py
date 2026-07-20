#!/usr/bin/env python3
"""Materialize a source-only vexp root-maintenance handoff request."""

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
    DEFAULT_MANIFEST_PATH,
    REQUEST_CONTRACT,
    RecoveryRequestError,
    build_request,
    write_new_private_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--reviewed-commit", required=True)
    parser.add_argument("--operator-authorization", type=Path, required=True)
    parser.add_argument("--operator-authorization-reference", required=True)
    parser.add_argument("--operator-state-snapshot", type=Path, required=True)
    parser.add_argument("--manifest-path", default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        request = build_request(
            repo_root=args.repo_root,
            reviewed_commit=args.reviewed_commit,
            operator_authorization_path=args.operator_authorization,
            operator_authorization_reference=(
                args.operator_authorization_reference
            ),
            operator_state_snapshot_path=args.operator_state_snapshot,
            manifest_path=args.manifest_path,
        )
        write_new_private_json(args.output, request)
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
    print(
        json.dumps(
            {
                "authority": False,
                "contract_name": REQUEST_CONTRACT,
                "external_root_receipt_required": True,
                "request_identity": request["request_identity"],
                "status": request["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
