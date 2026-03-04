from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_profile_persistence_contracts() -> None:
    profile_src = (ROOT / "ea/app/intelligence/profile.py").read_text(encoding="utf-8")
    db_src = (ROOT / "ea/app/db.py").read_text(encoding="utf-8")
    assert "def _load_profile_state(" in profile_src
    assert "def _load_interest_profile(" in profile_src
    assert "def save_profile_context(" in profile_src
    assert "CREATE TABLE IF NOT EXISTS profile_context_state" in db_src
    assert (ROOT / "ea/schema/20260304_v1_19_1_profile_core.sql").exists()
    _pass("v1.19.1 profile persistence contracts")


def test_profile_context_prefers_persisted_state() -> None:
    import app.intelligence.profile as profile_mod

    original_state_loader = profile_mod._load_profile_state
    original_interest_loader = profile_mod._load_interest_profile
    try:
        profile_mod._load_profile_state = lambda tenant, person_id: {
            "stable": {
                "tone": "warm",
                "urgency_tolerance": "low",
                "noise_suppression_mode": "balanced",
                "spending_sensitivity": "medium",
                "quiet_hours": "22:00-06:00",
            },
            "situational": {
                "mode": "travel_mode",
                "timezone": "Europe/Vienna",
                "location_hint": "Vienna",
            },
            "learned": {
                "preferred_sources": ["calendar"],
                "sticky_dislikes": ["cold outreach"],
                "top_domains": ["travel"],
            },
            "confidence": {
                "state": "healthy",
                "score": 0.88,
                "note": "Persisted confidence",
            },
        }
        profile_mod._load_interest_profile = lambda tenant, person_id: {
            "preferred_sources": ("gmail",),
            "sticky_dislikes": ("promo",),
            "top_domains": ("family_ops",),
        }
        ctx = profile_mod.build_profile_context(
            tenant="ea_bot",
            person_id="tibor",
            timezone_name="",
            mode=None,
            location_hint=None,
            runtime_confidence_note=None,
        )
        assert ctx.stable.tone == "warm"
        assert ctx.stable.quiet_hours == "22:00-06:00"
        assert ctx.situational.mode == "travel_mode"
        assert ctx.situational.timezone == "Europe/Vienna"
        assert ctx.situational.location_hint == "Vienna"
        assert "calendar" in ctx.learned.preferred_sources
        assert "gmail" in ctx.learned.preferred_sources
        assert "cold outreach" in ctx.learned.sticky_dislikes
        assert "promo" in ctx.learned.sticky_dislikes
        assert "travel" in ctx.learned.top_domains
        assert "family_ops" in ctx.learned.top_domains
        assert ctx.confidence.state == "healthy"
        assert abs(ctx.confidence.score - 0.88) < 1e-9
        assert ctx.confidence.note == "Persisted confidence"
    finally:
        profile_mod._load_profile_state = original_state_loader
        profile_mod._load_interest_profile = original_interest_loader
    _pass("v1.19.1 profile context persisted-state merge")


def test_runtime_note_overrides_persisted_confidence() -> None:
    import app.intelligence.profile as profile_mod

    original_state_loader = profile_mod._load_profile_state
    original_interest_loader = profile_mod._load_interest_profile
    try:
        profile_mod._load_profile_state = lambda tenant, person_id: {
            "stable": {},
            "situational": {},
            "learned": {},
            "confidence": {"state": "healthy", "score": 0.99, "note": "ok"},
        }
        profile_mod._load_interest_profile = lambda tenant, person_id: {
            "preferred_sources": (),
            "sticky_dislikes": (),
            "top_domains": (),
        }
        ctx = profile_mod.build_profile_context(
            tenant="ea_bot",
            person_id="tibor",
            runtime_confidence_note="runtime degraded after watchdog auto-restart",
        )
        assert ctx.confidence.state == "degraded"
        assert ctx.confidence.score <= 0.55
        assert "runtime degraded" in ctx.confidence.note
    finally:
        profile_mod._load_profile_state = original_state_loader
        profile_mod._load_interest_profile = original_interest_loader
    _pass("v1.19.1 runtime confidence precedence")


if __name__ == "__main__":
    test_profile_persistence_contracts()
    test_profile_context_prefers_persisted_state()
    test_runtime_note_overrides_persisted_confidence()
