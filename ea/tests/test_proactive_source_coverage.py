from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import ea_live_ops  # noqa: E402


def _report_for(rows: list[dict[str, object]]) -> dict[str, object]:
    return ea_live_ops._proactive_source_coverage_report(  # noqa: SLF001
        principal_id="principal-test",
        rows=rows,
        observation_repository="PostgresObservationRepository",
        observed_at="2026-06-30T10:00:00+00:00",
        observation_limit=400,
        source="unit_test",
    )


def _pocket_lane(report: dict[str, object]) -> dict[str, object]:
    lanes = [dict(row) for row in list(report.get("lanes") or [])]
    return next(row for row in lanes if row.get("key") == "pocket_ai_audio_transcripts")


def test_pocket_source_coverage_requires_archive_indexed_transcript_event() -> None:
    report = _report_for(
        [
            {
                "channel": "pocket",
                "event_type": "pocket_recording_sync_completed",
                "created_at": "2026-06-30T09:00:00+00:00",
                "payload_keys": ["recording_count"],
                "hints": ["pocket_ai_audio_transcripts", "recording"],
            }
        ]
    )

    lane = _pocket_lane(report)

    assert lane["status"] == "missing_required_event_type"
    assert lane["observed"] is False
    assert lane["record_count"] == 1
    assert lane["required_event_types"] == ["pocket_recording_archive_indexed"]
    assert lane["required_event_type_observed"] is False
    assert lane["missing_required_event_types"] == ["pocket_recording_archive_indexed"]
    assert lane["next_action"] == "sync_pocket_ai_audio_transcripts"
    assert "pocket_ai_audio_transcripts" in report["missing_lane_keys"]


def test_pocket_source_coverage_accepts_archive_indexed_transcript_event() -> None:
    report = _report_for(
        [
            {
                "channel": "pocket",
                "event_type": "pocket_recording_archive_indexed",
                "created_at": "2026-06-30T09:30:00+00:00",
                "payload_keys": ["transcript_sha256", "duration_seconds"],
                "hints": ["pocket_ai_audio_transcripts", "transcript"],
            }
        ]
    )

    lane = _pocket_lane(report)

    assert lane["status"] == "observed"
    assert lane["observed"] is True
    assert lane["required_event_type_observed"] is True
    assert lane["missing_required_event_types"] == []
    assert "pocket_recording_archive_indexed" in lane["evidence_event_types"]
    assert lane["raw_transcript_text_exposed"] is False
