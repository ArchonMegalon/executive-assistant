from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "ea/schema/20260303_v1_14_trust.sql"
VAULT = ROOT / "ea/app/evidence_vault/service.py"
TRUST = ROOT / "ea/app/operator/trust_service.py"
REPLAY = ROOT / "ea/app/repair/replay_worker.py"
EPICS = ROOT / "ea/app/intelligence/epics.py"
MODES = ROOT / "ea/app/intelligence/modes.py"
BRIEFINGS = ROOT / "ea/app/briefings.py"
HUMAN_COMPOSE = ROOT / "ea/app/intelligence/human_compose.py"

schema = SCHEMA.read_text(encoding="utf-8")
for table in (
    "review_claims",
    "evidence_reveals",
    "dead_letter_items",
    "dead_letter_envelopes",
    "evidence_vault_objects",
    "deletion_tombstones",
    "connector_health",
    "breaker_history",
    "operator_audit_events",
):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
print("[SMOKE][HOST][PASS] v1.14 schema tables present")

for path in (VAULT, TRUST, REPLAY, EPICS, MODES):
    ast.parse(path.read_text(encoding="utf-8"))
print("[SMOKE][HOST][PASS] v1.14 modules parse")

epics_src = EPICS.read_text(encoding="utf-8")
assert "class Epic" in epics_src
assert "def build_epics_from_dossiers(" in epics_src
assert "def summarize_epic_deltas(" in epics_src
assert "def rank_epics(" in epics_src
assert "def load_epic_snapshot(" in epics_src
assert "def save_epic_snapshot(" in epics_src

modes_src = MODES.read_text(encoding="utf-8")
assert "def select_briefing_mode(" in modes_src
assert "epics:" in modes_src
assert "epic_focus_mode" in modes_src

brief_src = BRIEFINGS.read_text(encoding="utf-8")
compose_src = HUMAN_COMPOSE.read_text(encoding="utf-8")
assert "from app.intelligence.epics import (" in brief_src
assert "build_epics_from_dossiers(profile_ctx, dossiers)" in brief_src
assert "summarize_epic_deltas(previous_epics, epics)" in brief_src
assert "save_epic_snapshot(epic_snapshot_path, epics)" in brief_src
assert "from app.intelligence.human_compose import compose_briefing_html" in brief_src
assert "<b>Active Epics:</b>" in compose_src
assert "<b>What Changed:</b>" in compose_src
print("[SMOKE][HOST][PASS] v1.14 epic narrative contracts wired")
