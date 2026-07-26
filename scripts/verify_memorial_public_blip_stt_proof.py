#!/usr/bin/env python3
"""Offline verifier for the governed public Blip STT proof."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    from scripts import materialize_memorial_public_blip_stt_proof as proof
except ImportError as exc:  # pragma: no cover - direct script execution
    if exc.name not in {
        "scripts",
        "scripts.materialize_memorial_public_blip_stt_proof",
    }:
        raise
    import materialize_memorial_public_blip_stt_proof as proof


def verify_proof(
    receipt_path: Path,
    *,
    challenge_ticket_path: Path,
    deployment_receipt_path: Path,
    operator_integrity_binding_path: Path,
    trusted_key_registry_path: Path,
    state_root: Path,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> dict[str, object]:
    return proof.verify_proof(
        receipt_path,
        challenge_ticket_path=challenge_ticket_path,
        deployment_receipt_path=deployment_receipt_path,
        operator_integrity_binding_path=operator_integrity_binding_path,
        trusted_key_registry_path=trusted_key_registry_path,
        state_root=state_root,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify signed proof, trusted registry, deployment binding, and nonce consumption."
    )
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--challenge-ticket", type=Path, required=True)
    parser.add_argument("--deployment-receipt", type=Path, required=True)
    parser.add_argument("--operator-integrity-binding", type=Path, required=True)
    parser.add_argument("--trusted-key-registry", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--expected-uid", type=int, default=os.geteuid())
    parser.add_argument("--expected-gid", type=int, default=os.getegid())
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    payload = verify_proof(
        args.receipt,
        challenge_ticket_path=args.challenge_ticket,
        deployment_receipt_path=args.deployment_receipt,
        operator_integrity_binding_path=args.operator_integrity_binding,
        trusted_key_registry_path=args.trusted_key_registry,
        state_root=args.state_root,
        expected_uid=args.expected_uid,
        expected_gid=args.expected_gid,
    )
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
