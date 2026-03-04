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


def test_health_dossier_module_and_wiring_presence() -> None:
    dossiers_src = (ROOT / "ea/app/intelligence/dossiers.py").read_text(encoding="utf-8")
    future_src = (ROOT / "ea/app/intelligence/future_situations.py").read_text(encoding="utf-8")
    readiness_src = (ROOT / "ea/app/intelligence/readiness.py").read_text(encoding="utf-8")
    critical_src = (ROOT / "ea/app/intelligence/critical_lane.py").read_text(encoding="utf-8")
    brief_src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")

    assert "def build_health_dossier(" in dossiers_src
    assert "health_watch_window" in future_src
    assert 'if dossier.kind == "health"' in readiness_src
    assert 'elif d.kind == "health"' in critical_src
    assert "build_health_dossier" in brief_src
    _pass("v1.19.2 health dossier module+wiring presence")


def test_health_dossier_behavior_contracts() -> None:
    from app.intelligence.critical_lane import build_critical_actions
    from app.intelligence.dossiers import build_health_dossier
    from app.intelligence.future_situations import build_future_situations
    from app.intelligence.profile import build_profile_context
    from app.intelligence.readiness import build_readiness_dossier

    t_start = (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()
    health = build_health_dossier(
        mails=[
            {
                "subject": "Urgent clinic follow-up required",
                "snippet": "Worsening symptoms; doctor requested immediate review.",
            }
        ],
        calendar_events=[
            {
                "summary": "Physio therapy session",
                "start": {"dateTime": t_start},
                "location": "Clinic",
            }
        ],
    )
    assert health.kind == "health"
    assert health.signal_count >= 1
    assert health.near_term
    assert "urgent" in health.risk_hits or "worsening" in health.risk_hits

    profile = build_profile_context(tenant="ea_bot", person_id="tibor")
    future = build_future_situations(profile=profile, dossiers=[health], calendar_events=[], horizon_hours=72)
    kinds = {s.kind for s in future}
    assert "health_watch_window" in kinds

    readiness = build_readiness_dossier(profile=profile, dossiers=[health], future_situations=future)
    assert readiness.status in {"watch", "critical"}
    assert any("health" in b.lower() for b in readiness.blockers + readiness.watch_items)

    critical = build_critical_actions(profile, [health], future_situations=future)
    critical_text = " ".join(critical.actions).lower()
    assert "health" in critical_text
    assert critical.decision_window_score >= 70
    _pass("v1.19.2 health dossier behavior contracts")


if __name__ == "__main__":
    test_health_dossier_module_and_wiring_presence()
    test_health_dossier_behavior_contracts()
