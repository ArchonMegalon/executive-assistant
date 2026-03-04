from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_missingness_module_presence() -> None:
    src = (ROOT / "ea/app/intelligence/missingness.py").read_text(encoding="utf-8")
    assert "class MissingnessSignal" in src
    assert "def build_missingness_signals(" in src
    _pass("v1.19.2 missingness module presence")


def test_missingness_behavior_and_readiness_wiring() -> None:
    from app.intelligence.dossiers import Dossier
    from app.intelligence.future_situations import FutureSituation
    from app.intelligence.missingness import build_missingness_signals
    from app.intelligence.profile import build_profile_context
    from app.intelligence.readiness import build_readiness_dossier

    profile = build_profile_context(tenant="ea_bot", person_id="tibor")
    trip = Dossier(
        kind="trip",
        title="Trip Dossier",
        signal_count=3,
        exposure_eur=9500.0,
        risk_hits=("advisory",),
        near_term=True,
        evidence=("Flight booking Zurich", "Layover advisory"),
    )
    finance = Dossier(
        kind="finance_commitment",
        title="Finance Commitment Dossier",
        signal_count=2,
        exposure_eur=2200.0,
        risk_hits=("final_notice",),
        near_term=True,
        evidence=("Invoice due tomorrow",),
    )
    project = Dossier(
        kind="project",
        title="Project Dossier",
        signal_count=2,
        exposure_eur=0.0,
        risk_hits=tuple(),
        near_term=True,
        evidence=("Client sync",),
    )
    future = (
        FutureSituation(
            kind="meeting_prep_window",
            title="Project prep window",
            horizon_hours=72,
            confidence=0.8,
            evidence=("Client sync",),
        ),
        FutureSituation(
            kind="deadline_window",
            title="Finance deadline window",
            horizon_hours=72,
            confidence=0.8,
            evidence=("Invoice due tomorrow",),
        ),
    )

    signals = build_missingness_signals(
        dossiers=[trip, finance, project],
        future_situations=future,
    )
    kinds = {s.kind for s in signals}
    assert "travel_support_gap" in kinds
    assert "decision_owner_missing" in kinds
    assert "prep_gap" in kinds

    readiness = build_readiness_dossier(
        profile=profile,
        dossiers=[trip, finance, project],
        future_situations=future,
    )
    blockers_text = " ".join(readiness.blockers).lower()
    actions_text = " ".join(readiness.suggested_actions).lower()
    assert "decision owner" in blockers_text
    assert "travel support" in actions_text or "hotel" in actions_text
    _pass("v1.19.2 missingness behavior + readiness wiring")


if __name__ == "__main__":
    test_missingness_module_presence()
    test_missingness_behavior_and_readiness_wiring()
