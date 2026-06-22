#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPLETION_ROOT = Path(os.environ.get("MAGICFIT_PROVIDER_COMPLETION_ROOT") or ROOT / "ea/_completion/magicfit_provider")
DEFAULT_OUTPUT = DEFAULT_COMPLETION_ROOT / "MAGICFIT_ACCOUNT_INVENTORY.generated.json"
DEFAULT_PROVIDER_RECEIPT = DEFAULT_COMPLETION_ROOT / "MAGICFIT_PROVIDER_VERIFICATION.generated.json"
DEFAULT_ACCOUNT_EMAILS = (
    "magicfit-account-1@example.test",
    "magicfit-account-2@example.test",
    "magicfit-account-3@example.test",
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


def _configured_accounts(raw: str | None = None) -> tuple[str, ...]:
    source = (
        raw
        if raw is not None
        else os.environ.get("CHUMMER_EA_MAGICFIT_ACCOUNT_EMAILS")
        or os.environ.get("MAGICFIT_ACCOUNT_EMAILS")
        or ",".join(DEFAULT_ACCOUNT_EMAILS)
    )
    accounts: list[str] = []
    seen: set[str] = set()
    for value in str(source).split(","):
        account = value.strip().lower()
        if account and account not in seen:
            accounts.append(account)
            seen.add(account)
    return tuple(accounts)


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
    accounts: tuple[str, ...] | None = None,
) -> dict[str, object]:
    text = ltds_path.read_text(encoding="utf-8") if ltds_path.is_file() else ""
    proof_account = _provider_receipt_account(provider_receipt_path)
    depleted = depleted_account.strip().lower()
    configured_accounts = accounts or _configured_accounts()
    rows = []
    for account in configured_accounts:
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
        "account_count": len(configured_accounts),
        "functioning_account_count_user_reported": len(configured_accounts),
        "depleted_account_count_user_reported": 1 if depleted else 0,
        "usable_for_new_render_count_user_reported": max(0, len(configured_accounts) - (1 if depleted else 0)),
        "depleted_account_known": bool(depleted),
        "existing_provider_proof_account": proof_account,
        "accounts": rows,
        "inventory_recorded_in_ltds": all(account in text for account in configured_accounts)
        and "`MagicFit`" in text
        and f"`{len(configured_accounts)} accounts`" in text,
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
    parser.add_argument("--accounts", default="", help="Comma-separated MagicFit account emails; defaults to env.")
    args = parser.parse_args()
    payload = build_inventory(
        ltds_path=Path(args.ltds),
        provider_receipt_path=Path(args.provider_receipt),
        output_path=Path(args.output),
        depleted_account=str(args.depleted_account),
        accounts=_configured_accounts(str(args.accounts)) if str(args.accounts).strip() else None,
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
