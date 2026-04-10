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


def _manifest_file_path(values: dict[str, str], *, dotenv_path: Path) -> Path | None:
    raw = str(values.get("ONEMIN_DIRECT_API_KEYS_JSON_FILE") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw)
    except Exception:
        return None
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
        if str(path).startswith("/config/"):
            candidates.append(dotenv_path.parent / "config" / path.name)
    else:
        candidates.extend(
            [
                dotenv_path.parent / path,
                path,
            ]
        )
    seen: set[Path] = set()
    for candidate in candidates:
        normalized = candidate.resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        if normalized.exists():
            return normalized
    return None


def _load_onemin_manifest_payload(values: dict[str, str], *, dotenv_path: Path) -> object:
    inline = str(values.get("ONEMIN_DIRECT_API_KEYS_JSON") or "").strip()
    if inline:
        try:
            return json.loads(inline)
        except Exception:
            return None
    path = _manifest_file_path(values, dotenv_path=dotenv_path)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _fallback_number_from_slot(raw: object) -> int | None:
    normalized = str(raw or "").strip()
    env_match = _FALLBACK_ENV_RE.match(normalized)
    if env_match is not None:
        try:
            number = int(env_match.group(1))
        except Exception:
            number = None
        if number is not None and number >= 1:
            return number
    text = normalized.lower().replace(" ", "_").replace("-", "_")
    if not text:
        return None
    match = re.fullmatch(r"fallback_?(\d+)", text)
    if match is None:
        return None
    try:
        number = int(match.group(1))
    except Exception:
        return None
    return number if number >= 1 else None


def _manifest_slots(values: dict[str, str], *, dotenv_path: Path) -> list[dict[str, str]]:
    payload = _load_onemin_manifest_payload(values, dotenv_path=dotenv_path)
    if isinstance(payload, dict):
        if isinstance(payload.get("slots"), list):
            items = payload.get("slots") or []
        elif isinstance(payload.get("keys"), list):
            items = payload.get("keys") or []
        elif isinstance(payload.get("accounts"), list):
            items = payload.get("accounts") or []
        else:
            items = []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    fallback_numbers: set[int] = set()
    for key in values:
        match = _FALLBACK_ENV_RE.match(key)
        if match is None:
            continue
        try:
            fallback_numbers.add(int(match.group(1)))
        except ValueError:
            continue
    next_fallback = max(fallback_numbers, default=0) + 1

    slots: list[dict[str, str]] = []
    seen_account_names: set[str] = set()
    for item in items:
        slot = ""
        account_name = ""
        key = ""
        owner_email = ""
        owner_name = ""
        owner_label = ""
        notes = ""
        if isinstance(item, str):
            key = str(item or "").strip()
        elif isinstance(item, dict):
            key = str(
                item.get("key")
                or item.get("secret")
                or item.get("api_key")
                or item.get("value")
                or item.get("token")
                or ""
            ).strip()
            slot = str(item.get("slot") or item.get("slot_name") or "").strip()
            account_name = str(item.get("account_name") or item.get("name") or "").strip()
            owner_email = str(item.get("owner_email") or item.get("email") or "").strip()
            owner_name = str(item.get("owner_name") or item.get("display_name") or "").strip()
            owner_label = str(item.get("owner_label") or "").strip()
            notes = str(item.get("notes") or "").strip()
        if not key:
            continue
        slot_number = _fallback_number_from_slot(slot) or _fallback_number_from_slot(account_name)
        normalized_account_name = account_name
        if not normalized_account_name:
            if str(slot or "").strip().lower() == "primary":
                normalized_account_name = "ONEMIN_AI_API_KEY"
            elif slot_number is not None:
                normalized_account_name = f"ONEMIN_AI_API_KEY_FALLBACK_{slot_number}"
            else:
                normalized_account_name = f"ONEMIN_AI_API_KEY_FALLBACK_{next_fallback}"
                next_fallback += 1
        if normalized_account_name in seen_account_names:
            continue
        seen_account_names.add(normalized_account_name)
        normalized_slot = "primary" if normalized_account_name == "ONEMIN_AI_API_KEY" else ""
        if not normalized_slot:
            derived_number = _fallback_number_from_slot(slot) or _fallback_number_from_slot(normalized_account_name)
            if derived_number is not None:
                normalized_slot = f"fallback_{derived_number}"
        row = {
            "slot": normalized_slot or normalized_account_name.lower(),
            "account_name": normalized_account_name,
            "secret_sha256": hashlib.sha256(key.encode("utf-8")).hexdigest(),
        }
        if owner_email:
            row["owner_email"] = owner_email
        if owner_name:
            row["owner_name"] = owner_name
        if owner_label:
            row["owner_label"] = owner_label
        if notes:
            row["notes"] = notes
        slots.append(row)
    return slots


def _discover_onemin_slots(values: dict[str, str], *, dotenv_path: Path) -> list[dict[str, str]]:
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
    slots.extend(_manifest_slots(values, dotenv_path=dotenv_path))
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
        if not owner_email:
            owner_email = str(env_slot.get("owner_email") or "").strip()
        if not owner_name:
            owner_name = str(env_slot.get("owner_name") or "").strip()
        if not owner_label:
            owner_label = str(env_slot.get("owner_label") or "").strip()
        if not notes:
            notes = str(env_slot.get("notes") or "").strip()
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
    env_slots = _discover_onemin_slots(env_values, dotenv_path=args.dotenv)
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
