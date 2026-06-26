from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.proactive_ooda_context_grounding import ground_digest_with_context
from app.services.proactive_ooda_service import ProactiveOodaService


def _digest_with_stage():
    return ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:contextual",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Prepare a contextual shortlist",
                "summary": "A reversible next step is possible.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "Prepare the contextual shortlist."},
                        "orient": {"summary": "Stored context should influence the recommendation."},
                        "decide": {"summary": "Approve whether EA should proceed.", "approval_required": True},
                        "act": {
                            "summary": "Stage the shortlist for approval.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "One contextual shortlist ready for approval.",
                                "candidate_items": [
                                    {"label": "Candidate A", "url": "https://example.test/item-a", "delivery_days": 2}
                                ],
                            },
                            "external_action_policy": "Do not buy, book, send, cancel, post, or commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )


def test_ground_digest_with_context_merges_preferences_deadlines_and_candidate_assessments() -> None:
    digest = _digest_with_stage()
    deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()

    grounded = ground_digest_with_context(
        digest,
        context_pack={
            "summary": "2 active commitments, 1 commitment risk",
            "commitment_risks": [
                {
                    "summary": "Anniversary delivery window needs attention.",
                    "due_at": deadline,
                    "severity": "high",
                }
            ],
            "decision_windows": [
                {
                    "title": "Approve the household shortlist",
                    "closes_at": deadline,
                    "authority_required": "executive",
                }
            ],
            "stakeholders": [
                {
                    "display_name": "Partner",
                    "authority_level": "primary",
                    "tone_pref": "warm",
                }
            ],
            "follow_ups": [
                {
                    "topic": "Confirm delivery timing",
                    "due_at": deadline,
                    "channel_hint": "telegram",
                }
            ],
        },
        preference_bundle={
            "preference_nodes": [
                {"domain": "general", "category": "constraint", "key": "max_budget", "value_json": 100, "status": "active"},
                {
                    "domain": "general",
                    "category": "constraint",
                    "key": "require_reversible_before_approval",
                    "value_json": True,
                    "status": "active",
                },
                {
                    "domain": "general",
                    "category": "soft_preference",
                    "key": "preferred_keywords",
                    "value_json": ["cool weather"],
                    "status": "active",
                },
                {
                    "domain": "general",
                    "category": "aversion",
                    "key": "avoided_tags",
                    "value_json": ["indoor"],
                    "status": "active",
                },
            ]
        },
        assess_candidate=lambda _domain, _object_type, _object_id, _payload: {
            "fit_score": 82.0,
            "recommendation": "shortlist",
            "match_reasons_json": ["Matches stored profile"],
            "mismatch_reasons_json": [],
            "blocking_constraints_json": [],
        },
    )

    payload = dict(grounded.items[0].stage_payload or {})

    assert payload["budget"]["max"] == 100
    assert "reversible before approval" in payload["requirements"]
    assert "keywords cool weather" in payload["preferences"]
    assert "tags indoor" in payload["exclusions"]
    assert payload["deadline"] == deadline
    assert any("2 active commitments" in value for value in payload["notes"])
    assert any("Anniversary delivery window needs attention." in value for value in payload["notes"])
    assert payload["recipient_context"]["stakeholders"][0]["display_name"] == "Partner"
    assert payload["candidate_items"][0]["preference_assessment"]["fit_score"] == 82.0
