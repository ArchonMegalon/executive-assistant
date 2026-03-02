from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "ea/schema/20260303_v1_17_personalization.sql"
ENGINE = ROOT / "ea/app/personalization/engine.py"

schema = SCHEMA.read_text(encoding="utf-8")
for table in (
    "user_interest_profiles",
    "tenant_interest_defaults",
    "ranking_explanations",
    "entities",
    "entity_aliases",
    "ai_error_reviews",
    "feedback_caps",
    "anomaly_flags",
):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
print("[SMOKE][HOST][PASS] v1.17 schema tables present")

ast.parse(ENGINE.read_text(encoding="utf-8"))
print("[SMOKE][HOST][PASS] v1.17 engine parses")
