from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_human_compose_module_presence() -> None:
    src = (ROOT / "ea/app/intelligence/human_compose.py").read_text(encoding="utf-8")
    assert "def compose_briefing_html(" in src
    assert "Immediate Action" in src
    assert "Why It Matters" in src
    assert "Preparation Plan" in src
    assert "What Changed" in src
    _pass("v1.19.3 human compose module presence")


def test_human_compose_degraded_confidence_no_false_all_clear() -> None:
    from app.intelligence.human_compose import compose_briefing_html

    critical = SimpleNamespace(actions=(), evidence=(), exposure_score=0, decision_window_score=0)
    readiness = SimpleNamespace(status="watch", score=72, blockers=(), watch_items=("runtime recovered",))
    prep = SimpleNamespace(actions=(), confidence_note="some checks may be incomplete")
    html, options = compose_briefing_html(
        compose_mode="low_confidence",
        critical=critical,
        readiness=readiness,
        prep_plan=prep,
        ranked_epics=[],
        epic_deltas=[],
        llm_obj={"emails": [], "calendar_summary": "today"},
        loops_txt="",
        confidence_note="runtime recovered recently",
    )
    lowered = html.lower()
    assert "no critical items require your immediate attention" not in lowered
    assert "runtime confidence is reduced" in lowered
    assert "immediate action" not in lowered
    assert options == []
    _pass("v1.19.3 degraded confidence compose behavior")


def test_human_compose_prioritizes_non_travel_critical_actions() -> None:
    from app.intelligence.human_compose import compose_briefing_html

    critical = SimpleNamespace(
        actions=(
            "Finance commitment deadline closes today; assign a decision owner now.",
            "Project prep gap detected for tomorrow board meeting.",
        ),
        evidence=("invoice thread", "board calendar entry"),
        exposure_score=81,
        decision_window_score=77,
    )
    readiness = SimpleNamespace(
        status="critical",
        score=39,
        blockers=("High-impact decisions are missing clear owners.",),
        watch_items=("meeting prep window active",),
    )
    prep = SimpleNamespace(
        actions=("Assign owner and stage draft response", "Prepare decision pack before lunch"),
        confidence_note="runtime healthy",
    )
    html, _ = compose_briefing_html(
        compose_mode="risk_mode",
        critical=critical,
        readiness=readiness,
        prep_plan=prep,
        ranked_epics=[],
        epic_deltas=[],
        llm_obj={"emails": [], "calendar_summary": "today"},
        loops_txt="",
        confidence_note=None,
    )
    lowered = html.lower()
    assert "<b>immediate action:</b>" in lowered
    assert "finance commitment deadline closes today" in lowered
    assert "project prep gap detected" in lowered
    assert "risk urgency:" in lowered
    assert "decision window:" in lowered
    _pass("v1.19.3 non-travel critical promotion behavior")


def test_human_compose_sanitizes_internal_terms() -> None:
    from app.intelligence.human_compose import compose_briefing_html

    critical = SimpleNamespace(actions=(), evidence=(), exposure_score=0, decision_window_score=0)
    readiness = SimpleNamespace(status="watch", score=80, blockers=(), watch_items=())
    prep = SimpleNamespace(actions=(), confidence_note="")
    html, _ = compose_briefing_html(
        compose_mode="standard",
        critical=critical,
        readiness=readiness,
        prep_plan=prep,
        ranked_epics=[],
        epic_deltas=[],
        llm_obj={
            "emails": [
                {
                    "sender": "Ops",
                    "subject": "statusCode <500>",
                    "churchill_action": "Check & resolve",
                    "action_button": "Review",
                }
            ],
            "calendar_summary": "Traceback <details>",
        },
        loops_txt="",
        confidence_note=None,
    )
    assert "statuscode &lt;500&gt;" in html.lower()
    assert "traceback &lt;details&gt;" in html.lower()
    assert "⚙️ diagnostics" not in html.lower()
    _pass("v1.19.3 user-surface html escaping behavior")


if __name__ == "__main__":
    test_human_compose_module_presence()
    test_human_compose_degraded_confidence_no_false_all_clear()
    test_human_compose_prioritizes_non_travel_critical_actions()
    test_human_compose_sanitizes_internal_terms()
