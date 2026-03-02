from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "ea/schema/20260302_v1_13_onboarding.sql"
EGRESS = ROOT / "ea/app/net/egress_guard.py"
ONBOARD = ROOT / "ea/app/onboarding/service.py"
REGISTRY = ROOT / "ea/app/connectors/registry.py"

schema = SCHEMA.read_text(encoding="utf-8")
for table in (
    "tenant_invites",
    "onboarding_sessions",
    "principals",
    "channel_bindings",
    "oauth_connections",
    "source_connections",
    "source_test_runs",
    "tenant_provision_jobs",
    "onboarding_audit_events",
    "connector_network_modes",
):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
print("[SMOKE][HOST][PASS] v1.13 schema tables present")

for path in (EGRESS, ONBOARD, REGISTRY):
    src = path.read_text(encoding="utf-8")
    ast.parse(src)
print("[SMOKE][HOST][PASS] v1.13 modules parse")

assert "evaluate_connector_url" in EGRESS.read_text(encoding="utf-8")
assert "class OnboardingService" in ONBOARD.read_text(encoding="utf-8")
assert "CONNECTOR_REGISTRY" in REGISTRY.read_text(encoding="utf-8")
print("[SMOKE][HOST][PASS] v1.13 core symbols present")
