#!/usr/bin/env python3
"""Verify the LTD scheduler, blast-radius, and capability-router contracts."""

from __future__ import annotations

import json
from pathlib import Path

import yaml  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    failures: list[str] = []
    scheduler = yaml.safe_load((ROOT / "config/ltd_capacity_scheduler.yaml").read_text(encoding="utf-8"))
    blast = yaml.safe_load((ROOT / "config/ltd_blast_radius.yaml").read_text(encoding="utf-8"))
    router = yaml.safe_load((ROOT / "config/ltd_capability_router.yaml").read_text(encoding="utf-8"))
    if scheduler.get("default_policy") != "fail_closed":
        failures.append("scheduler_not_fail_closed")
    dimensions = set(scheduler.get("routing_dimensions") or [])
    required_dimensions = {"provider_capability", "credit_balance", "slot_health", "privacy_class", "human_review_requirement"}
    if not required_dimensions <= dimensions:
        failures.append("scheduler_dimensions_incomplete")
    magicx = dict((scheduler.get("providers") or {}).get("AI Magicx") or {})
    if magicx.get("empty_credential_action") != "omit_from_effective_order":
        failures.append("magicx_empty_key_not_omitted")
    classes = dict(blast.get("classes") or {})
    if not {"public_safe", "operator_internal", "private_sensitive", "regulated_or_high_risk"} <= set(classes):
        failures.append("blast_radius_classes_incomplete")
    policies = dict(blast.get("provider_policies") or {})
    if any(bool(dict(row or {}).get("may_own_truth")) for row in policies.values()):
        failures.append("provider_may_own_truth")
    rules = dict(router.get("hard_rules") or {})
    if rules.get("can_publish_directly") is not False or rules.get("can_own_truth") is not False:
        failures.append("router_truth_boundary_missing")
    lanes = dict(router.get("named_lanes") or {})
    required_lanes = {
        "release_trust_factory",
        "public_trust_shelf",
        "black_ledger_media_bakeoff",
        "background_capacity_scheduler",
        "cross_repo_opportunity_index",
        "proof_debt_operations",
        "meeting_to_decision",
        "no_desktop_onboarding_funnel",
        "runsite_walkthrough_artifacts",
        "audio_campaign_memory",
    }
    if not required_lanes <= set(lanes):
        failures.append("named_product_lanes_incomplete")
    payload = {"contract": "ea.verify_ltd_capacity_scheduler.v1", "status": "pass" if not failures else "fail", "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
