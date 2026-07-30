from __future__ import annotations

from scripts.booka_book_worker import FULL_MANUSCRIPT_BLOCKER, _classify_generation_state


def test_outline_review_is_not_reported_as_completed_story() -> None:
    for marker in ("PHASE 2: STRUCTURE", "Refine Your Outline"):
        state = _classify_generation_state({"bodyText": f"First Book AI\n{marker}\nChapter 1"})

        assert state == {
            "render_status": "outline_ready",
            "generation_stage": "outline_review",
            "deliverable_kind": "outline_review_capture",
            "full_manuscript_ready": False,
            "blocker": FULL_MANUSCRIPT_BLOCKER,
            "next_safe_action": "Review the outline, generate every chapter in First Book AI, then export the complete manuscript.",
        }


def test_unconfirmed_framework_capture_remains_partial() -> None:
    state = _classify_generation_state({"bodyText": "Define Your Book"})

    assert state["render_status"] == "partial"
    assert state["generation_stage"] == "framework_capture_incomplete"
    assert state["deliverable_kind"] == "diagnostic_capture"
    assert state["full_manuscript_ready"] is False
    assert state["blocker"] == "first_book_outline_not_confirmed"


def test_empty_capture_cannot_claim_full_manuscript() -> None:
    state = _classify_generation_state({})

    assert state["render_status"] != "completed"
    assert state["full_manuscript_ready"] is False
    assert state["blocker"]
