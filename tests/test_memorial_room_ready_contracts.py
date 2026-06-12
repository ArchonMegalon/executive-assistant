from __future__ import annotations

from pathlib import Path


def test_room_ready_latest_audio_prefers_fresh_file(tmp_path: Path) -> None:
    import scripts.memorial_room_ready as room

    older = tmp_path / "manfred-demo-tts.wav"
    newer = tmp_path / "manfred-demo-tts.mp3"
    older.write_bytes(b"a")
    newer.write_bytes(b"b")

    assert room.latest_audio(tmp_path, "manfred") == newer
    assert room.latest_audio(tmp_path, "manfred", newer_than_epoch=newer.stat().st_mtime - 0.01) == newer
    assert room.latest_audio(tmp_path, "manfred", newer_than_epoch=newer.stat().st_mtime + 1.0) is None


def test_room_report_status_tracks_warn_and_fail(tmp_path: Path) -> None:
    import scripts.memorial_room_ready as room

    report = room.RoomReport(slug="manfred", base_url="https://example.test", output_dir=str(tmp_path), started_at_epoch=1)
    report.results.append(room.StepResult("ok", ["true"], str(tmp_path), "required", 0, 1, semantic_status="pass"))
    assert report.status == "pass"

    report.results.append(room.StepResult("warn", ["true"], str(tmp_path), "required", 0, 1, semantic_status="warn"))
    assert report.status == "warn"

    report.results.append(room.StepResult("bad", ["false"], str(tmp_path), "required", 1, 1))
    assert report.status == "fail"


def test_room_ready_treats_optional_avatar_fallback_as_pass(tmp_path: Path) -> None:
    import scripts.memorial_room_ready as room

    result = room.StepResult(
        "showtime",
        ["python3", "scripts/memorial_showtime.py"],
        str(tmp_path),
        "required",
        0,
        1,
        semantic_status="warn",
        semantic_detail={
            "warn_steps": ["launch_snapshot"],
            "warn_codes": ["avatar_video_not_published"],
            "warn_commands": ["python3 scripts/verify_memorial_video_call_avatar_ready.py"],
        },
    )
    report = room.RoomReport(slug="manfred", base_url="https://example.test", output_dir=str(tmp_path), started_at_epoch=1)
    report.results.append(result)

    assert result.effective_status == "pass"
    assert report.status == "pass"


def test_room_ready_extracts_semantic_warn_codes() -> None:
    import scripts.memorial_room_ready as room

    status, detail = room._semantic_from_payload(
        {
            "status": "warn",
            "findings": [{"status": "warn", "code": "lead_silence_short"}],
            "results": [{"name": "audio_probe", "effective_status": "warn"}],
        }
    )

    assert status == "warn"
    assert detail["warn_codes"] == ["lead_silence_short"]
    assert detail["warn_steps"] == ["audio_probe"]


def test_room_ready_preserves_nested_showtime_warning_commands() -> None:
    import scripts.memorial_room_ready as room

    status, detail = room._semantic_from_payload(
        {
            "status": "warn",
            "results": [
                {
                    "name": "launch_snapshot",
                    "effective_status": "warn",
                    "semantic_detail": {
                        "warn_commands": ["python3 scripts/verify_memorial_video_call_avatar_ready.py"],
                        "warn_codes": ["avatar_video_not_published"],
                    },
                }
            ],
        }
    )

    assert status == "warn"
    assert detail["warn_steps"] == ["launch_snapshot"]
    assert detail["warn_commands"] == ["python3 scripts/verify_memorial_video_call_avatar_ready.py"]
    assert detail["warn_codes"] == ["avatar_video_not_published"]


def test_room_ready_builds_avatar_video_check_command() -> None:
    import scripts.memorial_room_ready as room

    command = room.avatar_video_check_command(slug="manfred", base_url="https://example.test")

    assert "verify_memorial_video_call_avatar_ready.py" in " ".join(command)
    assert command[-1] == "--json"
