#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import re
from pathlib import Path
from typing import Any


UNMIXR_SERVICE_NAMES = {"unmixr", "unmixr ai"}
PRIMARY_SLOT = "UNMIXR_API_KEY"
FALLBACK_PREFIX = "UNMIXR_API_KEY_FALLBACK_"
LIST_SLOT = "UNMIXR_API_KEYS"
EXPLICIT_SLOT_RE = re.compile(r"\bUNMIXR_API_KEY(?:_FALLBACK_\d+)?\b")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    if set(stripped.replace("|", "").strip()) <= {"-", ":"}:
        return None
    return [part.strip().strip("`") for part in stripped.strip("|").split("|")]


def _service_name(value: object) -> str:
    return str(value or "").strip().strip("`").lower()


def _looks_like_account_alias(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text and EMAIL_RE.search(text))


def _slot_sort_key(slot_name: str) -> tuple[int, int | str]:
    if slot_name == PRIMARY_SLOT:
        return (0, 0)
    if slot_name.startswith(FALLBACK_PREFIX):
        try:
            return (1, int(slot_name[len(FALLBACK_PREFIX) :]))
        except ValueError:
            return (1, slot_name)
    if slot_name.startswith(f"{LIST_SLOT}_"):
        try:
            return (2, int(slot_name[len(LIST_SLOT) + 1 :]))
        except ValueError:
            return (2, slot_name)
    return (3, slot_name)


def parse_unmixr_accounts(markdown_text: str) -> list[dict[str, object]]:
    accounts: list[dict[str, object]] = []
    for line in markdown_text.splitlines():
        parts = _table_row(line)
        if not parts or _service_name(parts[0]) not in UNMIXR_SERVICE_NAMES:
            continue
        account_alias = parts[1].strip() if len(parts) > 1 else ""
        if not _looks_like_account_alias(account_alias):
            continue
        note = " | ".join(parts[2:])
        explicit_slots = EXPLICIT_SLOT_RE.findall(note)
        accounts.append(
            {
                "accountAlias": account_alias,
                "inventoryMentions": 1,
                "explicitExpectedEnvKeys": list(dict.fromkeys(explicit_slots)),
            }
        )
    return accounts


def parse_env_slots(env_text: str) -> dict[str, dict[str, object]]:
    slots: dict[str, dict[str, object]] = {}
    for line in env_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if key == PRIMARY_SLOT or key.startswith(FALLBACK_PREFIX) or key == LIST_SLOT:
            value = raw_value.strip()
            slots[key] = {
                "envKey": key,
                "present": True,
                "hasValue": bool(value),
                "kind": "list" if key == LIST_SLOT else "slot",
            }
    return dict(sorted(slots.items(), key=lambda item: _slot_sort_key(item[0])))


def _expected_slot_for_index(index: int) -> str:
    if index == 0:
        return PRIMARY_SLOT
    return f"{FALLBACK_PREFIX}{index}"


def build_audit(*, markdown_text: str, env_text: str, runtime_slots: list[str] | None = None) -> dict[str, object]:
    accounts = parse_unmixr_accounts(markdown_text)
    env_slots = parse_env_slots(env_text)
    assigned: list[dict[str, object]] = []
    used_slots: set[str] = set()

    for index, account in enumerate(accounts):
        explicit = [str(value) for value in account.get("explicitExpectedEnvKeys") or []]
        expected = explicit[0] if explicit else _expected_slot_for_index(index)
        used_slots.add(expected)
        env_slot = env_slots.get(expected, {})
        assigned.append(
            {
                "accountAlias": account["accountAlias"],
                "expectedEnvKey": expected,
                "explicitlyDeclaredInInventory": bool(explicit),
                "runtimeKeyPresent": bool(env_slot.get("present")),
                "runtimeKeyHasValue": bool(env_slot.get("hasValue")),
                "status": "configured" if env_slot.get("present") and env_slot.get("hasValue") else "missing_env_key",
            }
        )

    extra_env_slots = [
        {
            "envKey": key,
            "hasValue": bool(value.get("hasValue")),
            "status": "configured_without_inventory_alias" if value.get("hasValue") else "empty_without_inventory_alias",
        }
        for key, value in env_slots.items()
        if key not in used_slots
    ]
    missing = [row for row in assigned if row["status"] != "configured"]
    configured = [row for row in assigned if row["status"] == "configured"]
    runtime_slot_names = sorted(runtime_slots or [], key=_slot_sort_key)

    return {
        "contractName": "ea.unmixr_account_slot_audit.v1",
        "observedAtUtc": _now_iso(),
        "provider": "Unmixr AI",
        "inventoryAccountCount": len(accounts),
        "configuredInventoryAccountCount": len(configured),
        "missingInventoryAccountCount": len(missing),
        "envSlotCount": len(env_slots),
        "runtimeDiscoveredSlotCount": len(runtime_slot_names) if runtime_slots is not None else None,
        "runtimeDiscoveredSlots": runtime_slot_names,
        "accounts": assigned,
        "missingRuntimeKeys": missing,
        "extraEnvSlots": extra_env_slots,
        "genericSupport": {
            "numberedFallbackKeysSupported": True,
            "listKeySupported": True,
            "futureAccountsRequireCodeChange": False,
            "futureAccountEnvPattern": "UNMIXR_API_KEY_FALLBACK_N or UNMIXR_API_KEYS",
        },
        "secretsExposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Unmixr inventory accounts against configured API-key slots without exposing secrets.")
    parser.add_argument("--ltds", default="/docker/EA/LTDs.md")
    parser.add_argument("--env", default="/docker/EA/.env")
    parser.add_argument("--runtime-slots-json", default="", help="Optional JSON list of runtime-discovered slot names.")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    runtime_slots: list[str] | None = None
    if args.runtime_slots_json:
        parsed = json.loads(args.runtime_slots_json)
        if isinstance(parsed, list):
            runtime_slots = [str(item) for item in parsed]
    audit = build_audit(
        markdown_text=Path(args.ltds).read_text(encoding="utf-8"),
        env_text=Path(args.env).read_text(encoding="utf-8"),
        runtime_slots=runtime_slots,
    )
    payload = json.dumps(audit, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
