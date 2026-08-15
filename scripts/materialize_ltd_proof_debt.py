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
from typing import Any

import yaml  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parents[1]
EA_PYTHON_ROOT = ROOT / "ea"
if str(EA_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_PYTHON_ROOT))

from app.services.ltd_runtime_catalog import load_ltd_inventory_rows  # type: ignore[import-untyped]  # noqa: E402


DEFAULT_OUTPUT = ROOT / ".codex-studio/published/LTD_PROOF_DEBT.generated.json"
ROUTER_PATH = ROOT / "config/ltd_capability_router.yaml"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _provider_name_matches(service_name: str, provider_name: str) -> bool:
    service = _normalize(service_name)
    provider = _normalize(provider_name)
    if service == provider:
        return True
    suffixes = ("_ai", "_io", "_dev", "_com", "_me")
    service_without_suffix = next(
        (service[: -len(suffix)] for suffix in suffixes if service.endswith(suffix)),
        service,
    )
    provider_without_suffix = next(
        (provider[: -len(suffix)] for suffix in suffixes if provider.endswith(suffix)),
        provider,
    )
    return service_without_suffix == provider_without_suffix


def _candidate_lane(service_name: str) -> str:
    if not ROUTER_PATH.is_file():
        return "inventory_review"
    config = yaml.safe_load(ROUTER_PATH.read_text(encoding="utf-8")) or {}
    for lane, raw in dict(config.get("named_lanes") or {}).items():
        providers = dict(raw or {}).get("providers") or []
        if any(_provider_name_matches(service_name, str(provider)) for provider in providers):
            return str(lane)
    for section in ("catalog_only", "transport_only"):
        for provider, raw in dict(config.get(section) or {}).items():
            if _provider_name_matches(service_name, str(provider)):
                return str(dict(raw or {}).get("lane") or section)
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


def build_payload(*, generated_at: str | None = None) -> dict[str, Any]:
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
        "truth_posture": "operator projection only; not product canon or provider proof",
        "secret_material_exposed": bool(),
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
