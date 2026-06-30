from __future__ import annotations

import json
from pathlib import Path

from scripts.materialize_pocket_audio_archive_receipt import build_receipt
from scripts.verify_pocket_audio_archive_receipt import verify


def test_pocket_audio_archive_receipt_redacts_paths_and_transcripts(tmp_path: Path) -> None:
    archive_root = tmp_path / "pocket"
    archive_root.mkdir()
    audio = archive_root / "recording-1.mp3"
    audio.write_bytes(b"audio")
    audio.with_suffix(".json").write_text(json.dumps({"transcript_sha256": "abc"}), encoding="utf-8")
    output = tmp_path / "pocket_audio_archive_receipt.generated.json"

    receipt = build_receipt(
        archive_root=archive_root,
        index_rows=[],
        completion_rows=[],
        output_path=output,
        generated_at="2026-06-30T10:00:00Z",
        root=Path(__file__).resolve().parents[1],
    )

    assert receipt["status"] == "pass"
    assert receipt["transcript_ingest_ready"] is True
    assert receipt["archive_files"]["audio_file_total"] == 1
    assert receipt["archive_files"]["metadata_json_total"] == 1
    assert "archive_root" not in receipt["archive_files"]
    assert receipt["archive_files"]["archive_root_sha256"]
    assert receipt["privacy"]["raw_transcript_text_exposed"] is False
    assert receipt["privacy"]["raw_archive_root_exposed"] is False
    assert verify(output) == []


def test_pocket_audio_archive_receipt_blocks_missing_transcripts(tmp_path: Path) -> None:
    archive_root = tmp_path / "pocket"
    output = tmp_path / "pocket_audio_archive_receipt.generated.json"

    receipt = build_receipt(
        archive_root=archive_root,
        index_rows=[
            {
                "source_id": "recording-1",
                "created_at": "2026-06-30T09:00:00Z",
                "archive_status": "archived",
                "archive_path": "",
                "transcript_length": 0,
            }
        ],
        completion_rows=[],
        output_path=output,
        generated_at="2026-06-30T10:00:00Z",
        root=Path(__file__).resolve().parents[1],
    )

    assert receipt["status"] == "blocked"
    assert receipt["transcript_ingest_ready"] is False
    assert receipt["next_action"] == "sync_pocket_ai_audio_transcripts"
    assert "non_dismissed_rows_missing_transcript:1" in receipt["failures"]
    assert verify(output) == []
