from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "ea/schema/20260303_v1_18_planner.sql"
PLANNER = ROOT / "ea/app/planner/proactive.py"

schema = SCHEMA.read_text(encoding="utf-8")
for table in (
    "planner_jobs",
    "planner_candidates",
    "proactive_items",
    "proactive_muted_classes",
    "send_budgets",
    "quiet_hours",
    "channel_prefs",
    "urgency_policies",
    "planner_breakers",
    "planner_dedupe_keys",
    "planner_budget_windows",
):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
print("[SMOKE][HOST][PASS] v1.18 schema tables present")

ast.parse(PLANNER.read_text(encoding="utf-8"))
print("[SMOKE][HOST][PASS] v1.18 planner parses")
