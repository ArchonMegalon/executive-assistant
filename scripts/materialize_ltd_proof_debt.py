#!/usr/bin/env python3
"""Materialize one honest next-proof row for every non-Tier-1 LTD."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
EA_PYTHON_ROOT = ROOT / "ea"
if str(EA_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_PYTHON_ROOT))

from app.services.ltd_runtime_catalog import load_ltd_inventory_rows


DEFAULT_OUTPUT = ROOT / ".codex-studio/published/LTD_PROOF_DEBT.generated.json"
ROUTER_PATH = ROOT / "config/ltd_capability_router.yaml"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _candidate_lane(service_name: str) -> str:
    text = ROUTER_PATH.read_text(encoding="utf-8") if ROUTER_PATH.is_file() else ""
    normalized_service = _normalize(service_name)
    current_lane = ""
    in_named_lanes = False
    for line in text.splitlines():
        if line == "named_lanes:":
            in_named_lanes = True
            continue
        if in_named_lanes and line and not line.startswith(" "):
            break
        lane_match = re.match(r"^  ([a-z0-9_]+):$", line)
        if lane_match:
            current_lane = lane_match.group(1)
            continue
        if current_lane and line.strip().startswith("providers:"):
            providers = [_normalize(value) for value in re.findall(r"[^,\[\]]+", line.split(":", 1)[1])]
            if normalized_service in providers:
                return current_lane
    return "inventory_review"


def _next_proof(tier: str, notes: str, local_integration: str) -> str:
    lowered = f"{notes} {local_integration}".lower()
    if "missing" in lowered or "none" == local_integration.strip().lower():
        return "capture account capability, privacy boundary, and bounded smoke receipt"
    if tier == "Tier 2":
        return "refresh provider/runtime receipt and re-run false-complete promotion gate"
    if tier == "Tier 3":
        return "capture bounded account-use and failure-mode receipt"
    return "capture provider contract, safe export, and human-review receipt"


def build_payload(*, generated_at: str | None = None) -> dict[str, object]:
    rows = []
    for item in load_ltd_inventory_rows(ROOT / "LTDs.md"):
        tier = str(item.workspace_integration_tier or "").strip()
        if tier not in {"Tier 2", "Tier 3", "Tier 4"}:
            continue
        rows.append(
            {
                "service": item.service_name,
                "current_workspace_tier": tier,
                "candidate_lane": _candidate_lane(item.service_name),
                "next_proof": _next_proof(tier, item.notes, item.local_integration),
                "must_not_claim": "runtime promotion, product truth, release truth, or direct publication without a fresh accepted receipt",
                "owner_review_required": True,
            }
        )
    rows.sort(key=lambda row: (str(row["current_workspace_tier"]), str(row["service"]).casefold()))
    inventory_sha = hashlib.sha256((ROOT / "LTDs.md").read_bytes()).hexdigest()
    return {
        "contract": "ea.ltd_proof_debt.v1",
        "status": "projection_ready" if rows else "blocked_empty_inventory",
        "generated_at": generated_at or _utc_now(),
        "source": "LTDs.md",
        "source_sha256": inventory_sha,
        "secret_material_exposed": False,
        "truth_posture": "operator projection only; not product canon or provider proof",
        "row_count": len(rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = build_payload()
    if args.check:
        if payload["status"] != "projection_ready":
            return 1
        for row in payload["rows"]:
            if not all(str(row.get(key) or "").strip() for key in ("service", "candidate_lane", "next_proof", "must_not_claim")):
                return 1
        print(json.dumps({"status": "pass", "row_count": payload["row_count"]}))
        return 0
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "row_count": payload["row_count"], "output": str(output)}))
    return 0 if payload["status"] == "projection_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
