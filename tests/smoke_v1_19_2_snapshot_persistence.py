from __future__ import annotations

from datetime import datetime, timezone
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_snapshot_module_and_wiring_presence() -> None:
    snap_src = (ROOT / "ea/app/intelligence/snapshots.py").read_text(encoding="utf-8")
    brief_src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")
    db_src = (ROOT / "ea/app/db.py").read_text(encoding="utf-8")
    schema_sql = ROOT / "ea/schema/20260304_v1_19_2_intelligence_snapshots.sql"

    assert "def save_intelligence_snapshot(" in snap_src
    assert "INSERT INTO intelligence_snapshots" in snap_src
    assert "save_intelligence_snapshot" in brief_src
    assert 'source="briefing_compose"' in brief_src
    assert "CREATE TABLE IF NOT EXISTS intelligence_snapshots" in db_src
    assert schema_sql.exists()
    _pass("v1.19.2 snapshot persistence module+wiring presence")


def test_snapshot_persistence_behavior_contract() -> None:
    from app.intelligence.critical_lane import CriticalLaneResult
    from app.intelligence.dossiers import Dossier
    from app.intelligence.future_situations import FutureSituation
    from app.intelligence.preparation_planner import PreparationPlan
    from app.intelligence.profile import (
        ConfidenceProfile,
        LearnedProfile,
        PersonProfileContext,
        SituationalProfile,
        StableProfile,
    )
    from app.intelligence.readiness import ReadinessDossier
    from app.intelligence.snapshots import save_intelligence_snapshot

    class _FakeDB:
        def __init__(self):
            self.calls = []

        def execute(self, query, params):
            self.calls.append((str(query), params))

    fake_db = _FakeDB()
    original_app_db = sys.modules.get("app.db")
    try:
        sys.modules["app.db"] = types.SimpleNamespace(get_db=lambda: fake_db)
        profile = PersonProfileContext(
            tenant="ea_bot",
            person_id="tibor",
            stable=StableProfile(),
            situational=SituationalProfile(timestamp_utc=datetime.now(timezone.utc)),
            learned=LearnedProfile(),
            confidence=ConfidenceProfile(state="degraded", score=0.5, note="runtime recovered"),
        )
        dossiers = [
            Dossier(
                kind="trip",
                title="Trip",
                signal_count=1,
                exposure_eur=15000.0,
                risk_hits=("tel aviv",),
                near_term=True,
                evidence=("Booking mail",),
            )
        ]
        future = (
            FutureSituation(
                kind="risk_intersection",
                title="Travel route intersects risk signals",
                horizon_hours=72,
                confidence=0.8,
                evidence=("Booking mail",),
            ),
        )
        readiness = ReadinessDossier(
            status="critical",
            score=40,
            blockers=("High-value trip exposure requires explicit review.",),
            watch_items=("Departure window is near-term.",),
            suggested_actions=("Validate cancellation terms now.",),
            evidence=("Booking mail",),
        )
        critical = CriticalLaneResult(
            actions=("Validate cancellation/rebooking terms today.",),
            evidence=("Booking mail",),
            exposure_score=88,
            decision_window_score=82,
        )
        prep = PreparationPlan(
            actions=("Treat readiness as critical and handle blockers first.",),
            deferred=(),
            confidence_note="runtime recovered",
        )
        ok = save_intelligence_snapshot(
            tenant="ea_bot",
            person_id="tibor",
            compose_mode="risk_mode",
            profile=profile,
            dossiers=dossiers,
            future_situations=future,
            readiness=readiness,
            critical=critical,
            preparation=prep,
            epics=(),
            source="briefing_compose",
        )
        assert ok
        assert fake_db.calls, "expected DB write call"
        query, params = fake_db.calls[-1]
        assert "intelligence_snapshots" in query
        payload = json.loads(str(params[4] or "{}"))
        assert payload.get("readiness", {}).get("status") == "critical"
        assert payload.get("critical", {}).get("exposure_score") == 88
        assert payload.get("dossiers", [{}])[0].get("kind") == "trip"
    finally:
        if original_app_db is None:
            sys.modules.pop("app.db", None)
        else:
            sys.modules["app.db"] = original_app_db
    _pass("v1.19.2 snapshot persistence behavior contract")


if __name__ == "__main__":
    test_snapshot_module_and_wiring_presence()
    test_snapshot_persistence_behavior_contract()
