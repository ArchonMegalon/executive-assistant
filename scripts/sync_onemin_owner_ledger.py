#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_FALLBACK_ENV_RE = re.compile(r"^ONEMIN_AI_API_KEY_FALLBACK_(\d+)$")


def _parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Synchronize the 1min owner ledger with the current ONEMIN_AI_API_KEY* values."
    )
    parser.add_argument("--dotenv", type=Path, default=root / ".env")
    parser.add_argument("--ledger", type=Path, default=root / "config" / "onemin_slot_owners.json")
    parser.add_argument("--write", action="store_true", help="Write the synchronized ledger back to --ledger.")
    return parser.parse_args()


def _strip_optional_quotes(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


def _load_dotenv_values(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"Dotenv file not found: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_optional_quotes(value)
    return values


def _discover_onemin_slots(values: dict[str, str]) -> list[dict[str, str]]:
    slots: list[dict[str, str]] = []
    primary = str(values.get("ONEMIN_AI_API_KEY") or "").strip()
    if primary:
        slots.append(
            {
                "slot": "primary",
                "account_name": "ONEMIN_AI_API_KEY",
                "secret_sha256": hashlib.sha256(primary.encode("utf-8")).hexdigest(),
            }
        )
    fallback_numbers: list[int] = []
    for key in values:
        match = _FALLBACK_ENV_RE.match(key)
        if match is None:
            continue
        try:
            fallback_numbers.append(int(match.group(1)))
        except ValueError:
            continue
    for number in sorted(set(fallback_numbers)):
        account_name = f"ONEMIN_AI_API_KEY_FALLBACK_{number}"
        secret = str(values.get(account_name) or "").strip()
        if not secret:
            continue
        slots.append(
            {
                "slot": f"fallback_{number}",
                "account_name": account_name,
                "secret_sha256": hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            }
        )
    return slots


def _load_owner_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        raise SystemExit(f"Owner ledger not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"slots": payload}
    raise SystemExit(f"Unsupported owner ledger format in {path}")


def _normalized_owner_rows(payload: dict[str, object]) -> list[dict[str, str]]:
    raw_rows = payload.get("slots") if isinstance(payload.get("slots"), list) else payload.get("owners")
    if not isinstance(raw_rows, list):
        raise SystemExit("Owner ledger must contain a top-level 'slots' or 'owners' list.")
    rows: list[dict[str, str]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        row = {
            "slot": str(raw_row.get("slot") or "").strip(),
            "account_name": str(raw_row.get("account_name") or raw_row.get("slot_env_name") or "").strip(),
            "secret_sha256": str(raw_row.get("secret_sha256") or raw_row.get("sha256") or "").strip().lower(),
            "owner_email": str(raw_row.get("owner_email") or raw_row.get("email") or "").strip(),
            "owner_name": str(raw_row.get("owner_name") or raw_row.get("name") or "").strip(),
            "owner_label": str(raw_row.get("owner_label") or "").strip(),
            "notes": str(raw_row.get("notes") or "").strip(),
        }
        if not any(row.values()):
            continue
        rows.append(row)
    return rows


def _synchronized_payload(payload: dict[str, object], env_slots: list[dict[str, str]]) -> dict[str, object]:
    owner_rows = _normalized_owner_rows(payload)
    rows_by_account = {
        row["account_name"]: row
        for row in owner_rows
        if row.get("account_name")
    }
    rows_by_slot = {
        row["slot"].lower(): row
        for row in owner_rows
        if row.get("slot")
    }
    ordered_rows = [row for row in owner_rows if not row.get("account_name") and not row.get("slot")]

    synced_rows: list[dict[str, str]] = []
    for env_slot in env_slots:
        row = rows_by_account.get(env_slot["account_name"])
        if row is None:
            row = rows_by_slot.get(env_slot["slot"].lower())
        if row is None and ordered_rows:
            row = ordered_rows.pop(0)
        row = dict(row or {})
        synced = {
            "slot": env_slot["slot"],
            "account_name": env_slot["account_name"],
            "secret_sha256": env_slot["secret_sha256"],
        }
        owner_email = str(row.get("owner_email") or "").strip()
        owner_name = str(row.get("owner_name") or "").strip()
        owner_label = str(row.get("owner_label") or "").strip()
        notes = str(row.get("notes") or "").strip()
        if owner_email:
            synced["owner_email"] = owner_email
        if owner_name:
            synced["owner_name"] = owner_name
        if owner_label and owner_label not in {owner_email, owner_name}:
            synced["owner_label"] = owner_label
        if notes:
            synced["notes"] = notes
        synced_rows.append(synced)

    if ordered_rows:
        raise SystemExit(
            f"Owner ledger has {len(ordered_rows)} unassigned row(s); add slot/account_name fields or trim stale entries first."
        )

    return {
        "hash_algorithm": "sha256",
        "slots": synced_rows,
    }


def main() -> int:
    args = _parse_args()
    env_values = _load_dotenv_values(args.dotenv)
    env_slots = _discover_onemin_slots(env_values)
    if not env_slots:
        raise SystemExit(f"No configured ONEMIN_AI_API_KEY* values were found in {args.dotenv}")
    payload = _load_owner_payload(args.ledger)
    synced = _synchronized_payload(payload, env_slots)
    rendered = json.dumps(synced, indent=2) + "\n"
    if args.write:
        args.ledger.write_text(rendered, encoding="utf-8")
        print(f"Synchronized {len(env_slots)} 1min slot owner entries into {args.ledger}")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
