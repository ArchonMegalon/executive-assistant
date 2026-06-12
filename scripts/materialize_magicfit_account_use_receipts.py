#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "ea/_completion/magicfit"
ACCOUNTS = (
    "tibor.girschele@gmail.com",
    "the.girscheles@gmail.com",
    "archon.megalon@gmail.com",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _slug(account: str) -> str:
    return account.lower().replace("@", "_at_").replace(".", "_")


def build_receipt(
    *,
    account: str,
    output_dir: Path,
    status: str,
    render_receipt: str = "",
    generated_at: str | None = None,
) -> dict[str, object]:
    normalized = account.strip().lower()
    if normalized not in ACCOUNTS:
        raise ValueError(f"unknown_magicfit_account:{account}")
    state = status.strip().lower()
    if state not in {"pass", "pending_account_use"}:
        raise ValueError("status must be pass or pending_account_use")
    passed = state == "pass"
    payload = {
        "contract_name": "executive_assistant.magicfit_account_use_receipt.v1",
        "generated_at": generated_at or _utc_now(),
        "provider": "MagicFit",
        "account_user_hash": _hash(normalized),
        "account_user_redacted": normalized[:1] + "***@" + normalized.split("@", 1)[1],
        "status": "pass" if passed else "pending_account_use",
        "asset_provenance_claim_allowed": passed,
        "render_receipt": render_receipt if passed else "",
        "secret_boundary": "Account credentials, cookies, and session tokens stay in local runtime config only.",
        "source_of_truth_boundary": "This receipt proves account-use provenance only; EA/Chummer storyboards, safety scans, and human review own publication truth.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"MAGICFIT_ACCOUNT_USE_{_slug(normalized).upper()}.generated.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize MagicFit account-use receipts without committing account secrets.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--status", choices=("pending_account_use", "pass"), default="pending_account_use")
    parser.add_argument("--render-receipt", default="")
    args = parser.parse_args()
    receipts = [
        build_receipt(
            account=account,
            output_dir=Path(args.output_dir),
            status=str(args.status),
            render_receipt=str(args.render_receipt),
        )
        for account in ACCOUNTS
    ]
    print(
        json.dumps(
            {
                "status": "pass",
                "output_dir": str(args.output_dir),
                "receipt_count": len(receipts),
                "asset_provenance_claim_allowed_count": sum(
                    1 for receipt in receipts if receipt["asset_provenance_claim_allowed"]
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
