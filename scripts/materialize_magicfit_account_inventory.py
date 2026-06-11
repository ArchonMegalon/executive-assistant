#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("/docker/chummercomplete/_completion/magicfit_provider/MAGICFIT_ACCOUNT_INVENTORY.generated.json")
DEFAULT_PROVIDER_RECEIPT = Path("/docker/chummercomplete/_completion/magicfit_provider/MAGICFIT_PROVIDER_VERIFICATION.generated.json")
ACCOUNTS = (
    "tibor.girschele@gmail.com",
    "the.girscheles@gmail.com",
    "archon.megalon@gmail.com",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _load_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _provider_receipt_account(path: Path) -> str:
    receipt = _load_json(path)
    account = receipt.get("account")
    if not isinstance(account, dict):
        return ""
    return str(account.get("account_user") or "").strip().lower()


def build_inventory(
    *,
    ltds_path: Path,
    provider_receipt_path: Path,
    output_path: Path,
    depleted_account: str = "",
) -> dict[str, object]:
    text = ltds_path.read_text(encoding="utf-8") if ltds_path.is_file() else ""
    proof_account = _provider_receipt_account(provider_receipt_path)
    depleted = depleted_account.strip().lower()
    rows = []
    for account in ACCOUNTS:
        normalized = account.lower()
        rows.append(
            {
                "account_user": account,
                "account_user_hash": _hash(account),
                "credential_committed": False,
                "functioning_user_reported": True,
                "credit_state": "depleted" if depleted == normalized else "available_or_unverified",
                "used_for_existing_provider_proof": proof_account == normalized,
            }
        )
    payload = {
        "contract_name": "executive_assistant.magicfit_account_inventory.v1",
        "generated_at": _utc_now(),
        "provider": "MagicFit",
        "license_tier": "License Tier 5",
        "account_count": len(ACCOUNTS),
        "functioning_account_count_user_reported": 3,
        "depleted_account_count_user_reported": 1,
        "usable_for_new_render_count_user_reported": 2,
        "depleted_account_known": bool(depleted),
        "existing_provider_proof_account": proof_account,
        "accounts": rows,
        "inventory_recorded_in_ltds": all(account in text for account in ACCOUNTS) and "`MagicFit`" in text and "`3 accounts`" in text,
        "secret_boundary": "Account passwords and session tokens stay in local runtime config only and must not be committed.",
        "runtime_boundary": "Account ownership and credits do not grant publish authority; MagicFit remains a candidate render lane behind provider and render receipts.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the MagicFit account inventory without committing account secrets.")
    parser.add_argument("--ltds", default=str(ROOT / "LTDs.md"))
    parser.add_argument("--provider-receipt", default=str(DEFAULT_PROVIDER_RECEIPT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--depleted-account", default="")
    args = parser.parse_args()
    payload = build_inventory(
        ltds_path=Path(args.ltds),
        provider_receipt_path=Path(args.provider_receipt),
        output_path=Path(args.output),
        depleted_account=str(args.depleted_account),
    )
    print(
        json.dumps(
            {
                "status": "pass",
                "output": str(args.output),
                "account_count": payload["account_count"],
                "usable_for_new_render_count_user_reported": payload["usable_for_new_render_count_user_reported"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
