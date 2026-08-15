#!/usr/bin/env python3
"""Materialize secret-safe capacity readiness from the scheduler contract."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import yaml  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/ltd_capacity_scheduler.yaml"
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/LTD_CAPACITY_STATUS.generated.json"


def _local_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (ROOT / ".env", ROOT / ".env.local", ROOT / "ea/.env"):
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            normalized_key = key.strip()
            if normalized_key:
                values[normalized_key] = value.strip().strip('"').strip("'")
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def build_payload(*, env: dict[str, str] | None = None, generated_at: str | None = None) -> dict[str, object]:
    environment = _local_environment() if env is None else dict(env)
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    providers = []
    for name, raw in dict(config.get("providers") or {}).items():
        row = dict(raw or {})
        credential_env = str(row.get("credential_env") or "").strip()
        credential_present = bool(str(environment.get(credential_env) or "").strip())
        providers.append(
            {
                "provider": str(name),
                "configured_state": str(row.get("state") or ""),
                "credential_slot": credential_env,
                "credential_present": credential_present,
                "route_state": "eligible_for_health_probe" if credential_present else "omitted_empty_credential",
                "credit_balance_state": "unverified" if credential_present else "not_checked",
                "slot_health_state": "unverified" if credential_present else "not_checked",
                "dispatch_eligible": False,
                "maximum_blast_radius": str(row.get("maximum_blast_radius") or ""),
                "review_required": True,
            }
        )
    probe_candidates = sum(1 for row in providers if row["credential_present"])
    return {
        "contract": "ea.ltd_capacity_status.v1",
        "status": "ready_for_bounded_probe" if probe_candidates else "blocked_no_configured_provider",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
        "truth_posture": "credential-presence projection only; dispatch requires fresh credit, slot-health, privacy, and review receipts",
        "eligibility_scope": "health_probe_only",
        "eligible_provider_count": probe_candidates,
        "probe_candidate_count": probe_candidates,
        "dispatch_eligible_provider_count": 0,
        "secret_material_exposed": False,  # nosec B105
        "providers": providers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = build_payload()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
