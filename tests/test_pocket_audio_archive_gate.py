from __future__ import annotations

from pathlib import Path

from scripts.verify_pocket_audio_archive import build_receipt


def _row(
    source_id: str,
    *,
    status: str,
    transcript_length: int = 120,
    archive_path: str = "",
    created_at: str = "2026-06-01 08:00:00+02",
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "created_at": created_at,
        "recording_id": source_id.removeprefix("pocket-recording:"),
        "archive_status": status,
        "archive_path": archive_path,
        "transcript_length": transcript_length,
    }


def _backfill(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_type": "pocket_recording_backfill_completed",
        "created_at": "2026-06-01 08:37:55+02",
        "recording_total": "2",
        "archived_total": "1",
        "archive_dismissed_total": "1",
        "archive_failed_total": "0",
        "failed_total": "0",
        "scan_truncated": "false",
        "teable_index_status": "synced",
        "teable_index_row_total": "2",
        "teable_index_sync_attempted": "true",
    }
    payload.update(overrides)
    return payload


def test_pocket_audio_archive_gate_passes_when_archive_db_and_teable_counts_match(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "recording.mp3"
    metadata = tmp_path / "recording.json"
    archive.write_bytes(b"audio")
    metadata.write_text('{"recording_id":"done-1"}\n', encoding="utf-8")

    receipt = build_receipt(
        archive_root=tmp_path,
        index_rows=[
            _row(
                "pocket-recording:done-1",
                status="archived",
                archive_path=archive.as_posix(),
            ),
            _row("pocket-recording:short-1", status="dismissed", transcript_length=0),
        ],
        completion_rows=[_backfill()],
    )

    assert receipt["status"] == "pass"
    assert receipt["archive_files"]["audio_file_total"] == 1
    assert receipt["database_index"]["latest_archived_total"] == 1
    assert receipt["database_index"]["latest_dismissed_total"] == 1


def test_pocket_audio_archive_gate_passes_when_lane_has_no_archive_data_yet(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "missing-pocket-archive"

    receipt = build_receipt(
        archive_root=archive_root,
        index_rows=[],
        completion_rows=[],
    )

    assert receipt["status"] == "pass"
    assert receipt["evidence_mode"] == "inactive_no_archive_data"
    assert receipt["archive_files"]["archive_root_exists"] is False
    assert receipt["failures"] == []


def test_pocket_audio_archive_gate_passes_when_inactive_archive_root_exists(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "empty-pocket-archive"
    archive_root.mkdir()

    receipt = build_receipt(
        archive_root=archive_root,
        index_rows=[],
        completion_rows=[],
    )

    assert receipt["status"] == "pass"
    assert receipt["evidence_mode"] == "inactive_no_archive_data"
    assert receipt["archive_files"]["archive_root_exists"] is True
    assert receipt["failures"] == []


def test_pocket_audio_archive_gate_fails_closed_on_unindexed_archive_file(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "partial-pocket-archive"
    archive_root.mkdir()
    (archive_root / "recording.mp3").write_bytes(b"audio")

    receipt = build_receipt(
        archive_root=archive_root,
        index_rows=[],
        completion_rows=[],
    )

    assert receipt["status"] == "fail"
    assert receipt["evidence_mode"] == "event_backfill"
    assert receipt["failures"] == ["missing_full_backfill_completion"]


def test_pocket_audio_archive_gate_still_fails_when_index_exists_but_archive_root_is_missing(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "missing-pocket-archive"
    archive = archive_root / "recording.mp3"

    receipt = build_receipt(
        archive_root=archive_root,
        index_rows=[
            _row(
                "pocket-recording:done-1",
                status="archived",
                archive_path=archive.as_posix(),
            )
        ],
        completion_rows=[
            _backfill(
                archived_total="1",
                archive_dismissed_total="0",
                teable_index_row_total="1",
            )
        ],
    )

    assert receipt["status"] == "fail"
    assert f"archive_root_missing:{archive_root}" in receipt["failures"]
    assert "archived_rows_missing_audio_file:1" in receipt["failures"]


def test_pocket_audio_archive_gate_fails_closed_on_missing_audio_or_transcript(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "missing.mp3"

    receipt = build_receipt(
        archive_root=tmp_path,
        index_rows=[
            _row(
                "pocket-recording:done-1",
                status="archived",
                archive_path=archive.as_posix(),
                transcript_length=0,
            ),
        ],
        completion_rows=[
            _backfill(
                archived_total="1",
                archive_dismissed_total="0",
                teable_index_row_total="1",
            )
        ],
    )

    assert receipt["status"] == "fail"
    assert "archived_rows_missing_audio_file:1" in receipt["failures"]
    assert "archived_rows_missing_metadata_file:1" in receipt["failures"]
    assert "non_dismissed_rows_missing_transcript:1" in receipt["failures"]


def test_pocket_audio_archive_gate_fails_when_backfill_or_teable_sync_is_not_clean(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "recording.mp3"
    archive.write_bytes(b"audio")
    archive.with_suffix(".json").write_text("{}\n", encoding="utf-8")

    receipt = build_receipt(
        archive_root=tmp_path,
        index_rows=[
            _row(
                "pocket-recording:done-1",
                status="archived",
                archive_path=archive.as_posix(),
            )
        ],
        completion_rows=[
            _backfill(
                scan_truncated="true",
                archive_failed_total="1",
                teable_index_status="blocked",
                teable_index_sync_attempted="false",
            )
        ],
    )

    assert receipt["status"] == "fail"
    assert "latest_backfill_scan_truncated" in receipt["failures"]
    assert "latest_backfill_archive_failed_total:1" in receipt["failures"]
    assert "latest_backfill_teable_status:blocked" in receipt["failures"]
    assert "latest_backfill_teable_sync_not_attempted" in receipt["failures"]


def test_pocket_audio_archive_gate_keeps_latest_full_backfill_when_newer_incremental_syncs_exist(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "recording.mp3"
    archive.write_bytes(b"audio")
    archive.with_suffix(".json").write_text("{}\n", encoding="utf-8")

    sync_rows = [
        {
            "event_type": "pocket_recording_sync_completed",
            "created_at": f"2026-06-03 08:{minute:02d}:00+02",
            "recording_total": "0",
            "archived_total": "0",
            "archive_dismissed_total": "0",
            "archive_failed_total": "0",
            "failed_total": "0",
            "scan_truncated": "false",
            "teable_index_status": "noop",
            "teable_index_row_total": "0",
            "teable_index_sync_attempted": "false",
        }
        for minute in range(0, 30)
    ]

    receipt = build_receipt(
        archive_root=tmp_path,
        index_rows=[
            _row(
                "pocket-recording:done-1",
                status="archived",
                archive_path=archive.as_posix(),
            )
        ],
        completion_rows=sync_rows
        + [
            _backfill(
                archived_total="1",
                archive_dismissed_total="0",
                teable_index_row_total="1",
            )
        ],
    )

    assert receipt["status"] == "pass"
    assert receipt["latest_backfill"]["created_at"] == "2026-06-01 08:37:55+02"
    assert receipt["latest_backfill"]["archived_total"] == "1"


def test_pocket_audio_archive_gate_can_infer_clean_archive_without_local_events(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "recording.mp3"
    archive.write_bytes(b"audio")
    archive.with_suffix(".json").write_text(
        """
        {
          "recording_id": "done-1",
          "archive_path": "%s",
          "archived_at": "2026-06-02T17:18:45.781034+00:00"
        }
        """
        % archive.as_posix(),
        encoding="utf-8",
    )

    receipt = build_receipt(
        archive_root=tmp_path,
        index_rows=[],
        completion_rows=[],
    )

    assert receipt["status"] == "pass"
    assert receipt["evidence_mode"] == "filesystem_archive_scan"
    assert (
        receipt["latest_backfill"]["event_type"] == "filesystem_archive_scan_completed"
    )
    assert receipt["latest_backfill"]["teable_index_status"] == "filesystem_only"


def test_pocket_audio_archive_gate_can_infer_clean_backfill_from_sync_completion_and_index_rows(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "recording.mp3"
    archive.write_bytes(b"audio")
    archive.with_suffix(".json").write_text(
        '{"recording_id":"done-1"}\n', encoding="utf-8"
    )

    receipt = build_receipt(
        archive_root=tmp_path,
        index_rows=[
            _row(
                "pocket-recording:done-1",
                status="archived",
                archive_path=archive.as_posix(),
            )
        ],
        completion_rows=[
            {
                "event_type": "pocket_recording_sync_completed",
                "created_at": "2026-06-03 08:00:00+02",
                "recording_total": "0",
                "archived_total": "0",
                "archive_dismissed_total": "0",
                "archive_failed_total": "0",
                "failed_total": "0",
                "scan_truncated": "false",
                "teable_index_status": "noop",
                "teable_index_row_total": "0",
                "teable_index_sync_attempted": "false",
            }
        ],
    )

    assert receipt["status"] == "pass"
    assert receipt["evidence_mode"] == "sync_index_inferred_backfill"
    assert (
        receipt["latest_backfill"]["event_type"]
        == "pocket_recording_sync_index_inferred"
    )
    assert receipt["latest_backfill"]["archived_total"] == "1"
