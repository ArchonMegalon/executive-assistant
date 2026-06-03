#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


FLAGSHIP_REQUIRED = {
    "1min.AI": {"manual_seeded", "complete"},
    "Prompt Architects": {"manual_seeded", "complete"},
    "PayFunnels": {"manual_seeded", "complete"},
    "BrowserAct": {"complete"},
    "Teable": {"complete"},
    "ClickRank.ai": {"complete"},
    "Emailit": {"manual_seeded", "complete"},
    "Pixefy": {"manual_seeded", "complete"},
    "Rafter": {"manual_seeded", "complete"},
}

ACCEPTED_SOURCES = {
    "1min.AI": {"local_env_browseract_refresh"},
    "Prompt Architects": {"local_env + prompt_foundry_receipts"},
    "PayFunnels": {"payfunnels_test_billing_receipts"},
    "BrowserAct": {"browseract_live"},
    "Teable": {"browseract_live"},
    "ClickRank.ai": {"clickrank_live"},
    "Emailit": {"emailit_api_live"},
    "Pixefy": {"fleet_verified"},
    "Rafter": {"fleet_verified"},
}

MIN_ACCEPTED_COUNT = 9


def _extract_discovery_rows(markdown_text: str) -> dict[str, dict[str, str]]:
    lines = markdown_text.splitlines()
    rows: dict[str, dict[str, str]] = {}
    in_section = False
    for raw_line in lines:
        line = raw_line.rstrip()
        if line.startswith("## Discovery Tracking"):
            in_section = True
            continue
        if in_section and line.startswith("## ") and not line.startswith("## Discovery Tracking"):
            break
        if not in_section or not line.startswith("|"):
            continue
        if line.startswith("|---"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) != 6 or parts[0] == "Service":
            continue
        service = parts[0].strip().strip("`")
        rows[service] = {
            "account": parts[1],
            "discovery_status": parts[2].strip("`"),
            "verification_source": parts[3].strip("`"),
            "last_verified": parts[4],
            "notes": parts[5],
        }
    return rows


def build_receipt(*, markdown_text: str) -> dict[str, object]:
    rows = _extract_discovery_rows(markdown_text)
    failures: list[str] = []
    accepted_total = 0
    service_checks: dict[str, dict[str, object]] = {}
    for service, accepted_statuses in FLAGSHIP_REQUIRED.items():
        row = rows.get(service)
        status = str((row or {}).get("discovery_status") or "").strip()
        source = str((row or {}).get("verification_source") or "").strip()
        accepted = bool(row) and status in accepted_statuses and source in ACCEPTED_SOURCES[service]
        if accepted:
            accepted_total += 1
        else:
            failures.append(f"flagship_subset_mismatch:{service}:{status or 'missing'}:{source or 'missing'}")
        service_checks[service] = {
            "present": bool(row),
            "status": status,
            "source": source,
            "accepted": accepted,
        }
    if accepted_total < MIN_ACCEPTED_COUNT:
        failures.append(f"flagship_subset_coverage_below_floor:{accepted_total}<{MIN_ACCEPTED_COUNT}")
    return {
        "contract_name": "ea.verify_ltd_flagship_subset",
        "status": "pass" if not failures else "fail",
        "accepted_total": accepted_total,
        "minimum_required": MIN_ACCEPTED_COUNT,
        "services": service_checks,
        "failures": failures,
    }


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/verify_ltd_flagship_subset.py\n\n"
            "Fail closed when the named flagship LTD subset drifts away from its\n"
            "accepted verification sources or minimum coverage floor."
        )
        return 0
    root = Path(__file__).resolve().parents[1]
    markdown_text = (root / "LTDs.md").read_text(encoding="utf-8")
    receipt = build_receipt(markdown_text=markdown_text)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
