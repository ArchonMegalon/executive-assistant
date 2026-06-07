from __future__ import annotations

from pathlib import Path


def test_room_ready_latest_audio(tmp_path: Path):
    import scripts.memorial_room_ready as room

    older = tmp_path / "manfred-demo-tts.wav"
    newer = tmp_path / "manfred-demo-tts.mp3"
    older.write_bytes(b"a")
    newer.write_bytes(b"b")

    assert room.latest_audio(tmp_path, "manfred") in {older, newer}


def test_room_report_status(tmp_path: Path):
    import scripts.memorial_room_ready as room

    report = room.RoomReport(
        slug="manfred",
        base_url="https://example.test",
        output_dir=str(tmp_path),
        started_at_epoch=0,
    )
    report.results.append(
        room.StepResult(
            name="ok",
            command=["true"],
            cwd=str(tmp_path),
            gate="required",
            returncode=0,
            duration_ms=1,
        )
    )
    assert report.status == "pass"
    report.results.append(
        room.StepResult(
            name="bad",
            command=["false"],
            cwd=str(tmp_path),
            gate="required",
            returncode=1,
            duration_ms=1,
        )
    )
    assert report.status == "fail"
