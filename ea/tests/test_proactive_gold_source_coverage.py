from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import materialize_proactive_ooda_gold_acceptance as gold_acceptance  # noqa: E402


def test_gold_operator_runtime_blocks_when_source_coverage_has_missing_lane() -> None:
    ready, detail = gold_acceptance._operator_runtime_source_coverage_posture(  # noqa: SLF001
        {
            "source_coverage": {
                "checked": True,
                "status": "ready_with_gaps",
                "lane_count": 8,
                "observed_lane_count": 7,
                "missing_lane_keys": ["pocket_ai_audio_transcripts"],
                "lanes": [
                    {
                        "key": "pocket_ai_audio_transcripts",
                        "observed": False,
                        "next_action": "sync_pocket_ai_audio_transcripts",
                        "missing_required_event_types": ["pocket_recording_archive_indexed"],
                    }
                ],
            }
        }
    )

    assert ready is False
    assert detail["source_coverage_ready"] is False
    assert detail["source_coverage_status"] == "ready_with_gaps"
    assert detail["source_coverage_missing_lane_keys"] == ["pocket_ai_audio_transcripts"]
    assert detail["source_coverage_missing_required_event_types"] == ["pocket_recording_archive_indexed"]
    assert detail["next_action"] == "sync_pocket_ai_audio_transcripts"


def test_gold_operator_runtime_accepts_complete_source_coverage() -> None:
    ready, detail = gold_acceptance._operator_runtime_source_coverage_posture(  # noqa: SLF001
        {
            "source_coverage": {
                "checked": True,
                "status": "ready",
                "lane_count": 8,
                "observed_lane_count": 8,
                "missing_lane_keys": [],
                "lanes": [
                    {
                        "key": "pocket_ai_audio_transcripts",
                        "observed": True,
                        "next_action": "",
                        "missing_required_event_types": [],
                    }
                ],
            }
        }
    )

    assert ready is True
    assert detail["source_coverage_ready"] is True
    assert detail["source_coverage_missing_lane_keys"] == []
    assert detail["source_coverage_missing_required_event_types"] == []


def test_assistant_grade_quality_accepts_clean_safe_work_from_noisy_transcript() -> None:
    proof, present = gold_acceptance._assistant_grade_packet_quality_proof(  # noqa: SLF001
        stage_packet={
            "stage": {
                "kind": "approval_packet",
                "payload": {
                    "adapter_hint": "transcript_signal",
                    "work_type": "draft",
                    "draft_request_text": (
                        "[Mikrofongeraeusche] Also ich bin ein bisschen nervoes. "
                        "Ich bin entlassen worden."
                    ),
                    "research_query": "Elektriker fuer zusaetzliche Steckdosen",
                    "search_queries": ["Elektriker fuer zusaetzliche Steckdosen"],
                },
            },
            "safe_work_order": {"work_type": "draft"},
        },
        safe_work_result={
            "work_type": "draft",
            "audit": {"status": "pass", "issues": []},
            "execution_receipt": {
                "search_queries_used": ["Elektriker fuer zusaetzliche Steckdosen 1200 Wien"],
            },
            "recommended_option_or_draft": {
                "kind": "draft_text",
                "value": "Draft to review: Elektriker fuer zusaetzliche Steckdosen",
            },
            "shortlist": [{"label": "Elektriker 1200 Wien"}],
        },
        packet_artifacts_match_run_receipt=True,
    )

    assert present is True
    assert proof["status"] == "pass"
    assert proof["issues"] == []
