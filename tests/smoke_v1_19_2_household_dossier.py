from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_household_dossier_module_and_wiring_presence() -> None:
    dossiers_src = (ROOT / "ea/app/intelligence/dossiers.py").read_text(encoding="utf-8")
    future_src = (ROOT / "ea/app/intelligence/future_situations.py").read_text(encoding="utf-8")
    readiness_src = (ROOT / "ea/app/intelligence/readiness.py").read_text(encoding="utf-8")
    critical_src = (ROOT / "ea/app/intelligence/critical_lane.py").read_text(encoding="utf-8")
    brief_src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")

    assert "def build_household_ops_dossier(" in dossiers_src
    assert "household_ops_window" in future_src
    assert 'if dossier.kind == "household_ops"' in readiness_src
    assert 'elif d.kind == "household_ops"' in critical_src
    assert "build_household_ops_dossier" in brief_src
    _pass("v1.19.2 household dossier module+wiring presence")


def test_household_dossier_behavior_contracts() -> None:
    from app.intelligence.critical_lane import build_critical_actions
    from app.intelligence.dossiers import build_household_ops_dossier
    from app.intelligence.future_situations import build_future_situations
    from app.intelligence.profile import build_profile_context
    from app.intelligence.readiness import build_readiness_dossier

    start = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    dossier = build_household_ops_dossier(
        mails=[
            {
                "subject": "Final notice: utility bill overdue",
                "snippet": "Service interruption possible if unpaid.",
            }
        ],
        calendar_events=[
            {
                "summary": "Plumber service visit",
                "start": {"dateTime": start},
                "location": "Home",
            }
        ],
    )
    assert dossier.kind == "household_ops"
    assert dossier.signal_count >= 1
    assert dossier.near_term
    assert "overdue" in dossier.risk_hits or "service_interruption" in dossier.risk_hits

    profile = build_profile_context(tenant="ea_bot", person_id="tibor")
    future = build_future_situations(profile=profile, dossiers=[dossier], calendar_events=[], horizon_hours=96)
    assert "household_ops_window" in {s.kind for s in future}

    readiness = build_readiness_dossier(profile=profile, dossiers=[dossier], future_situations=future)
    text = " ".join(readiness.blockers + readiness.watch_items).lower()
    assert "household" in text

    critical = build_critical_actions(profile, [dossier], future_situations=future)
    critical_text = " ".join(critical.actions).lower()
    assert "household" in critical_text
    assert critical.decision_window_score >= 60
    _pass("v1.19.2 household dossier behavior contracts")


if __name__ == "__main__":
    test_household_dossier_module_and_wiring_presence()
    test_household_dossier_behavior_contracts()
