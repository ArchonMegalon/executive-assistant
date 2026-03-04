from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "ea/schema/20260302_v1_13_onboarding.sql"
EGRESS = ROOT / "ea/app/net/egress_guard.py"
ONBOARD = ROOT / "ea/app/onboarding/service.py"
REGISTRY = ROOT / "ea/app/connectors/registry.py"
PROFILE_CORE = ROOT / "ea/app/intelligence/profile.py"
DOSSIERS = ROOT / "ea/app/intelligence/dossiers.py"
CRITICAL_LANE = ROOT / "ea/app/intelligence/critical_lane.py"
HOUSEHOLD_GRAPH = ROOT / "ea/app/intelligence/household_graph.py"
MODES = ROOT / "ea/app/intelligence/modes.py"
FUTURE_SITUATIONS = ROOT / "ea/app/intelligence/future_situations.py"
READINESS = ROOT / "ea/app/intelligence/readiness.py"
SCORES = ROOT / "ea/app/intelligence/scores.py"
PREP_PLANNER = ROOT / "ea/app/intelligence/preparation_planner.py"

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
onboard_src = ONBOARD.read_text(encoding="utf-8")
assert "class OnboardingService" in onboard_src
assert "def _upsert_channel_binding" in onboard_src
assert "ON CONFLICT DO NOTHING" in onboard_src
assert "DELETE FROM channel_bindings" in onboard_src
assert "CONNECTOR_REGISTRY" in REGISTRY.read_text(encoding="utf-8")
print("[SMOKE][HOST][PASS] v1.13 core symbols present")

for path in (
    PROFILE_CORE,
    DOSSIERS,
    CRITICAL_LANE,
    HOUSEHOLD_GRAPH,
    MODES,
    FUTURE_SITUATIONS,
    READINESS,
    SCORES,
    PREP_PLANNER,
):
    src = path.read_text(encoding="utf-8")
    ast.parse(src)
print("[SMOKE][HOST][PASS] v1.13 profile intelligence modules parse")

profile_src = PROFILE_CORE.read_text(encoding="utf-8")
assert "class PersonProfileContext" in profile_src
assert "def build_profile_context(" in profile_src
dossiers_src = DOSSIERS.read_text(encoding="utf-8")
assert "class Dossier" in dossiers_src
assert "def build_trip_dossier(" in dossiers_src
critical_src = CRITICAL_LANE.read_text(encoding="utf-8")
assert "class CriticalLaneResult" in critical_src
assert "def build_critical_actions(" in critical_src
household_src = HOUSEHOLD_GRAPH.read_text(encoding="utf-8")
assert "class HouseholdGraph" in household_src
assert "def build_household_graph(" in household_src
assert "def ensure_profile_isolation(" in household_src
modes_src = MODES.read_text(encoding="utf-8")
assert "def select_briefing_mode(" in modes_src
assert "def mode_label(" in modes_src
future_src = FUTURE_SITUATIONS.read_text(encoding="utf-8")
assert "class FutureSituation" in future_src
assert "def build_future_situations(" in future_src
readiness_src = READINESS.read_text(encoding="utf-8")
assert "class ReadinessDossier" in readiness_src
assert "def build_readiness_dossier(" in readiness_src
scores_src = SCORES.read_text(encoding="utf-8")
assert "def exposure_score(" in scores_src
assert "def decision_window_score(" in scores_src
assert "def readiness_score(" in scores_src
prep_src = PREP_PLANNER.read_text(encoding="utf-8")
assert "class PreparationPlan" in prep_src
assert "def build_preparation_plan(" in prep_src
print("[SMOKE][HOST][PASS] v1.13 profile intelligence symbols present")

import sys
sys.path.insert(0, str(ROOT / "ea"))
from app.intelligence.household_graph import build_household_graph, ensure_profile_isolation  # noqa: E402
from app.intelligence.dossiers import Dossier  # noqa: E402
from app.intelligence.future_situations import build_future_situations  # noqa: E402
from app.intelligence.preparation_planner import build_preparation_plan  # noqa: E402
from app.intelligence.profile import build_profile_context  # noqa: E402
from app.intelligence.readiness import build_readiness_dossier  # noqa: E402

g_ok = build_household_graph(
    principals=[{"tenant": "t1", "person_id": "p1"}, {"tenant": "t1", "person_id": "p2"}],
    relationships=[{"source_person_id": "p1", "target_person_id": "p2", "relationship": "family", "share_scope": "summaries"}],
)
assert ensure_profile_isolation(g_ok) is True
g_bad = build_household_graph(
    principals=[{"tenant": "t1", "person_id": "p1"}, {"tenant": "t1", "person_id": "p2"}],
    relationships=[{"source_person_id": "p1", "target_person_id": "p2", "relationship": "family", "share_scope": "profile"}],
)
assert ensure_profile_isolation(g_bad) is False
print("[SMOKE][HOST][PASS] v1.13 household profile-isolation invariant")

ctx = build_profile_context(tenant="t1", person_id="p1")
dossier = Dossier(
    kind="trip",
    title="Trip Dossier",
    signal_count=3,
    exposure_eur=8500.0,
    risk_hits=("iran",),
    near_term=True,
    evidence=("Booking #1",),
)
situations = build_future_situations(profile=ctx, dossiers=[dossier], calendar_events=[])
readiness = build_readiness_dossier(profile=ctx, dossiers=[dossier], future_situations=situations)
plan = build_preparation_plan(profile=ctx, readiness=readiness, epics=())
assert len(situations) >= 1
assert readiness.status in ("watch", "critical")
assert len(plan.actions) >= 1
print("[SMOKE][HOST][PASS] v1.13 future intelligence core contracts")
